from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.auth import current_user_id
from api.jobs.manager import JobManager, JobQueueFullError
from api.rate_limit import RateLimitExceeded, SlidingWindowRateLimiter
from api.repositories.postgres_run_repository import InvalidCursor, PostgresRunRepository
from api.schemas.models import (
    ComparisonRequest,
    CorpusKind,
    ComparisonResponse,
    MatchJobRequest,
    MatchJobResponse,
    MetaResponse,
    RunDetail,
    RunListResponse,
    SaveMatchRequest,
    SavedMatchListResponse,
    SavedMatchResponse,
)
from api.serialization import run_detail, run_list_item, saved_match_response
from api.services.compare_service import compare_runs
from api.services.csv_export import build_csv
from src import config, vector_store
from src.corpora import DEFAULT_KIND, KINDS, get_corpus, kind_for_record
from src.platforms import PLATFORMS

logger = logging.getLogger(__name__)


def _unavailable(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": code, "message": message},
    )


def _require_ready(request: Request, kind: str = DEFAULT_KIND) -> None:
    """The single readiness gate, so the two callers cannot disagree.

    These were two ladders over the same three conditions in a different order,
    and they did disagree: /health/ready reported NOT_READY where
    /match-jobs reported INDEX_NOT_READY for an empty index, so a client had to
    know two codes for one state. The mismatch check was also missing from the
    match path entirely, which is how a stale index reached ranking.

    `kind` matters for the last condition only. A corpus that has never been
    indexed has to fail here with its own name, or a Companies search on an
    unindexed corpus returns an empty shortlist and reads as "no companies match"
    -- which is a false statement about the data rather than about the app.
    """
    state = request.app.state
    noun = "creators" if kind == DEFAULT_KIND else "companies"
    if not state.database_available:
        raise _unavailable("DATABASE_UNAVAILABLE", f"The {noun} database is unavailable.")
    if state.index_model_mismatch:
        raise _unavailable(
            "INDEX_MODEL_MISMATCH",
            f"The {noun} index was built with a different embedding model than "
            f"{config.EMBED_MODEL}. It must be re-embedded before matching works.",
        )
    if _count_for(state, kind) <= 0:
        raise _unavailable("NOT_READY", f"The {noun} index is not ready.")


