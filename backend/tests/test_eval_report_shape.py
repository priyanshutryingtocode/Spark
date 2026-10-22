"""Tests for the report's headline block and the hard-case breakdown.

`summary` carries every field for debugging. `headline` carries only what a
reader should quote, and the two must not drift apart.
"""

import json
from pathlib import Path

import pytest

from evaluate import DEFAULT_CASES
from src.corpora import CREATORS

BACKEND = Path(__file__).resolve().parents[1]

HEADLINE_KEYS = {
    "corpus_kind",
    "dataset_size",
    "case_count",
    "mean_retrieval_tag_precision_at_k",
    # The comparable pair. These three are what make a reranking claim
    # attributable: the retriever's own ordering and the ranker's, both at n,
    # plus the difference between them.
    "mean_retrieval_tag_precision_at_n",
    "mean_reranked_tag_precision_at_n",
    "mean_retrieval_fit_precision_at_n",
    "mean_reranked_fit_precision_at_n",
    "mean_retrieval_campaign_precision_at_n",
    "mean_reranked_campaign_precision_at_n",
    "mean_ranked_tag_precision_at_n",
    "mean_ranking_gain_at_n",
    "mean_recall_of_ceiling_at_k",
    "mean_recall_of_ceiling_at_n",
    "mean_topic_overlap_at_k",
    "mean_strong_fits_per_case",
    "ranking_fallback_rate",
    # Says whether the ranked number is attributable to the reranker at all.
    "ranking_measured",
    # Why the ranking metrics are absent, when they are. Without it a
    # retrieval-only report reads like one where ranking found nothing.
    "ranking_skipped",
}


@pytest.fixture(scope="module")
def written_report(tmp_path_factory):
    """Run the evaluator once against the live schema with the model stubbed."""
    import evaluate as ev

    out = tmp_path_factory.mktemp("reports") / "report.json"
    # Restored in the finally below. These are plain attribute assignments on the
    # evaluate module, so without that they outlive the fixture: _run_case stayed
    # replaced by the stub for the rest of the session, and any later test that
    # called the real _run_case silently exercised the stub instead.
    patched = {
        "_run_case": _stub_case,
        "get_client": lambda: object(),
        "embed_query": lambda text: [0.0] * 768,
        "PostgresRunRepository": _StubRepository,
        "vector_store": _StubVectorStore,
    }
    originals = {name: getattr(ev, name) for name in patched}
    for name, value in patched.items():
        setattr(ev, name, value)
    # --rate-limit-per-min is raised so the sequential pacing does not spend a
    # minute of the suite sleeping; it is a report-shape test, not a latency
    # measurement, and the values are stubbed anyway.
    monkey_argv = [
        "evaluate.py", "--sequential", "--rate-limit-per-min", "1000",
        "--output", str(out),
        # The cache is disabled so this fixture can never append to the real
        # .embed-cache directory the way a real evaluation run would.
        "--no-query-cache",
    ]
    import sys
    original_argv = sys.argv
    sys.argv = monkey_argv
    try:
        ev.main()
    finally:
        sys.argv = original_argv
        for name, value in originals.items():
            setattr(ev, name, value)
    return json.loads(out.read_text(encoding="utf-8"))


def _stub_case(client, case, top_k, top_n, query_cache=None, corpus=CREATORS, ranks=True):
    return {
        "id": case["id"],
        "expected_tags": sorted(case["expected_tags"]),
        "corpus_kind": corpus.kind,
        "platform": case.get("platform", "Any"),
        "hard": bool(case.get("hard")),
        "retrieved_count": top_k,
        "retrieval_tag_precision_at_k": 0.5,
        "retrieval_tag_hit_at_k": True,
        "topic_overlap_at_k": 0.1,
        "ranked_tag_precision_at_n": 0.4,
        # Consistent with the pair above: the reranker took 0.25 -> 0.4, so the
        # headline mean must come out as exactly that difference.
        "retrieval_tag_precision_at_n": 0.25,
        "reranked_tag_precision_at_n": 0.3,
        "retrieval_fit_precision_at_n": 0.4,
        "reranked_fit_precision_at_n": 0.45,
        "retrieval_campaign_precision_at_n": 0.1,
        "reranked_campaign_precision_at_n": 0.15,
        "ranking_gain_at_n": 0.15,
        "pool_size": 12,
        "ceiling_precision_at_k": 1.0,
        "recall_of_ceiling_at_k": 0.5,
        "ceiling_precision_at_n": 1.0,
        "recall_of_ceiling_at_n": 0.5,
        "ranking_fallback": False,
        "fallback_count": 0,
        "filled_count": 0,
        "strong_fit_count": 3,
        "retrieval_latency_ms": 1.0,
        "embed_latency_ms": 1.0,
        "search_latency_ms": 1.0,
        "ranking_latency_ms": 1.0,
    }


class _StubRepository:
    def ensure_schema(self):
        return None


class _StubVectorStore:
    DEFAULT_TABLE = "influencers"

    @staticmethod
    def init_schema(conn):
        return None

    @staticmethod
    def count_records(conn, table=None):
        return 500

    @staticmethod
    def search(conn, query_embedding=None, corpus=None, facet=None, top_k=1):
        return []

    @staticmethod
    def get_connection():
        class _Ctx:
            def __enter__(self_inner):
                return object()

            def __exit__(self_inner, *a):
                return False

        return _Ctx()


# ------------------------------------------------------------- headline

