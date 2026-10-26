from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import RLock
from typing import Callable
from uuid import UUID, uuid4

from api.schemas.models import MatchJobResponse, MatchParams
from api.serialization import build_run_record
from src.corpora import CREATORS, Corpus
from src.gemini_client import get_client
from src.match_service import rank_match, retrieve_for_run
from src.models import Brief
from src.retrieval import rerank_candidates

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}


class JobQueueFullError(RuntimeError):
    pass


class JobManager:
    """In-memory queue: a restart loses an in-flight match, completed runs are
    persisted separately. The trade the free tier makes."""

    def __init__(
        self,
        repository,
        matcher: Callable | None = None,
        client_factory: Callable | None = None,
        max_workers: int = 1,
        max_jobs: int = 4,
    ):
        self._repository = repository
        self._matcher = matcher or self._default_match
        self._client_factory = client_factory or get_client
        self._max_jobs = max_jobs
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="match-job")
        self._lock = RLock()
        self._jobs: dict[UUID, dict] = {}
        self._client = None

    def submit(
        self,
        brief: Brief,
        params: MatchParams,
        owner_id: str | None = None,
        corpus: Corpus = CREATORS,
    ) -> MatchJobResponse:
        job_id = uuid4()
        now = _now()
        state = {
            "job_id": job_id,
            "owner_id": owner_id,
            # Echoed on the job rather than inferred by the client from its own
            # request: a poll that outlives a panel switch still has to say which
            # corpus it is waiting on.
            "kind": corpus.kind,
            "dataset": "real" if corpus.real_data else "synthetic",
            "status": "queued",
            "stage": "queued",
            "progress": {},
            "run_id": None,
            "outcome": None,
            "error": None,
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._prune_locked()
            if len(self._jobs) >= self._max_jobs:
                raise JobQueueFullError("The match queue is full.")
            self._jobs[job_id] = state
        try:
            self._executor.submit(self._execute, job_id, brief, params, owner_id, corpus)
        except RuntimeError as exc:
            # Executor shut down between releasing the lock and submitting.
            with self._lock:
                self._jobs.pop(job_id, None)
            raise JobQueueFullError("The match service is shutting down.") from exc
        return self.get(job_id)

    def get(self, job_id: UUID, owner_id: str | None = None) -> MatchJobResponse | None:
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None or (owner_id is not None and state.get("owner_id") != owner_id):
                return None
            return MatchJobResponse.model_validate({key: value for key, value in state.items() if key != "owner_id"})

    def shutdown(self) -> None:
        with self._lock:
            for state in self._jobs.values():
                if state["status"] == "queued":
                    state.update(
                        status="cancelled",
                        stage="cancelled",
                        error="The API shut down before this match started.",
                        updated_at=_now(),
                    )
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _execute(
        self,
        job_id: UUID,
        brief: Brief,
        params: MatchParams,
        owner_id: str | None,
        corpus: Corpus = CREATORS,
    ) -> None:
        self._update(job_id, status="running", stage="embedding")
        try:
            result = self._matcher(job_id, brief, params, corpus)
            if result is None:
                self._update(
                    job_id,
                    status="succeeded",
                    stage="complete",
                    outcome="no_results",
                    progress={"retrieved_candidate_count": 0},
                )
                return
            self._update(job_id, stage="persisting")
            record = build_run_record(result, uuid4(), corpus)
            record["owner_id"] = owner_id
            saved = self._repository.create(record)
            self._update(
                job_id,
                status="succeeded",
                stage="complete",
                outcome="match",
                run_id=saved["id"],
            )
        except Exception:
            logger.exception("Match job %s failed", job_id)
            self._update(
                job_id,
                status="failed",
                stage="failed",
                error="The match could not be completed. Check the API service and try again.",
            )

    def _default_match(
        self,
        job_id: UUID,
        brief: Brief,
        params: MatchParams,
        corpus: Corpus = CREATORS,
    ):
        self._update(job_id, stage="retrieval")
        # User intent and reviewed product context are retrieved separately;
        # only the explicit brief fields become filters.
        #
        # `retrieve_for_run`, not the strict retriever: it drops the filters one
        # at a time until the corpus has something to say, and reports which it
        # dropped. A brief whose filters match nothing then comes back with
        # results and an explanation, rather than an empty page that reads as
        # "nothing matched" -- which is a claim about the data, when the truth
        # is about the brief.
        candidates, relaxed = retrieve_for_run(brief, top_k=params.top_k, corpus=corpus)
        if not candidates:
            return None
        candidates = rerank_candidates(brief, candidates, corpus=corpus)
        self._update(job_id, stage="ranking", progress={"retrieved_candidate_count": len(candidates)})
        ranked = rank_match(
            brief,
            candidates,
            top_n=params.top_n,
            client=self._get_client(),
            corpus=corpus,
            relaxed_filters=relaxed,
        )
        return {
            "brief": brief,
            "params": {"top_k": params.top_k, "top_n": params.top_n},
            "candidates": candidates,
            "ranked": ranked,
            # Read back by build_run_record, which turns it into the
            # FILTER_RELAXED warning. Without this the relaxation happened
            # silently and the reader was told a filter they never asked for.
            "relaxed_filters": relaxed,
        }

    def _get_client(self):
        # Double-checked: the factory builds a Gemini client, so it must run once
        # even when several jobs start together.
        if self._client is None:
            with self._lock:
                if self._client is None:
                    self._client = self._client_factory()
        return self._client

    def _prune_locked(self) -> None:
        for job_id, state in list(self._jobs.items()):
            if len(self._jobs) < self._max_jobs:
                break
            if state["status"] in TERMINAL_STATUSES:
                self._jobs.pop(job_id, None)

    def _update(self, job_id: UUID, **changes) -> None:
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                return
            state.update(changes)
            state["updated_at"] = _now()


def _now() -> datetime:
    return datetime.now(timezone.utc)
