"""Tests for src.summaries and the summary half of api.serialization.

The creator numbers are the regression gate: this phase changes where they are
defined, not what they are. Every expected value below is written by hand from
the pre-existing behaviour, so a change in how a figure is computed fails here
rather than in someone's saved run.
"""

import pytest

from uuid import uuid4

from api.schemas.models import MatchParams, RunSummary
from api.services.compare_service import summarize_run
from api.serialization import (
    build_run_record,
    build_summary,
    candidate_key,
    prospect_key,
    prospect_to_snapshot,
)
from src.corpora import CREATORS, PROSPECTS, Influencer, Prospect
from src.models import Brief
from src.summaries import (
    CREATOR_SUMMARY,
    PROSPECT_SUMMARY,
    compact_count,
    joined,
    pct,
    summary_spec,
)


def creator_snapshot(id_, *, similarity=None, engagement_pct=0.0, followers=0):
    return {
        "id": id_, "handle": f"@c{id_}", "platform": "TikTok",
        "similarity": similarity, "engagement_pct": engagement_pct,
        "followers": followers,
    }


def prospect_snapshot(id_, *, similarity=None, headcount=0):
    return {"id": id_, "name": f"Co{id_}", "industry": "fintech",
            "headcount": headcount, "similarity": similarity}


def make_prospect(**overrides) -> Prospect:
    base = dict(
        id=1, name="Acme", industry="supply chain", headcount=240,
        city="Berlin", country="Germany", description="Freight tooling.",
        tags=["freight", "fleet"], website="https://acme.test",
        founded_year=2019, funding_stage="Series A",
        seniority_mix="mid-weighted", department_mix=["engineering", "sales"],
        tech_stack=["SAP"], buying_signals=["needs route optimisation"],
        growth_trend="rising", growth_rate=0.31, hiring_intensity=0.4,
        top_markets=["Germany"], similarity=0.8,
    )
    base.update(overrides)
    return Prospect(**base)


# --- the creator regression gate ----------------------------------------------

def test_creator_values_are_unchanged():
    """Hand-computed from the behaviour this replaced."""
    candidates = [
        creator_snapshot(1, similarity=0.8, engagement_pct=5.0, followers=1_000),
        creator_snapshot(2, similarity=0.6, engagement_pct=3.0, followers=3_000),
    ]
    ranked = [{"id": 1, "fit": "strong"}, {"id": 2, "fit": "weak"}]
    s = build_summary(candidates, ranked)
    assert s["n_results"] == 2
    assert s["n_strong"] == 1
    assert s["n_weak"] == 1
    assert s["avg_match_pct"] == 70.0
    assert s["avg_engagement_pct"] == 4.0
    assert s["median_followers"] == 2_000
    assert s["kind"] == "creator"


def test_creator_cells_match_the_previous_component():
    """Exactly the five cells RunSummary.tsx used to build, same labels, same
    formatting -- that component now renders what arrives here instead."""
    candidates = [
        creator_snapshot(1, similarity=0.8, engagement_pct=5.0, followers=1_000),
        creator_snapshot(2, similarity=0.6, engagement_pct=3.0, followers=3_000),
    ]
    ranked = [{"id": 1, "fit": "strong"}, {"id": 2, "fit": "weak"}]
    cells = build_summary(candidates, ranked)["cells"]
    assert [(c["label"], c["value"]) for c in cells] == [
        ("Quality", "1/2"),
        ("Avg similarity", "70.0%"),
        ("Avg engagement", "4.0%"),
        ("Median reach", "2K"),
        ("Needs review", "1"),
    ]
    assert cells[0]["primary"] is True
    assert all("primary" not in c for c in cells[1:])
    assert "explanation" in cells[1]
    assert all("explanation" not in c for c in (cells[0], cells[2], cells[3], cells[4]))


def test_stored_values_stay_numeric():
    """A cell can be a ratio; a stored value cannot. `RunListItem` sums
    `n_strong` and compare differences these keys, so a string here breaks both
    in ways a validation error would not catch."""
    candidates = [creator_snapshot(1, similarity=0.5, followers=100)]
    summary = build_summary(candidates, [{"id": 1, "fit": "strong"}])
    assert isinstance(summary["n_results"], int)
    assert isinstance(summary["n_strong"], int)
    assert isinstance(summary["n_weak"], int)
    assert isinstance(summary["median_followers"], int)
    assert isinstance(summary["avg_match_pct"], float)
    assert isinstance(summary["avg_engagement_pct"], float)