def test_headline_has_exactly_the_intended_keys(written_report):
    assert set(written_report["headline"]) == HEADLINE_KEYS


def test_headline_values_come_from_the_summary(written_report):
    """The trimmed view must not drift from the full one."""
    h, s = written_report["headline"], written_report["summary"]
    # corpus_kind, dataset_size and case_count are labels rather than computed
    # metrics, so they are not expected to appear in the summary.
    for key in HEADLINE_KEYS - {"corpus_kind", "dataset_size", "case_count"}:
        assert h[key] == s[key], f"{key} disagrees between headline and summary"
    assert h["dataset_size"] == written_report["dataset_size"] == s["case_count"] * 0 + written_report["dataset_size"]
    assert h["case_count"] == s["case_count"] == len(written_report["cases"])


def test_headline_omits_operational_noise(written_report):
    """Latency and slot counters belong in the JSON, not in a quoted figure."""
    for noisy in ("mean_ranking_latency_ms", "total_filled_slots",
                  "mean_ceiling_precision_at_k", "retrieval_tag_hit_rate_at_k"):
        assert noisy not in written_report["headline"]
        assert noisy in written_report["summary"]


def test_summary_keeps_every_field(written_report):
    assert len(written_report["summary"]) > len(HEADLINE_KEYS)


# ------------------------------------------------------------ hard cases

def test_hard_cases_are_listed_per_case_with_no_mean(written_report):
    """A mean over three briefs is three anecdotes in a trenchcoat."""
    hard = written_report["summary"]["hard_cases"]
    assert set(hard) == {"case_count", "note", "cases"}
    assert hard["case_count"] == len(hard["cases"]) == 3
    assert not any(key.startswith("mean_") for key in hard)
    for row in hard["cases"]:
        assert set(row) == {"id", "retrieval_tag_precision_at_k", "topic_overlap_at_k"}
    assert "too few for a mean" in hard["note"]


def test_hard_case_ids_match_the_flagged_briefs(written_report):
    hard = written_report["summary"]["hard_cases"]
    flagged = {c["id"] for c in written_report["cases"] if c["hard"]}
    assert {row["id"] for row in hard["cases"]} == flagged
    assert len(flagged) < len(written_report["cases"]), "a subset must actually be a subset"


# --------------------------------------------------------- case set

def test_golden_set_is_ten_balanced_cases():
    """Ten cases, one per vertical, spread over as many platforms as possible.

    The set was 15 with Instagram a third of it and Fitness a fifth, so the mean
    was weighted toward two topics. Ten cases at the per-minute ranking limit
    also fits one window, which is what makes the run take about a minute.
    """
    cases = json.loads(DEFAULT_CASES["creator"].read_text(encoding="utf-8"))
    assert len(cases) == 10

    verticals = {c["expected_tags"][0] for c in cases}
    assert len(verticals) == len(cases), "each case should cover a distinct topic"

    assert len({c["platform"] for c in cases}) >= 7
    assert sum(1 for c in cases if c["hard"]) == 3


def test_every_case_has_the_fields_the_runner_reads():
    cases = json.loads(DEFAULT_CASES["creator"].read_text(encoding="utf-8"))
    for case in cases:
        assert case["id"] and case["goal"]
        assert case["expected_tags"], f"{case['id']} has no expected_tags"
        assert isinstance(case["hard"], bool)
        assert "audience" in case and "vibe" in case


def _run_evaluator(tmp_path, extra_args):
    """Run the evaluator with the model stubbed, and return the report."""
    import evaluate as ev

    out = tmp_path / "report.json"
    patched = {
        "_run_case": _stub_case,
        "get_client": lambda: object(),
        "embed_query": lambda text: [0.0] * 768,
        "PostgresRunRepository": _StubRepository,
        "vector_store": _StubVectorStore,
    }
    originals = {name: getattr(ev, name) for name in patched}
    for name, value in patched.items():
        setattr(ev, name, value)
    import sys
    original_argv = sys.argv
    sys.argv = [
        "evaluate.py", "--sequential", "--rate-limit-per-min", "1000",
        "--no-query-cache", "--output", str(out), *extra_args,
    ]
    try:
        ev.main()
    finally:
        sys.argv = original_argv
        for name, value in originals.items():
            setattr(ev, name, value)
    return json.loads(out.read_text(encoding="utf-8"))


def test_a_no_ranking_run_omits_the_ranking_metrics_and_says_why(tmp_path):
    """The trap this flag has to avoid.

    `ranking_measured` is computed as "no case fell back", and a skipped run
    falls back on nothing -- so it would report `True` for a run that measured
    no ranking at all. The metrics are omitted instead, and the report says they
    were skipped.
    """
    report = _run_evaluator(tmp_path, ["--no-ranking"])

    headline = report["headline"]
    for key in ("mean_ranked_tag_precision_at_n", "mean_ranking_gain_at_n",
                "ranking_measured", "ranking_fallback_rate"):
        assert key not in headline, f"{key} is present on a run that measured no ranking"
    assert headline["ranking_skipped"] == "--no-ranking"
    assert report["ranking_skipped"] == "--no-ranking"
    # The retrieval metrics are the point of the free pass, so they are present.
    assert "mean_retrieval_tag_precision_at_n" in headline


def test_a_ranked_run_reports_no_skip(tmp_path):
    report = _run_evaluator(tmp_path, [])
    assert report["headline"]["ranking_skipped"] is None
    assert "ranking_measured" in report["headline"]
