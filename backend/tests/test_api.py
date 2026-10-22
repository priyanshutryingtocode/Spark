import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from fastapi.testclient import TestClient

from api.jobs.manager import JobManager
from api.main import create_app
from api.schemas.models import MatchJobResponse, MatchParams
from api.serialization import build_run_record
from src import config
from src.corpora import Influencer
from src.models import Brief


class MemoryRepository:
    def __init__(self):
        self.records = {}

    def ensure_schema(self):
        return None

    def create(self, record, owner_id=None):
        now = datetime.now(timezone.utc)
        saved = dict(record)
        saved["created_at"] = now
        saved["updated_at"] = now
        self.records[saved["id"]] = saved
        return saved

    def list(self, limit, cursor=None, owner_id=None, kind=None):
        records = sorted(
            self.records.values(),
            key=lambda item: (item["created_at"], item["id"]),
            reverse=True,
        )
        # Honours the filter rather than ignoring it: an in-memory stand-in that
        # accepted `kind` and dropped it would make every panel-isolation test
        # pass against a repository that does not isolate anything.
        if kind is not None:
            records = [r for r in records if r.get("kind", "creator") == kind]
        return records[:limit], None

    def get(self, run_id, owner_id=None):
        return self.records.get(run_id)

    def delete(self, run_id, owner_id=None):
        return self.records.pop(run_id, None) is not None


class MemoryJobManager:
    def __init__(self):
        self.jobs = {}

    def submit(self, brief, params, owner_id=None, corpus=None):
        job_id = uuid4()
        now = datetime.now(timezone.utc)
        job = MatchJobResponse(
            job_id=job_id,
            # Echoes the corpus the way JobManager does, so a test can assert the
            # panel's kind reached the job rather than defaulting back to creator.
            kind=getattr(corpus, "kind", "creator"),
            status="queued",
            stage="queued",
            created_at=now,
            updated_at=now,
        )
        self.jobs[job_id] = job
        return job

    def get(self, job_id, owner_id=None):
        return self.jobs.get(job_id)

    def shutdown(self):
        return None


def make_result():
    brief = Brief(
        goal="high-energy strength training for busy millennials",
        platform="TikTok",
        audience="",
        vibe="",
    )
    candidates = [
        Influencer(
            id=1,
            handle="@fit1",
            name="Fit One",
            platform="TikTok",
            city="Austin",
            country="USA",
            language="English",
            followers=10_000,
            engagement=5.0,
            similarity=0.9,
            tags=["gym"],
            bio="Lifting daily.",
        ),
        Influencer(
            id=2,
            handle="@fit2",
            name="Fit Two",
            platform="TikTok",
            city="Austin",
            country="USA",
            language="English",
            followers=20_000,
            engagement=4.0,
            similarity=0.8,
            tags=["stretching"],
            bio="Movement and recovery.",
        ),
    ]
    return {
        "brief": brief,
        "params": {"top_k": 2, "top_n": 1},
        "candidates": candidates,
        "ranked": [{"id": 1, "fit": "strong", "source": "llm", "rationale": "Direct fit."}],
    }


def test_job_manager_persists_match():
    repository = MemoryRepository()
    manager = JobManager(
        repository,
        matcher=lambda job_id, brief, params, corpus: make_result(),
    )
    response = manager.submit(Brief(goal="high-energy strength training for beginners", platform="TikTok"), MatchParams(top_k=2, top_n=1))
    for _ in range(50):
        current = manager.get(response.job_id)
        if current.status in {"succeeded", "failed"}:
            break
        time.sleep(0.01)
    assert current.status == "succeeded"
    assert current.outcome == "match"
    assert current.run_id in repository.records
    manager.shutdown()


def test_api_health_meta_and_match_job():
    repository = MemoryRepository()
    manager = MemoryJobManager()
    app = create_app(
        repository=repository,
        job_manager=manager,
        initialize_database=False,
        indexed_count=10,
    )
    with TestClient(app) as client:
        live = client.get("/health/live").json()
        assert live["status"] == "ok"
        assert live["memory_rss_mb"] is None or live["memory_rss_mb"] > 0
        assert client.get("/health/ready").status_code == 200
        meta = client.get("/api/v1/meta")
        assert meta.status_code == 200
        assert "TikTok" in meta.json()["platforms"]
        assert "niches" not in meta.json()
        # The key has to be present even though it is empty. When it was
        # omitted, the Search page read undefined and called .trim() on it.
        assert meta.json()["defaults"]["goal"] == ""
        # Same contract for the two optional fields, and this one is load-bearing
        # rather than cosmetic: Brief.query_text() folds a non-empty audience or
        # vibe into the embedded query, so an example value restored here would
        # silently prepend itself to every run's ranking. Example briefs belong in
        # the frontend's suggestion chips, not in the defaults the form loads.
        assert meta.json()["defaults"]["audience"] == ""
        assert meta.json()["defaults"]["vibe"] == ""
        response = client.post(
            "/api/v1/match-jobs",
            json={
                "brief": {
                    "goal": "high-energy strength training for busy millennials",
                    "platform": "TikTok",
                    "audience": "",
                    "vibe": "",
                },
                "params": {"top_k": 10, "top_n": 5},
            },
        )
        assert response.status_code == 202
        job = client.get(f"/api/v1/match-jobs/{response.json()['job_id']}")
        assert job.status_code == 200