def test_creator_key_order_matches_the_replaced_tuple():
    """`summarize_run` decides whether a stored summary is reusable by key
    membership, and compare differences them pairwise."""
    assert CREATOR_SUMMARY.keys == (
        "n_results", "avg_match_pct", "n_strong", "n_weak",
        "avg_engagement_pct", "median_followers",
    )


# --- the joined-set rule ------------------------------------------------------

def test_a_dangling_ranked_entry_is_excluded_from_every_metric():
    """The rule `test_compare_logic.py` exists for, now shared by both corpora:
    counting an entry whose candidate is gone would let a run report "1/3 strong
    fits" out of two candidates."""
    candidates = [
        creator_snapshot(1, similarity=0.8, engagement_pct=4.0, followers=1_000),
        creator_snapshot(2, similarity=0.6, engagement_pct=6.0, followers=3_000),
    ]
    ranked = [
        {"id": 1, "fit": "strong"},
        {"id": 2, "fit": "weak"},
        {"id": 99, "fit": "strong"},
    ]
    s = build_summary(candidates, ranked)
    assert s["n_results"] == 2
    assert s["n_strong"] == 1
    # 6.0 would only appear if the dangling entry counted.
    assert s["avg_engagement_pct"] == 5.0


def test_joined_drops_dangling_and_preserves_ranked_order():
    pairs = joined(
        [{"id": 1}, {"id": 2}],
        [{"id": 2, "fit": "strong"}, {"id": 1, "fit": "weak"}, {"id": 3, "fit": "strong"}],
    )
    assert [candidate["id"] for _, candidate in pairs] == [2, 1]


def test_empty_run_reports_zeroes_rather_than_raising():
    s = build_summary([], [])
    assert s["n_results"] == 0
    assert s["avg_match_pct"] == 0.0
    assert s["median_followers"] == 0
    assert s["cells"][0]["value"] == "0/0"


# --- the prospect spec --------------------------------------------------------

def test_prospect_values_and_cells():
    candidates = [
        prospect_snapshot(1, similarity=0.9, headcount=240),
        prospect_snapshot(2, similarity=0.5, headcount=1_200),
    ]
    ranked = [{"id": 1, "fit": "strong"}, {"id": 2, "fit": "partial"}]
    s = build_summary(candidates, ranked, PROSPECT_SUMMARY)
    assert s["kind"] == "prospect"
    assert s["n_results"] == 2
    assert s["avg_match_pct"] == 70.0
    assert s["median_headcount"] == 720
    # Absent, not null. A company has no engagement rate and no follower count;
    # storing either key would invite a reader to treat a missing measurement as
    # a measured zero.
    assert "avg_engagement_pct" not in s
    assert "median_followers" not in s
    assert [(c["label"], c["value"]) for c in s["cells"]] == [
        ("Quality", "1/2"),
        ("Avg similarity", "70.0%"),
        ("Median headcount", "720"),
        ("Needs review", "0"),
    ]


def test_a_stored_prospect_summary_reads_back_as_none_not_zero():
    """The contract that matters across a round trip: the summary is persisted as
    JSONB and re-validated on every read, so an absent optional must come back
    as None -- and never as 0.0, which would render as a real measurement."""
    candidates = [prospect_snapshot(1, similarity=0.7, headcount=240)]
    stored = build_summary(candidates, [{"id": 1, "fit": "strong"}], PROSPECT_SUMMARY)
    reloaded = RunSummary(**stored)
    assert reloaded.avg_engagement_pct is None
    assert reloaded.median_followers is None
    assert reloaded.median_headcount == 240
    assert reloaded.kind == "prospect"
    assert len(reloaded.cells or []) == 4


def test_each_spec_has_one_primary_and_starts_with_quality():
    for spec in (CREATOR_SUMMARY, PROSPECT_SUMMARY):
        assert sum(1 for c in spec.cells if c.primary) == 1, spec.kind
        assert spec.cells[0].label == "Quality"
        assert spec.cells[0].primary


def test_prospect_has_one_fewer_cell_than_creator():
    """Four, not five -- and that is the consequence of *swapping* rather than
    adding. Creator's five cells are Quality, similarity, engagement, reach and
    review; dropping engagement and renaming reach to headcount leaves four.

    Asserted explicitly because "five cells for both" is an easy thing to
    believe and would mean inventing a fifth metric to fill the gap."""
    assert len(CREATOR_SUMMARY.cells) == 5
    assert len(PROSPECT_SUMMARY.cells) == 4
    prospect_labels = [c.label for c in PROSPECT_SUMMARY.cells]
    assert "Avg engagement" not in prospect_labels
    assert "Median reach" not in prospect_labels
    assert "Median headcount" in prospect_labels