def create_app(
    repository=None,
    job_manager=None,
    initialize_database: bool = True,
    indexed_count: int | None = None,
    indexed_counts: dict[str, int] | None = None,
) -> FastAPI:
    ip_rate_limiter = SlidingWindowRateLimiter(
        config.MAX_MATCH_JOBS_PER_IP_PER_HOUR,
        window_seconds=3600,
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        if config.APP_ENV in {"demo", "production"}:
            _validate_public_configuration()
        repo = application.state.run_repository
        manager = application.state.job_manager
        application.state.db_ready = False
        application.state.database_available = False
        application.state.index_model_mismatch = False
        application.state.indexed_count = indexed_count or 0
        # Keep the legacy count creator-only; never infer other corpus counts from it.
        # Database initialization replaces this seed with actual per-corpus counts.
        application.state.indexed_counts = (
            indexed_counts
            if indexed_counts is not None
            else ({DEFAULT_KIND: indexed_count} if indexed_count else {})
        )
        application.state.index_checked_at = 0.0
        application.state.startup_error = None
        if initialize_database:
            repo = repo or PostgresRunRepository()
            application.state.run_repository = repo
            try:
                if config.RUN_SCHEMA_ON_STARTUP:
                    counted = await asyncio.to_thread(_initialize_database, repo)
                else:
                    counted = await asyncio.to_thread(_check_database)
                application.state.indexed_counts = counted
                application.state.indexed_count = counted.get(DEFAULT_KIND, 0)
                application.state.database_available = True
                application.state.index_checked_at = time.monotonic()
                application.state.db_ready = application.state.indexed_count > 0
            except vector_store.IndexModelMismatch as exc:
                application.state.database_available = True
                application.state.index_model_mismatch = True
                application.state.indexed_count = 0
                application.state.db_ready = False
                application.state.startup_error = "INDEX_MODEL_MISMATCH"
                logger.error("Creator index needs a reindex: %s", exc)
            except Exception as exc:
                application.state.database_available = False
                application.state.startup_error = type(exc).__name__
                logger.warning("API startup dependency check failed: %s", type(exc).__name__)
        else:
            application.state.database_available = repo is not None
            application.state.db_ready = application.state.database_available and application.state.indexed_count > 0
        if manager is None and repo is not None:
            # Jobs are in-process. The free tier cannot afford a worker, so a
            # restart loses an in-flight match; completed runs are persisted.
            manager = JobManager(
                repo,
                max_jobs=config.MAX_MEMORY_JOBS,
            )
            application.state.job_manager = manager
        yield
        if manager is not None:
            manager.shutdown()

    application = FastAPI(
        title="Influencer Matcher API",
        version="1.0.0",
        lifespan=lifespan,
    )
    application.state.run_repository = repository
    application.state.job_manager = job_manager
    application.state.db_ready = False
    application.state.database_available = repository is not None
    application.state.indexed_count = indexed_count or 0
    application.state.index_checked_at = 0.0
    application.state.startup_error = None
    application.state.uses_database = initialize_database
    application.state.index_model_mismatch = False

    origins = [
        origin.strip()
        for origin in os.environ.get("CORS_ALLOWED_ORIGINS", "http://localhost:5173").split(",")
        if origin.strip()
    ]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization"],
    )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        errors = exc.errors()
        if errors:
            first = errors[0]
            location = ".".join(str(part) for part in first.get("loc", []))
            message = first.get("msg", "Invalid request.")
            if location:
                message = f"{location}: {message}"
        else:
            message = "Invalid request."
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": "VALIDATION_ERROR", "message": message}},
        )

    @application.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception):
        logger.error("Unhandled API error: %s", type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "detail": {
                    "code": "INTERNAL_ERROR",
                    "message": "The API could not complete the request.",
                }
            },
        )

    @application.get("/health/live")
    def live():
        return {"status": "ok", "memory_rss_mb": _rss_mb()}

    @application.get("/health/ready")
    def ready(request: Request):
        _refresh_index_state(request)
        _require_ready(request)
        return {
            "status": "ready",
            "database": True,
            "indexed_creator_count": request.app.state.indexed_count,
            "embedding_model": config.EMBED_MODEL,
            "embed_dimensions": config.EMBED_DIMENSIONS,
            "memory_rss_mb": _rss_mb(),
        }

    @application.get("/api/v1/meta", response_model=MetaResponse)
    def meta(request: Request, kind: CorpusKind = DEFAULT_KIND):
        _refresh_index_state(request)
        corpus = get_corpus(kind)
        return {
            # A corpus without this facet gets no options, since it cannot filter on them.
            "platforms": ["Any", *PLATFORMS] if corpus.facet_column == "platform" else [],
            "defaults": {
                # Keep optional brief fields empty; non-empty defaults would alter every search.
                # Starter prompts belong in the UI, not in the API configuration.
                "goal": "",
                "audience": "",
                "vibe": "",
                "top_k": config.DEFAULT_TOP_K_RETRIEVAL,
                "top_n": config.DEFAULT_TOP_N_RANKED,
            },
            "limits": {
                "top_k_min": 1,
                "top_k_max": config.MAX_TOP_K,
                "top_n_min": 1,
                "top_n_max": config.MAX_TOP_K,
                "audience_max_length": config.AUDIENCE_MAX_LENGTH,
                "vibe_max_length": config.VIBE_MAX_LENGTH,
                "goal_min_length": config.MIN_GOAL_LENGTH,
                "goal_max_length": config.MAX_GOAL_LENGTH,
            },
            "index": {
                # Report readiness from the selected corpus count, matching the request gate.
                "status": (
                    "reindex_required"
                    if request.app.state.index_model_mismatch
                    else "ready" if _count_for(request.app.state, kind) > 0 else "unavailable"
                ),
                "count": _count_for(request.app.state, kind),
                "embedding_model": config.EMBED_MODEL,
                "embed_dimensions": config.EMBED_DIMENSIONS,
            },
            "ranking": {
                "model": config.GEN_MODEL,
                "fit_levels": ["strong", "partial", "weak", "unknown"],
            },
        }

    @application.post(
        "/api/v1/match-jobs",
        response_model=MatchJobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_match_job(payload: MatchJobRequest, request: Request):
        corpus = get_corpus(payload.kind)
        _validate_brief(payload.brief.goal, payload.brief.platform, corpus)
        owner_id = current_user_id(request)
        _refresh_index_state(request)
        _require_ready(request, corpus.kind)
        manager = request.app.state.job_manager
        if manager is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "MATCH_SERVICE_UNAVAILABLE", "message": "The match service is unavailable."},
            )
        if config.APP_ENV == "demo":
            try:
                ip_rate_limiter.check(_client_ip(request))
            except RateLimitExceeded as exc:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={"code": "MATCH_IP_RATE_LIMIT", "message": "The demo match limit has been reached for this network."},
                ) from exc
        try:
            brief = payload.brief.to_domain()
            return manager.submit(brief, payload.params, owner_id=owner_id, corpus=corpus)
        except JobQueueFullError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={"code": "MATCH_QUEUE_FULL", "message": "The match queue is full. Try again shortly."},
            ) from exc

    @application.get("/api/v1/match-jobs/{job_id}", response_model=MatchJobResponse)
    def get_match_job(job_id: UUID, request: Request):
        owner_id = current_user_id(request)
        manager = request.app.state.job_manager
        job = manager.get(job_id, owner_id=owner_id) if manager else None
        if job is None:
            raise _not_found("MATCH_JOB_NOT_FOUND", "Match job not found.")
        return job

    @application.get("/api/v1/runs", response_model=RunListResponse)
    def list_runs(
        request: Request,
        limit: int = Query(default=20, ge=1, le=100),
        cursor: str | None = None,
        kind: CorpusKind | None = None,
    ):
        owner_id = current_user_id(request)
        try:
            repository = _repository(request)
            records, next_cursor = repository.list(
                limit=limit, cursor=cursor, owner_id=owner_id, kind=kind,
            )
        except InvalidCursor as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "INVALID_CURSOR", "message": str(exc)},
            ) from exc
        return {
            "items": [run_list_item(record) for record in records],
            "next_cursor": next_cursor,
        }

    @application.get("/api/v1/runs/{run_id}/export.csv")
    def export_run(run_id: UUID, request: Request):
        owner_id = current_user_id(request)
        repository = _repository(request)
        record = repository.get(run_id, owner_id=owner_id)
        if record is None:
            raise _not_found("RUN_NOT_FOUND", "Run not found.")
        return Response(
            content=build_csv(record),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="shortlist-{run_id}.csv"'},
        )

    @application.get("/api/v1/runs/{run_id}", response_model=RunDetail)
    def get_run(run_id: UUID, request: Request):
        owner_id = current_user_id(request)
        repository = _repository(request)
        record = repository.get(run_id, owner_id=owner_id)
        if record is None:
            raise _not_found("RUN_NOT_FOUND", "Run not found.")
        return run_detail(record)

    @application.delete("/api/v1/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_run(run_id: UUID, request: Request):
        owner_id = current_user_id(request)
        repository = _repository(request)
        deleted = repository.delete(run_id, owner_id=owner_id)
        if not deleted:
            raise _not_found("RUN_NOT_FOUND", "Run not found.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @application.post("/api/v1/comparisons", response_model=ComparisonResponse)
    def compare(payload: ComparisonRequest, request: Request):
        owner_id = current_user_id(request)
        repository = _repository(request)
        run_a = repository.get(payload.run_id_a, owner_id=owner_id)
        run_b = repository.get(payload.run_id_b, owner_id=owner_id)
        if run_a is None or run_b is None:
            raise _not_found("RUN_NOT_FOUND", "One or both runs were not found.")
        # Refused rather than answered. The comparison joins the two runs on
        # candidate keys and differences their summaries; across two corpora
        # every key is distinct, so the honest answer is an empty overlap and
        # a meaningless delta row rather than a 200. Silently succeeding here
        # would look like "these two briefs found nothing in common".
        kind_a = kind_for_record(run_a)
        kind_b = kind_for_record(run_b)
        if kind_a != kind_b:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "CROSS_CORPUS_COMPARE",
                    "message": "Both runs must come from the same panel. "
                               f"One searched {kind_a} and the other {kind_b}.",
                },
            )
        return compare_runs(run_a, run_b, get_corpus(kind_a))

    @application.get("/api/v1/saved-matches", response_model=SavedMatchListResponse)
    def list_saved_matches(request: Request, kind: CorpusKind | None = None):
        owner_id = current_user_id(request)
        repository = _repository(request)
        records = repository.list_saved_matches(owner_id=owner_id, kind=kind)
        return {"items": [saved_match_response(record) for record in records]}

    @application.post(
        "/api/v1/saved-matches",
        response_model=SavedMatchResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def save_match(payload: SaveMatchRequest, request: Request):
        owner_id = current_user_id(request)
        repository = _repository(request)
        record = repository.save_match(payload.run_id, payload.candidate_id, owner_id=owner_id)
        if record is None:
            raise _not_found("RUN_MATCH_NOT_FOUND", "Match not found in your run.")
        return saved_match_response(record)

    @application.delete("/api/v1/saved-matches/{saved_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_saved_match(saved_id: UUID, request: Request):
        owner_id = current_user_id(request)
        repository = _repository(request)
        if not repository.delete_saved_match(saved_id, owner_id=owner_id):
            raise _not_found("SAVED_MATCH_NOT_FOUND", "Saved match not found.")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return application


def _validate_public_configuration() -> None:
    missing = []
    if not config.AUTH_REQUIRED:
        missing.append("AUTH_REQUIRED=true")
    if not config.DATABASE_URL:
        missing.append("DATABASE_URL")
    if not config.GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if not config.SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not (config.SUPABASE_JWT_SECRET or config.SUPABASE_JWKS_URL):
        missing.append("SUPABASE_JWT_SECRET or SUPABASE_JWKS_URL")
    if not os.environ.get("CORS_ALLOWED_ORIGINS", "").strip():
        missing.append("CORS_ALLOWED_ORIGINS")
    if missing:
        raise RuntimeError("Public deployment configuration is missing: " + ", ".join(missing))


def _count_all_corpora(conn) -> dict[str, int]:
    """Every corpus's row count, in one connection.

    Both startup probes and `_refresh_index_state` use this so there is a single
    definition of "how many records are indexed". Counting only the creator table
    and letting the next refresh fill in the rest leaves the company panel showing
    an empty index for as long as the refresh cache holds.
    """
    return {
        corpus.kind: vector_store.count_records(conn, table=corpus.table)
        for corpus in KINDS.values()
    }


def _initialize_database(repository) -> dict[str, int]:
    repository.ensure_schema()
    with vector_store.get_connection() as conn:
        vector_store.init_schema(conn)
        for corpus in KINDS.values():
            vector_store.assert_index_matches_config(conn, table=corpus.table)
        return _count_all_corpora(conn)


def _check_database() -> dict[str, int]:
    with vector_store.get_connection() as conn:
        for corpus in KINDS.values():
            vector_store.assert_index_matches_config(conn, table=corpus.table)
        return _count_all_corpora(conn)


def _rss_mb() -> float | None:
    """Current resident set size in MB, or None where /proc is unavailable.

    The free service dies at 512 MB, so the number that matters is what the
    process is holding right now, not its peak.
    """
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            resident_pages = int(handle.read().split()[1])
        return round(resident_pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024), 1)
    except (OSError, IndexError, ValueError):
        return None


def _refresh_index_state(request: Request) -> None:
    application = request.app
    if not application.state.uses_database:
        return
    now = time.monotonic()
    if application.state.index_checked_at and now - application.state.index_checked_at < 5:
        return
    try:
        with vector_store.get_connection() as conn:
            # Every corpus, not just the default table: migration 009 makes
            # prospects.embedding a literal VECTOR(768), and a deployment with a
            # different EMBED_DIMENSIONS must be caught on both.
            for corpus in KINDS.values():
                vector_store.assert_index_matches_config(conn, table=corpus.table)
            counts = _count_all_corpora(conn)
        application.state.indexed_counts = counts
        # Kept in step with the creator count so the readiness endpoint and the
        # injected `indexed_count=` path keep meaning what they meant.
        application.state.indexed_count = counts.get(DEFAULT_KIND, 0)
        application.state.database_available = True
        application.state.index_checked_at = now
        application.state.startup_error = None
        application.state.index_model_mismatch = False
        application.state.db_ready = application.state.indexed_count > 0
    except vector_store.IndexModelMismatch:
        # Re-checked on every refresh so a reindex run against the live
        # database flips the service back to ready without a redeploy.
        application.state.database_available = True
        application.state.index_checked_at = now
        application.state.index_model_mismatch = True
        application.state.indexed_count = 0
        application.state.db_ready = False
        application.state.startup_error = "INDEX_MODEL_MISMATCH"
    except Exception as exc:
        application.state.database_available = False
        application.state.index_checked_at = now
        application.state.db_ready = False
        application.state.startup_error = type(exc).__name__


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        candidate = forwarded.split(",")[-1].strip()
        if candidate:
            return candidate
    return request.client.host if request.client else "unknown"


def _repository(request: Request):
    repository = request.app.state.run_repository
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "HISTORY_UNAVAILABLE", "message": "Run history is unavailable."},
        )
    return repository