def test_api_runs_export_compare_and_delete():
    repository = MemoryRepository()
    run_id = uuid4()
    repository.create(build_run_record(make_result(), run_id))
    app = create_app(
        repository=repository,
        job_manager=MemoryJobManager(),
        initialize_database=False,
        indexed_count=10,
    )
    with TestClient(app) as client:
        listed = client.get("/api/v1/runs")
        assert listed.status_code == 200
        assert listed.json()["items"][0]["run_id"] == str(run_id)
        detail = client.get(f"/api/v1/runs/{run_id}")
        assert detail.status_code == 200
        assert detail.json()["ranked"][0]["creator_key"] == "TikTok:@fit1"
        exported = client.get(f"/api/v1/runs/{run_id}/export.csv")
        assert exported.status_code == 200
        assert "creator_key" in exported.text
        compared = client.post(
            "/api/v1/comparisons",
            json={"run_id_a": str(run_id), "run_id_b": str(run_id)},
        )
        assert compared.status_code == 200
        assert len(compared.json()["shared"]) == 1
        assert client.delete(f"/api/v1/runs/{run_id}").status_code == 204
        assert client.get(f"/api/v1/runs/{run_id}").status_code == 404


def test_match_params_default_top_n_follows_top_k():
    from api.schemas.models import MatchParams

    assert MatchParams(top_k=1).top_n == 1


def test_api_normalizes_request_validation_errors():
    app = create_app(
        repository=MemoryRepository(),
        job_manager=MemoryJobManager(),
        initialize_database=False,
        indexed_count=10,
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/match-jobs",
            json={
                "brief": {"goal": "at-home strength training for gen z", "platform": "Any"},
                "params": {"top_k": 2, "top_n": 3},
            },
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "VALIDATION_ERROR"
        assert "top_n" in response.json()["detail"]["message"]


def test_api_rejects_thin_goal_and_reports_index_not_ready():
    """Free text means there is no taxonomy to violate, only length to check."""
    app = create_app(
        repository=MemoryRepository(),
        job_manager=MemoryJobManager(),
        initialize_database=False,
        indexed_count=0,
    )
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/match-jobs",
            json={"brief": {"goal": "yoga", "platform": "Any"}},
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "GOAL_TOO_SHORT"
        ready_response = client.post(
            "/api/v1/match-jobs",
            json={"brief": {"goal": "a thrifted-vintage clothing label for Gen Z", "platform": "Any"}},
        )
        assert ready_response.status_code == 503
        assert ready_response.json()["detail"]["code"] == "NOT_READY"


def test_demo_ip_rate_limit_blocks_repeated_matches(monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "demo")
    monkeypatch.setattr(config, "AUTH_REQUIRED", True)
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://demo")
    monkeypatch.setattr(config, "GEMINI_API_KEY", "demo-key")
    monkeypatch.setattr(config, "SUPABASE_URL", "https://demo.supabase.co")
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", "test-secret-that-is-at-least-32-bytes")
    monkeypatch.setattr(config, "SUPABASE_JWKS_URL", None)
    monkeypatch.setattr(config, "SUPABASE_ISSUER", None)
    monkeypatch.setattr(config, "MAX_MATCH_JOBS_PER_IP_PER_HOUR", 1)
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://demo.vercel.app")
    app = create_app(
        repository=MemoryRepository(),
        job_manager=MemoryJobManager(),
        initialize_database=False,
        indexed_count=10,
    )
    payload = {
        "brief": {"goal": "at-home strength training for Gen Z", "platform": "Any", "audience": "", "vibe": "warm"},
        "params": {"top_k": 3, "top_n": 1},
    }
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "aud": "authenticated",
            "role": "authenticated",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        "test-secret-that-is-at-least-32-bytes",
        algorithm="HS256",
    )
    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        assert client.post("/api/v1/match-jobs", json=payload, headers=headers).status_code == 202
        limited = client.post("/api/v1/match-jobs", json=payload, headers=headers)
        assert limited.status_code == 429
        assert limited.json()["detail"]["code"] == "MATCH_IP_RATE_LIMIT"