def test_cell_labels_are_unique_within_a_spec():
    for spec in (CREATOR_SUMMARY, PROSPECT_SUMMARY):
        labels = [c.label for c in spec.cells]
        assert len(set(labels)) == len(labels), spec.kind


def test_every_cell_key_exists_in_the_stored_values():
    """A cell reading a key the spec never stores renders a blank or a zero, and
    neither looks wrong."""
    for spec in (CREATOR_SUMMARY, PROSPECT_SUMMARY):
        stored = set(spec.keys)
        for cell in spec.cells:
            assert cell.key in stored, f"{spec.kind}: cell {cell.label!r} reads {cell.key!r}, unstored"


def test_shared_cells_are_the_same_object_in_both_specs():
    """The similarity caveat is domain reasoning; if it were copied per spec the
     two could drift, and it is the one cell most likely to be misread."""
    creator = {c.label: c for c in CREATOR_SUMMARY.cells}
    prospect = {c.label: c for c in PROSPECT_SUMMARY.cells}
    assert creator["Avg similarity"] is prospect["Avg similarity"]
    assert creator["Quality"] is prospect["Quality"]


def test_summary_spec_rejects_an_unknown_corpus():
    with pytest.raises(KeyError):
        summary_spec("leads")


# --- snapshots ----------------------------------------------------------------

def test_prospect_snapshot_has_no_creator_fields():
    snap = prospect_to_snapshot(make_prospect())
    for field in ("handle", "platform", "followers", "engagement_pct",
                  "average_views", "verified", "posts_per_week"):
        assert field not in snap, f"a company must not carry {field}"
    assert snap["name"] == "Acme"
    assert snap["industry"] == "supply chain"
    assert snap["headcount"] == 240


def test_prospect_snapshot_keeps_the_display_only_signals():
    """growth_rate, hiring_intensity and top_markets are display-only per
    migration 009 -- stored on the run, never citable by a reason."""
    snap = prospect_to_snapshot(make_prospect())
    assert snap["growth_rate"] == 0.31
    assert snap["hiring_intensity"] == 0.4
    assert snap["top_markets"] == ["Germany"]


def test_prospect_key_separates_same_industry_companies():
    a = make_prospect(id=1, name="Acme")
    b = make_prospect(id=2, name="Beta")
    assert prospect_key(a) != prospect_key(b)
    assert prospect_key(a) == "supply chain:Acme"


def test_candidate_key_backfill_reads_whichever_corpus_is_present():
    """This runs on every displayed run, including the five stored before any
    prospect existed, so assuming a creator shape would key every company to
    "::"."""
    assert candidate_key({"platform": "TikTok", "handle": "@a"}) == "TikTok:@a"
    assert candidate_key({"industry": "fintech", "name": "Acme", "headcount": 10}) == "fintech:Acme"
    # A stored key wins over inference, so an old run's key is never rewritten.
    assert candidate_key({"creator_key": "TikTok:@a", "platform": "X", "handle": "@b"}) == "TikTok:@a"


# --- stored runs predating cells ----------------------------------------------

def test_a_stored_summary_without_cells_is_hydrated_on_read():
    """The five runs already in the database predate `cells`. They are complete
    on the numeric keys, so without hydration they would be the only runs in the
    table that cannot describe their own labels -- and the client fallback
    carrying those labels would be permanent rather than temporary."""
    old = {
        "n_results": 2, "avg_match_pct": 70.0, "n_strong": 1, "n_weak": 1,
        "avg_engagement_pct": 4.0, "median_followers": 2_000,
    }
    run = {"summary": old, "result": {"candidates": [], "ranked": []}}
    got = summarize_run(run)
    assert got["kind"] == "creator"
    assert [(c["label"], c["value"]) for c in got["cells"]] == [
        ("Quality", "1/2"),
        ("Avg similarity", "70.0%"),
        ("Avg engagement", "4.0%"),
        ("Median reach", "2K"),
        ("Needs review", "1"),
    ]
    # The stored keys are passed through untouched; hydration adds, never edits.
    assert {k: got[k] for k in old} == old


