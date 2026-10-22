import threading

import pytest

from api.jobs import manager as manager_module
from api.jobs.manager import JobQueueFullError, JobManager
from api.schemas.models import MatchParams
from src.corpora import Influencer
from src.models import Brief


class EmptyRepository:
    def create(self, record):
        return record


def test_job_queue_rejects_work_when_all_jobs_are_live():
    started = threading.Event()
    release = threading.Event()
    max_jobs = 3

    def matcher(job_id, brief, params, corpus):
        started.set()
        release.wait(timeout=2)
        return None

    manager = JobManager(EmptyRepository(), matcher=matcher, max_workers=1, max_jobs=max_jobs)
    brief = Brief(goal="at-home strength training for gen z", platform="Any")
    params = MatchParams(top_k=3, top_n=1)
    manager.submit(brief, params)
    assert started.wait(timeout=2)
    for _ in range(max_jobs - 1):
        manager.submit(brief, params)
    with pytest.raises(JobQueueFullError):
        manager.submit(brief, params)
    release.set()
    manager.shutdown()


def _creator() -> Influencer:
    return Influencer(
        id=1, handle="@a", platform="Instagram", city="Austin",
        followers=24_500, engagement=4.1, tags=["investing"], bio="Numbers.",
        name="A Person", similarity=0.82,
    )


class RecordingRepository:
    """Keeps the record the job built, so the test can read its warnings."""

    def __init__(self):
        self.record = None

    def create(self, record):
        self.record = record
        return record


def test_default_match_uses_the_relaxing_retriever_and_reports_what_it_dropped(monkeypatch):
    """The production path, end to end.

    Every other test in this file injects a fake matcher, so the code that
    actually retrieves and ranks -- the part that runs when a reader submits a
    brief -- was never executed by the suite. A stale name there shipped as a
    NameError that failed every match in the app while all the tests passed.

    This one runs the real `_default_match`, with only the two calls that
    reach outside the process stubbed: the retriever and the ranker.
    """
    seen = {}

    def fake_retrieve(brief, top_k, query_vec=None, corpus=None):
        seen["corpus"] = corpus
        seen["top_k"] = top_k
        return [_creator()], ["Audience age"]

    def fake_rank(brief, candidates, top_n, client=None, corpus=None):
        return [{
            "id": candidates[0].id,
            "fit": "strong",
            "source": "llm",
            "rationale": "On topic and on audience.",
            "grounding": [{"field": "tags", "quote": "investing"}],
            "fallback_reason": "",
        }]

    monkeypatch.setattr(manager_module, "retrieve_for_run", fake_retrieve)
    monkeypatch.setattr(manager_module, "rank_match", fake_rank)

    repository = RecordingRepository()
    manager = JobManager(repository, client_factory=lambda: object(), max_workers=1, max_jobs=2)
    job = manager.submit(
        Brief(goal="data-driven investing basics", platform="Any"),
        MatchParams(top_k=5, top_n=1),
    )
    for _ in range(100):
        state = manager.get(job.job_id)
        if state and state.status in ("succeeded", "failed"):
            break
        threading.Event().wait(timeout=0.05)
    manager.shutdown()

    state = manager.get(job.job_id)
    assert state.status == "succeeded", state.error
    # The corpus reaches the retriever, so the Companies panel searches
    # companies rather than creators.
    assert seen["corpus"].kind == "creator"
    assert seen["top_k"] == 5
    # The dropped filters reach the record, which is what turns them into the
    # FILTER_RELAXED warning the reader is shown.
    assert repository.record["result"]["ranked"][0]["id"] == 1
    assert [w["code"] for w in repository.record["warnings"]] == ["FILTER_RELAXED"]
    assert repository.record["warnings"][0]["details"]["relaxed"] == ["Audience age"]


def test_default_match_reports_no_warning_when_nothing_was_relaxed(monkeypatch):
    """A brief with no structured filters is untouched by the relaxation, and
    must not claim that something was dropped."""
    monkeypatch.setattr(
        manager_module, "retrieve_for_run",
        lambda brief, top_k, query_vec=None, corpus=None: ([_creator()], []),
    )
    monkeypatch.setattr(
        manager_module, "rank_match",
        lambda brief, candidates, top_n, client=None, corpus=None: [{
            "id": candidates[0].id, "fit": "strong", "source": "llm",
            "rationale": "On topic.", "grounding": [], "fallback_reason": "",
        }],
    )

    repository = RecordingRepository()
    manager = JobManager(repository, client_factory=lambda: object(), max_workers=1, max_jobs=2)
    job = manager.submit(
        Brief(goal="data-driven investing basics", platform="Any"),
        MatchParams(top_k=5, top_n=1),
    )
    for _ in range(100):
        state = manager.get(job.job_id)
        if state and state.status in ("succeeded", "failed"):
            break
        threading.Event().wait(timeout=0.05)
    manager.shutdown()

    assert manager.get(job.job_id).status == "succeeded"
    assert repository.record["warnings"] == []