def _validate_brief(goal: str, platform: str, corpus=None) -> None:
    """Free-text briefs are open-ended; only length and platform are checked.

    The old check rejected anything outside the generator's 30 verticals,
    which is what forced brief input to be a taxonomy value rather than a
    description of what the brand actually wants.
    """
    text = (goal or "").strip()
    if len(text) < config.MIN_GOAL_LENGTH:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "GOAL_TOO_SHORT",
                "message": f"Describe what you are promoting in at least {config.MIN_GOAL_LENGTH} characters.",
            },
        )
    if len(text) > config.MAX_GOAL_LENGTH:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "GOAL_TOO_LONG",
                "message": f"Keep the brief under {config.MAX_GOAL_LENGTH} characters.",
            },
        )
    if not any(char.isalnum() for char in text):
        raise HTTPException(
            status_code=422,
            detail={"code": "GOAL_EMPTY", "message": "Describe what you are promoting in words."},
        )
    # Same predicate retrieval uses. A corpus with a facet it does not filter on
    # would otherwise have its brief validated against a list it ignores.
    if corpus is not None and not corpus.filters_by_facet():
        return
    if platform not in {"Any", *PLATFORMS}:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_PLATFORM", "message": "Choose a supported platform."},
        )



def _count_for(state, kind: str) -> int:
    """How many records of `kind` are indexed.

    Reads the per-corpus map and falls back to zero for a corpus the app has no
    count for. The fallback is zero rather than `state.indexed_count` on purpose:
    the creator count means creators, and reusing it would let an unindexed
    corpus pass the readiness gate.
    """
    counts = getattr(state, "indexed_counts", None) or {}
    return counts.get(kind, 0)


def _not_found(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": code, "message": message},
    )


app = create_app()
