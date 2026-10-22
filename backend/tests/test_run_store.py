import csv
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from api.serialization import build_run_record, run_detail
from api.services.csv_export import build_csv
from src.corpora import Influencer
from src.models import Brief


def make_influencer(id_: int, **overrides) -> Influencer:
    defaults = dict(
        id=id_, handle=f"@c{id_}", name=f"Creator {id_}",
        platform="TikTok", city="Austin",
        country="USA", language="English", followers=50_000, engagement=5.5,
        average_views=20_000, average_likes=2_500, average_comments=150,
        verified=False, posts_per_week=5, account_age_years=3,
        content_style="Educational", audience_age="18-24",
        audience_gender="60% Female", audience_country="USA",
        brand_collaborations=["Nike"], tags=["gym", "HIIT"],
        bio="Lifting daily.", similarity=0.8123,
    )
    defaults.update(overrides)
    return Influencer(**defaults)


def make_run(goal="at-home strength training for gen z", platform="Any", n=3) -> dict:
    brief = Brief(goal=goal, platform=platform, audience="", vibe="warm")
    candidates = [make_influencer(i) for i in range(n)]
    ranked = [
        {"id": i, "fit": "strong", "rationale": f"r{i}", "source": "llm"}
        for i in range(n)
    ]
    return {
        "brief": brief,
        "params": {"top_k": 10, "top_n": n},
        "candidates": candidates,
        "ranked": ranked,
    }


def stored_run(n=3):
    record = build_run_record(make_run(n=n), uuid4())
    now = datetime.now(timezone.utc)
    record["created_at"] = now
    record["updated_at"] = now
    return record


def test_run_record_keeps_snapshot_without_embeddings():
    record = stored_run()
    assert record["result"]["candidates"][0]["creator_key"] == "TikTok:@c0"
    assert "embedding" not in record["result"]["candidates"][0]
    detail = run_detail(record)
    assert detail.ranked[0].evidence
    assert detail.summary.n_results == 3


def test_legacy_run_detail_normalizes_creator_keys():
    record = stored_run(n=1)
    record["result"]["candidates"][0]["creator_key"] = "@c0"
    record["result"]["ranked"][0]["creator_key"] = "@c0"
    detail = run_detail(record)
    assert detail.candidates[0].creator_key == "TikTok:@c0"
    assert detail.ranked[0].creator_key == "TikTok:@c0"


def test_even_shortlist_summary_rounds_median_followers():
    run = make_run(n=2)
    run["candidates"][0].followers = 10_001
    run["candidates"][1].followers = 20_000
    record = build_run_record(run, uuid4())
    assert record["summary"]["median_followers"] == 15_000


def test_build_csv_contents_and_formula_protection():
    run = make_run(n=2)
    record = build_run_record(run, uuid4())
    record["created_at"] = datetime.now(timezone.utc)
    record["updated_at"] = record["created_at"]
    record["result"]["candidates"][0]["handle"] = "=danger"
    csv_text = build_csv(record)
    rows = list(csv.DictReader(csv_text.splitlines()))
    assert rows[0]["handle"] == "'=danger"
    assert rows[1]["handle"] == "@c1"
    assert rows[0]["tags"] == "gym|HIIT"
    assert rows[0]["brand_collaborations"] == "Nike"
    assert rows[0]["semantic_similarity"] == "0.8123"
    assert rows[0]["evidence"]


def test_csv_of_a_run_stored_before_the_taxonomy_removed():
    """Runs captured while creators still had a niche must keep exporting.

    The API no longer models `niche`, so such a snapshot is re-validated with
    the field dropped. Extra keys in the stored JSON are ignored rather than
    raising, which is what keeps an old run readable.
    """
    run = make_run(n=1)
    record = build_run_record(run, uuid4())
    record["result"]["candidates"][0]["niche"] = "Fitness"
    record["result"]["candidates"][0]["secondary_niches"] = ["Yoga"]
    record["created_at"] = datetime.now(timezone.utc)
    record["updated_at"] = record["created_at"]

    rows = list(csv.DictReader(build_csv(record).splitlines()))
    assert rows[0]["handle"] == "@c0"
    assert rows[0]["tags"] == "gym|HIIT"


def test_csv_exports_the_new_signals():
    run = make_run(n=1)
    candidate = run["candidates"][0]
    candidate.reach_ratio = 0.421
    candidate.sponsored_ratio = 0.12
    candidate.growth_trend = "rising"
    candidate.audience_top_countries = ["USA", "Canada"]
    record = build_run_record(run, uuid4())
    record["created_at"] = datetime.now(timezone.utc)
    record["updated_at"] = record["created_at"]

    row = next(csv.DictReader(build_csv(record).splitlines()))
    assert row["reach_ratio"] == "0.421"
    assert row["sponsored_ratio"] == "0.120"
    assert row["growth_trend"] == "rising"
    assert row["audience_top_countries"] == "USA|Canada"


