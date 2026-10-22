from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from api.serialization import build_run_record
from api.services.compare_service import compare_runs, summarize_run
from src.corpora import Influencer
from src.models import Brief


def make_influencer(id_: int, tags: list[str] | None = None) -> Influencer:
    return Influencer(
        id=id_, handle=f"@c{id_}", name=f"Creator {id_}",
        platform="Instagram", city="Austin",
        country="USA", language="English", followers=50_000, engagement=5.5,
        similarity=0.8, tags=tags or [], bio="",
    )


def make_run(fits, tags, similarities=None):
    assert len(fits) <= len(tags)
    brief = Brief(goal="at-home strength training for beginners", platform="Any")
    similarities = similarities or [0.8] * len(tags)
    result = {
        "brief": brief,
        "params": {"top_k": 10, "top_n": max(1, len(fits))},
        "candidates": [
            replace(make_influencer(i, tags[i]), similarity=similarities[i])
            for i in range(len(tags))
        ],
        "ranked": [
            {"id": i, "fit": fit, "rationale": "", "source": "llm"}
            for i, fit in enumerate(fits)
        ],
    }
    record = build_run_record(result, uuid4())
    now = datetime.now(timezone.utc)
    record["created_at"] = now
    record["updated_at"] = now
    return record


def test_summarize_run_stats():
    run = make_run(
        fits=["strong", "partial", "weak"],
        tags=[["gym"], ["skincare"], ["fps"]],
        similarities=[0.9, 0.5, 0.7],
    )
    summary = summarize_run(run)
    assert summary["n_results"] == 3
    assert summary["avg_match_pct"] == 70.0
    assert summary["n_strong"] == 1 and summary["n_weak"] == 1
    assert summary["avg_engagement_pct"] == 5.5
    assert summary["median_followers"] == 50_000


def test_summarize_run_ignores_stored_summary_from_old_schema():
    """Runs stored before avg_match_pct existed must be recomputed."""
    run = make_run(fits=["strong"], tags=[["gym"]], similarities=[0.4])
    run["summary"] = {"n_results": 1, "n_ranked_on_niche": 1}
    assert summarize_run(run)["avg_match_pct"] == 40.0


def test_summary_counts_and_denominator_use_the_same_result_set():
    """A ranked entry with no snapshot must not inflate the fit tallies.

    The two implementations disagreed here: n_results counted the joined set
    while n_strong/n_weak counted every ranked entry, so a run with a dangling
    entry could report more strong fits than results.
    """
    run = make_run(fits=["strong", "weak"], tags=[["gym"], ["skincare"]], similarities=[0.9, 0.3])
    run["result"]["ranked"].append({"id": str(uuid4()), "fit": "strong", "creator_key": "tiktok:ghost"})
    run.pop("summary")
    summary = summarize_run(run)
    assert summary["n_results"] == 2
    assert summary["n_strong"] == 1
    assert summary["n_weak"] == 1


def test_shared_only_counts_ranked_results():
    run_a = make_run(["strong"], [["gym"], ["mindfulness"]])
    run_b = make_run(["strong"], [["mindfulness"], ["gym"]])
    comparison = compare_runs(run_a, run_b)
    assert comparison["shared"] == [
        {"id": 0, "creator_key": "Instagram:@c0", "label": "@c0"}
    ]


def test_legacy_creator_keys_compare_with_normalized_keys():
    legacy = make_run(["strong"], [["gym"]])
    for creator in legacy["result"]["candidates"]:
        creator["creator_key"] = creator["handle"]
    for entry in legacy["result"]["ranked"]:
        entry["creator_key"] = entry["id"]
    current = make_run(["strong"], [["gym"]])
    comparison = compare_runs(legacy, current)
    assert comparison["shared"][0]["creator_key"] == "Instagram:@c0"


def test_compare_runs_shape():
    run_a = make_run(["strong", "partial"], [["gym"], ["mindfulness"]])
    run_b = make_run(["partial", "strong"], [["mindfulness"], ["gym"]])
    comparison = compare_runs(run_a, run_b)
    assert len(comparison["shared"]) == 2
    assert comparison["summary_a"]["n_strong"] == 1
    assert comparison["summary_b"]["n_strong"] == 1