def test_hydration_reuses_stored_cells_rather_than_recomputing():
    """Cells already present are authoritative. Recomputing would be pure
    formatting, so the values would match -- but only until a label changes, at
    which point a stored run would silently re-label itself on read."""
    run = {
        "summary": {
            "n_results": 1, "avg_match_pct": 80.0, "n_strong": 1, "n_weak": 0,
            "avg_engagement_pct": 5.0, "median_followers": 1_000,
            "kind": "creator",
            "cells": [{"key": "n_results", "label": "Hand-edited",
                       "caption": "x", "value": "99"}],
        },
        "result": {"candidates": [], "ranked": []},
    }
    assert summarize_run(run)["cells"][0]["label"] == "Hand-edited"


def test_a_prospect_run_hydrates_headcount_and_no_creator_cells():
    run = {
        "summary": {"n_results": 1, "avg_match_pct": 70.0, "n_strong": 1,
                    "n_weak": 0, "median_headcount": 240},
        "result": {"candidates": [], "ranked": []},
    }
    cells = summarize_run(run, PROSPECTS)["cells"]
    labels = [c["label"] for c in cells]
    assert labels == ["Quality", "Avg similarity", "Median headcount", "Needs review"]
    assert [c["value"] for c in cells][2] == "240"


# --- run records, both corpora ------------------------------------------------

def _match_result(candidates, ranked):
    brief = Brief(goal="warehouse robotics", platform="any")
    return {
        "brief": brief,
        "params": MatchParams().model_dump(mode="json"),
        "candidates": candidates,
        "ranked": ranked,
    }


def _creator_result():
    influencer = Influencer(
        id=1, handle="@a", platform="TikTok, YouTube", city="Austin",
        followers=1_000, engagement=5.0, average_views=4_000, verified=True,
        posts_per_week=3, audience_age="25-34", bio="Home goods.",
        content_style="warm", similarity=0.8, tags=["home", "kitchen"],
    )
    return _match_result(
        [influencer],
        [{"id": 1, "fit": "strong", "rationale": "close", "grounding": []}],
    )


def test_a_creator_run_record_still_ships_its_own_fields():
    record = build_run_record(_creator_result(), uuid4(), CREATORS)
    candidate = record["result"]["candidates"][0]
    assert candidate["handle"] == "@a"
    assert candidate["followers"] == 1_000
    assert "evidence" in record["result"]["ranked"][0]
    assert record["summary"]["kind"] == "creator"
    assert len(record["summary"]["cells"]) == 5


def test_a_prospect_run_record_carries_no_creator_field():
    record = build_run_record(
        _match_result(
            [make_prospect()],
            [{"id": 1, "fit": "strong", "rationale": "text match",
              "grounding": [{"field": "tags", "quote": "freight"}]}],
        ),
        uuid4(), PROSPECTS,
    )
    candidate = record["result"]["candidates"][0]
    for field in ("handle", "platform", "followers", "engagement_pct"):
        assert field not in candidate, f"a stored company must not carry {field}"
    assert candidate["name"] == "Acme"
    assert candidate["creator_key"] == "supply chain:Acme"


def test_a_prospect_ranked_row_omits_evidence_entirely():
    """Not an empty list. `evidence` is per-field verification against
    `MatchSignals`, which is the creator's signal set; [] would read as
    "checked, found nothing" when nothing was ever checked."""
    record = build_run_record(
        _match_result([make_prospect()], [{"id": 1, "fit": "strong", "grounding": []}]),
        uuid4(), PROSPECTS,
    )
    assert "evidence" not in record["result"]["ranked"][0]


def test_a_prospect_run_summary_omits_the_creator_keys():
    record = build_run_record(
        _match_result([make_prospect(headcount=240)], [{"id": 1, "fit": "strong", "grounding": []}]),
        uuid4(), PROSPECTS,
    )
    summary = record["summary"]
    assert summary["kind"] == "prospect"
    assert summary["median_headcount"] == 240
    assert "avg_engagement_pct" not in summary
    assert "median_followers" not in summary


# --- formatting ---------------------------------------------------------------

@pytest.mark.parametrize(
    "value, expected",
    [(0, "0"), (999, "999"), (1_000, "1K"), (1_200, "1K"), (1_450, "1K"),
     (15_000, "15K"), (1_000_000, "1.0M"), (2_400_000, "2.4M")],
)
def test_compact_count(value, expected):
    assert compact_count(value) == expected


def test_compact_count_ignores_none():
    """An absent metric renders 0 rather than "None"."""
    assert compact_count(None) == "0"


@pytest.mark.parametrize("value, expected", [(0, "0.0%"), (5, "5.0%"), (12.34, "12.3%")])
def test_pct(value, expected):
    assert pct(value) == expected