def test_csv_exports_grounded_claims():
    run = make_run(n=1)
    run["ranked"][0]["grounding"] = [{"field": "tags", "quote": "gym"}]
    record = build_run_record(run, uuid4())
    record["created_at"] = datetime.now(timezone.utc)
    record["updated_at"] = record["created_at"]

    rows = list(csv.DictReader(build_csv(record).splitlines()))
    assert rows[0]["grounding"] == "tags=gym"


@pytest.mark.parametrize("run_id", [uuid4(), uuid4()])
def test_run_records_have_unique_identifiers(run_id):
    record = build_run_record(make_run(n=1), run_id)
    assert record["id"] == run_id


def test_fallback_reason_survives_a_store_and_reread():
    """The reason has to outlive the process that produced it.

    It was write-only: `fallback_reason` lived on the in-memory entry and was
    dropped when the run was persisted, so a run opened the next morning always
    showed the generic "ranking was unavailable" message and could not say the
    quota had simply been spent.
    """
    from src.ranking import QUOTA_REASON_TAG

    reason = f"{QUOTA_REASON_TAG}: generate_content(gemini-2.5-flash-lite) exhausted its daily free-tier quota"
    run = make_run(n=1)
    run["ranked"][0].update(source="fallback", fallback_reason=reason)

    record = build_run_record(run, uuid4())
    now = datetime.now(timezone.utc)
    record["created_at"] = now
    record["updated_at"] = now

    detail = run_detail(record)
    assert detail.ranked[0].fallback_reason == reason
    assert detail.warnings[0].code == "RANKING_FALLBACK"
    assert "quota" in detail.warnings[0].message.lower()


def test_csv_includes_the_fallback_reason():
    from src.ranking import QUOTA_REASON_TAG

    run = make_run(n=1)
    run["ranked"][0].update(
        source="fallback",
        fallback_reason=f"{QUOTA_REASON_TAG}: exhausted",
    )
    record = build_run_record(run, uuid4())
    record["created_at"] = datetime.now(timezone.utc)
    record["updated_at"] = record["created_at"]

    row = next(csv.DictReader(build_csv(record).splitlines()))
    assert row["fallback_reason"].startswith(QUOTA_REASON_TAG)


def test_quota_and_outage_warnings_say_different_things():
    """The wording is the fix, not decoration.

    "Ranking was unavailable" reads as an outage, and the reasonable response
    to an outage is to retry immediately -- which cannot help when a daily cap
    is spent. The quota message has to name the cap and the reset.
    """
    from src.ranking import QUOTA_REASON_TAG

    ranked_quota = [{"source": "fallback",
                     "fallback_reason": f"{QUOTA_REASON_TAG}: exhausted its daily free-tier quota"}]
    ranked_outage = [{"source": "fallback", "fallback_reason": "APIError: 500"}]

    from api.serialization import build_warnings

    quota = build_warnings(ranked_quota)[0]
    outage = build_warnings(ranked_outage)[0]

    assert quota["code"] == outage["code"] == "RANKING_FALLBACK"
    assert "quota" in quota["message"].lower()
    assert "midnight Pacific" in quota["message"]
    assert quota["message"] != outage["message"]
    assert "unavailable" in outage["message"]
    # The technical reason is one click away either way.
    assert quota["details"]["reason"].startswith(QUOTA_REASON_TAG)
    assert outage["details"]["reason"] == "APIError: 500"


def test_a_quota_fallback_is_still_an_error_severity():
    """Results really are unranked, so the alert styling is correct.

    Quota exhaustion is routine at 20 calls/day, but downgrading the severity
    would calm the styling over a genuinely degraded result.
    """
    from src.ranking import QUOTA_REASON_TAG
    from api.serialization import build_warnings

    warning = build_warnings(
        [{"source": "fallback", "fallback_reason": f"{QUOTA_REASON_TAG}: spent"}]
    )[0]
    assert warning["severity"] == "error"


def test_row_mapping_matches_the_column_order_the_repository_selects():
    """Pin the positional mapping in `_record_from_row`.

    The run-detail tests above pass a dict, so they never touch it: the mapping
    is the one place where removing a column from the SELECT silently shifts
    every field after it, returning a wrong-but-plausible run. Dropping the
    `pipeline` column is exactly that case.
    """
    from api.repositories.postgres_run_repository import _record_from_row

    columns = [
        "id", "owner_id", "kind", "brief", "params", "result", "warnings",
        "summary", "created_at", "updated_at",
    ]
    sentinels = {
        "id": "ID", "owner_id": "OWNER", "kind": "creator", "brief": {"goal": "g"},
        "params": {"top_k": 10}, "result": {"candidates": [], "ranked": []},
        "warnings": [{"code": "w"}], "summary": {"n_results": 1},
        "created_at": "CREATED", "updated_at": "UPDATED",
    }
    row = tuple(sentinels[name] for name in columns)

    mapped = _record_from_row(row)

    assert set(mapped) == set(columns), "every selected column must be mapped"
    for name in columns:
        assert mapped[name] == sentinels[name], f"{name} read from the wrong index"


def test_run_record_no_longer_carries_provenance():
    """`pipeline` was written to every run and never displayed by any client."""
    record = stored_run()

    assert "pipeline" not in record
    assert "indexed_creator_count" not in record
