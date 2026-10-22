"""Tests for the two-corpus split: kind storage, filtering, and the guards that
stop one panel's data reaching the other.

The interesting failures here are all silent ones. A kind filter that is ignored
returns a plausible list of the wrong runs; a compare that crosses corpora
returns an empty overlap that reads as "these briefs found nothing in common".
So the tests assert on what must NOT appear as much as on what must.
"""

from __future__ import annotations

import io
import csv
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from api.repositories.postgres_run_repository import _record_from_row
from api.schemas.models import MatchJobRequest, RunDetail
from api.serialization import run_detail, run_list_item
from api.services.compare_service import compare_runs
from api.services.csv_export import build_csv, columns_for
from src.corpora import CREATORS, DEFAULT_KIND, KINDS, PROSPECTS
from src.summaries import summary_spec


# --- the wire contract agrees with the corpus registry ------------------------

def test_the_wire_kind_literal_covers_every_registered_corpus():
    """`CorpusKind` is hand-written in the schema and `KINDS` is built from the
    dataclasses. Nothing makes them agree, so a third corpus would be
    unreachable over the API with a green test suite."""
    from api.schemas.models import CorpusKind

    import typing
    literal = set(typing.get_args(CorpusKind))
    assert literal == set(KINDS), "schema CorpusKind and src.corpora.KINDS disagree"
    assert DEFAULT_KIND in literal


def test_every_corpus_has_a_summary_spec():
    """Two corpora, one spec table. A corpus with no spec would fall through
    `summary_spec` and raise at read time on a run that was already written."""
    for kind in KINDS:
        assert summary_spec(kind).kind == kind


def test_default_kind_is_the_creator_corpus():
    assert DEFAULT_KIND == "creator"


# --- records carry a kind ----------------------------------------------------

def _record(kind: str = DEFAULT_KIND) -> dict:
    return {
        "id": uuid.uuid4(),
        "owner_id": None,
        "kind": kind,
        "brief": {"goal": "a goal long enough to pass validation", "platform": "Any",
                  "audience": "", "vibe": ""},
        "params": {"top_k": 5, "top_n": 3},
        "result": {"candidates": [], "ranked": []},
        "warnings": [],
        "summary": {"n_results": 0, "avg_match_pct": 0.0, "n_strong": 0, "n_weak": 0},
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def test_run_list_item_reports_the_stored_kind():
    assert run_list_item(_record("prospect")).kind == "prospect"


def test_a_record_without_a_kind_reads_as_creator():
    """Every run stored before migration 010 has no kind. It is a creator run,
    and the column default means the database never returns NULL -- but a record
    assembled in memory, or read from a replica taken mid-migration, can still
    lack the key."""
    record = _record()
    del record["kind"]
    assert run_list_item(record).kind == "creator"
    assert run_detail(record).kind == "creator"


def test_the_positional_row_mapper_puts_kind_third():
    """`get` selects `id, owner_id, kind, brief, ...`. Inserting the column at
    any other position returns a wrong-but-plausible run: every field after the
    shift arrives under the previous field's name, and nothing raises."""
    columns = ["id", "owner_id", "kind", "brief", "params", "result", "warnings",
               "summary", "created_at", "updated_at"]
    values = {
        "id": "ID", "owner_id": "OWNER", "kind": "prospect", "brief": {"goal": "g"},
        "params": {"top_k": 10}, "result": {"candidates": [], "ranked": []},
        "warnings": [{"code": "w"}], "summary": {"n_results": 1},
        "created_at": "CREATED", "updated_at": "UPDATED",
    }
    mapped = _record_from_row(tuple(values[name] for name in columns))
    for name in columns:
        assert mapped[name] == values[name], name


# --- the candidates union is not ambiguous -----------------------------------

def _company_run(kind: str = "prospect") -> dict:
    record = _record(kind)
    record["result"]["candidates"] = [{
        "id": 1, "creator_key": "logistics:Acme", "name": "Acme",
        "industry": "logistics", "headcount": 240, "city": "Berlin", "country": "DE",
        "description": "Freight tooling.", "website": "", "founded_year": 2019,
        "funding_stage": "Series A", "tags": ["freight"], "similarity": 0.7,
        "seniority_mix": "mid", "department_mix": ["eng"], "tech_stack": ["SAP"],
        "buying_signals": ["needs routing"], "growth_trend": "rising",
        "growth_rate": 0.31, "hiring_intensity": 0.4, "top_markets": ["DE"],
    }]
    return record


def test_a_company_validates_as_the_prospect_arm():
    """Left to Pydantic's union order, a company is tried against
    CreatorSnapshot first. It fails there only because `handle` is required --
    so the discrimination is real, but it is load-bearing on required fields
    rather than declared, and this pins it."""
    detail = run_detail(_company_run())
    candidate = detail.candidates[0]
    assert detail.kind == "prospect"
    assert candidate.name == "Acme"
    assert not hasattr(candidate, "handle")


def test_a_company_run_has_no_creator_only_field_on_the_wire():
    payload = run_detail(_company_run()).model_dump()
    candidate = payload["candidates"][0]
    for field in ("handle", "platform", "followers", "engagement_pct", "reach_ratio"):
        assert field not in candidate, field


def test_evidence_is_optional_on_a_ranked_row():
    """A company run has nothing to verify field-by-field, so the key is absent.
    Were `evidence` required, Pydantic would coerce the absence to [] -- which
    reads as "every claim was checked and none held"."""
    ranked = RunDetail.model_fields["ranked"].annotation.__args__[0]
    field = ranked.model_fields["evidence"]
    assert field.is_required() is False
    assert field.default is None


def test_a_stored_company_ranked_row_omits_evidence():
    """Checked on the storage path, not on a bare `model_dump`.

    `RankedEntry` alone still serialises `evidence: None`, because omitting it is
    done by the snapshot builders passing `exclude_none` -- the field has to stay
    optional for the creator arm. So the guarantee worth pinning is the one a run
    actually relies on: what `build_run_record` writes to JSONB.
    """
    from api.serialization import build_run_record
    from src.corpora import Prospect
    from src.models import Brief

    # A stored snapshot, not the model: `creator_key` and `similarity` are
    # computed by the builder, so constructing a Prospect from a snapshot's dict
    # would pass fields the dataclass does not have.
    company = dict(_company_run()["result"]["candidates"][0])
    company["id"] = 7
    company.pop("creator_key", None)
    company.pop("similarity", None)
    company.setdefault("seniority_mix", "mid")
    company.setdefault("department_mix", [])
    company.setdefault("tech_stack", [])
    company.setdefault("buying_signals", [])
    company.setdefault("growth_trend", "rising")
    company.setdefault("growth_rate", 0.3)
    company.setdefault("hiring_intensity", 0.4)
    company.setdefault("top_markets", [])
    record = build_run_record(
        {
            "brief": Brief(goal="warehouse robotics", platform="Any"),
            "params": {"top_k": 1, "top_n": 1},
            "candidates": [Prospect(**company)],
            "ranked": [{"id": 7, "fit": "strong", "rationale": "fit"}],
        },
        uuid.uuid4(),
        PROSPECTS,
    )
    assert "evidence" not in record["result"]["ranked"][0]


# --- comparison refuses to cross corpora -------------------------------------

def _ranked_run(kind: str, run_id: uuid.UUID, candidate_id: int, key: str) -> dict:
    record = _record(kind)
    record["id"] = run_id
    record["result"]["candidates"] = [{
        "id": candidate_id, "creator_key": key,
        "handle": "@a", "platform": "TikTok", "city": "Austin",
        "followers": 10, "engagement_pct": 1.0,
    }] if kind == "creator" else [{
        "id": candidate_id, "creator_key": key, "name": "Acme", "industry": "logistics",
        "headcount": 10, "city": "Berlin", "country": "DE", "description": "",
        "website": "", "founded_year": 2020, "funding_stage": "", "tags": [],
        "similarity": 0.5,
    }]
    record["result"]["ranked"] = [{"id": candidate_id, "fit": "strong"}]
    return record


def test_two_company_runs_compare_and_label_with_the_company_name():
    left = _ranked_run("prospect", uuid.uuid4(), 1, "logistics:Acme")
    right = _ranked_run("prospect", uuid.uuid4(), 1, "logistics:Acme")
    result = compare_runs(left, right, PROSPECTS)
    assert result["shared"] == [
        {"id": 1, "creator_key": "logistics:Acme", "label": "Acme"},
    ]
    assert result["summary_a"]["kind"] == "prospect"


def test_two_creator_runs_still_label_with_the_handle():
    left = _ranked_run("creator", uuid.uuid4(), 1, "TikTok:@a")
    right = _ranked_run("creator", uuid.uuid4(), 1, "TikTok:@a")
    assert compare_runs(left, right, CREATORS)["shared"][0]["label"] == "@a"


def test_comparing_across_corpora_would_report_an_empty_overlap():
    """Not an error from `compare_runs` -- the HTTP layer refuses first. Pinned
    so the reason it refuses stays visible: joining a creator to a company on
    candidate key finds nothing, and that empty result is indistinguishable from
    two briefs that genuinely share nothing."""
    left = _ranked_run("creator", uuid.uuid4(), 1, "TikTok:@a")
    right = _ranked_run("prospect", uuid.uuid4(), 2, "logistics:Acme")
    assert compare_runs(left, right, CREATORS)["shared"] == []


# --- CSV per corpus -----------------------------------------------------------

def test_the_creator_header_is_unchanged():
    """This file is a deliverable people paste into a spreadsheet. Adding a
    column is fine; reordering one shifts every column after it for anyone
    reusing an old template."""
    assert columns_for("creator") == [
        "rank", "creator_key", "handle", "name", "platform", "city", "country",
        "followers", "engagement_pct", "average_views", "average_likes",
        "average_comments", "verified", "posts_per_week", "account_age_years",
        "content_style", "language", "audience_age", "audience_gender",
        "audience_country", "semantic_similarity", "reach_ratio", "sponsored_ratio",
        "growth_trend", "audience_top_countries", "fit", "source", "rationale",
        "evidence", "grounding", "fallback_reason", "tags", "brand_collaborations",
    ]


def test_the_company_header_carries_the_fields_a_salesperson_filters_on():
    columns = columns_for("prospect")
    for field in ("name", "industry", "headcount", "founded_year", "funding_stage",
                  "tech_stack", "buying_signals", "website"):
        assert field in columns, field


def test_the_company_header_omits_evidence_entirely():
    """Not blank. An empty evidence column reads as "every claim was checked and
    none held", which is a statement about the ranking. A company run never
    checked anything."""
    assert "evidence" not in columns_for("prospect")
    assert "evidence" in columns_for("creator")


def test_the_company_header_omits_creator_only_columns():
    for field in ("handle", "platform", "followers", "engagement_pct",
                  "reach_ratio", "sponsored_ratio", "brand_collaborations"):
        assert field not in columns_for("prospect"), field


def test_build_csv_reads_the_kind_off_the_record():
    record = _company_run()
    assert record["kind"] == "prospect"
    header = build_csv(record).splitlines()[0].split(",")
    assert header == columns_for("prospect")


def test_a_negative_growth_rate_survives_as_a_number():
    """`_safe_cell` prefixes anything starting with `-` as formula injection. A
    formatting template turns a legitimate -0.064 into the string "-0.064", which
    the guard then ships as the text `'-0.064` -- a shrinking company's growth
    rate corrupted by the protection meant for a hostile one."""
    record = _company_run()
    record["result"]["candidates"][0]["growth_rate"] = -0.064
    record["result"]["ranked"] = [{"id": 1, "fit": "weak"}]
    row = next(csv.DictReader(io.StringIO(build_csv(record))))
    assert row["growth_rate"] == "-0.064"
    assert float(row["growth_rate"]) == pytest.approx(-0.064)
    assert not row["growth_rate"].startswith("'")


def test_a_formula_in_company_free_text_is_still_neutralised():
    """The guard exists because a company description is free text. Dropping it
    for the company corpus would be the one place an injection could land."""
    record = _company_run()
    record["result"]["candidates"][0]["description"] = "=cmd|' /C calc'!A0"
    record["result"]["ranked"] = [{"id": 1, "fit": "weak"}]
    row = next(csv.DictReader(io.StringIO(build_csv(record))))
    assert row["description"].startswith("'=")


# --- the request -------------------------------------------------------------

def test_a_match_request_defaults_to_the_creator_panel():
    request = MatchJobRequest(brief={"goal": "x"})
    assert request.kind == "creator"


def test_an_unknown_kind_is_rejected_by_the_schema():
    with pytest.raises(Exception):
        MatchJobRequest(brief={"goal": "x"}, kind="leads")


# --- the guards at the HTTP boundary -----------------------------------------
#
# The service-level tests above cover the rules. These cover that the rules are
# actually reachable: a guard the router never calls is not a guard.

class _MemoryRepository:
    """Honours `kind`, which an in-memory stand-in that ignored it would not."""

    def __init__(self, records):
        self.records = {record["id"]: record for record in records}

    def ensure_schema(self):
        return None

    def create(self, record, owner_id=None):
        self.records[record["id"]] = record
        return record

    def list(self, limit, cursor=None, owner_id=None, kind=None):
        found = list(self.records.values())
        if kind is not None:
            found = [r for r in found if r.get("kind", DEFAULT_KIND) == kind]
        return found[:limit], None

    def get(self, run_id, owner_id=None):
        return self.records.get(run_id)

    def delete(self, run_id, owner_id=None):
        return self.records.pop(run_id, None) is not None


@contextmanager
def _client(records, counts):
    """A test client with the lifespan actually run.

    `create_app` applies its injected index counts inside `lifespan`, and a bare
    `TestClient(app)` never runs it -- so a client built without `with` reports an
    index of zero no matter what it was given, and a test asserting on a count
    fails against a correct app.
    """
    from fastapi.testclient import TestClient

    from api.main import create_app

    # job_manager left as None: the lifespan builds a real one and shuts it down
    # on exit, and a bare object() has no shutdown for it to call.
    app = create_app(
        repository=_MemoryRepository(records),
        initialize_database=False,
        indexed_counts=counts,
    )
    with TestClient(app) as client:
        yield client


def test_the_runs_list_is_filtered_by_kind():
    creator_run = _record("creator")
    prospect_run = _record("prospect")
    with _client([creator_run, prospect_run], {"creator": 2000, "prospect": 500}) as client:
        creators = client.get("/api/v1/runs?kind=creator").json()["items"]
        companies = client.get("/api/v1/runs?kind=prospect").json()["items"]

    assert [item["run_id"] for item in creators] == [str(creator_run["id"])]
    assert [item["run_id"] for item in companies] == [str(prospect_run["id"])]
    assert {item["kind"] for item in creators} == {"creator"}


def test_meta_reports_each_corporus_own_index_and_facets():
    with _client([], {"creator": 2000, "prospect": 500}) as client:
        creator_meta = client.get("/api/v1/meta?kind=creator").json()
        company_meta = client.get("/api/v1/meta?kind=prospect").json()

    assert creator_meta["index"]["count"] == 2000
    assert len(creator_meta["platforms"]) > 1
    # No platform facet: offering one would offer a filter the server ignores.
    assert company_meta["platforms"] == []
    assert company_meta["index"]["count"] == 500


def test_comparing_across_panels_is_refused_with_a_named_code():
    left, right = _record("creator"), _record("prospect")
    with _client([left, right], {"creator": 1, "prospect": 1}) as client:
        response = client.post(
            "/api/v1/comparisons",
            json={"run_id_a": str(left["id"]), "run_id_b": str(right["id"])},
        )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "CROSS_CORPUS_COMPARE"
    # Both corpora named, so the message tells the reader what to change rather
    # than only that something was wrong.
    message = response.json()["detail"]["message"]
    assert "creator" in message and "prospect" in message


def test_an_unknown_kind_is_rejected_before_any_query_runs():
    with _client([], {"creator": 1, "prospect": 1}) as client:
        # 422 from the Literal, not a 500 from a table that does not exist.
        assert client.get("/api/v1/runs?kind=leads").status_code == 422
        assert client.get("/api/v1/meta?kind=leads").status_code == 422


# --- regressions -------------------------------------------------------------
# Each of these is a bug that shipped once and is now pinned. The comments say
# what broke, because a test named after the fix stops being informative once the
# fix is old.

def test_meta_status_describes_the_requested_corpus():
    """`status` was read from `db_ready`, which only ever counts creators, so the
    Companies panel showed "ready" beside "0 companies indexed", enabled Search,
    and the POST was then refused by the very gate the pill claimed had passed."""
    with _client([], {"creator": 2000, "prospect": 0}) as client:
        creator = client.get("/api/v1/meta?kind=creator").json()["index"]
        company = client.get("/api/v1/meta?kind=prospect").json()["index"]

    assert (creator["status"], creator["count"]) == ("ready", 2000)
    assert (company["status"], company["count"]) == ("unavailable", 0)
    # The frontend disables the button on `status`, so the two must agree.
    assert (company["status"] == "ready") == (company["count"] > 0)


def test_comparing_two_runs_survives_a_dangling_ranked_entry():
    """A ranked entry whose snapshot is gone made `_ranked_key` synthesise a key
    with no candidate behind it; the intersection then held that key and looking
    it up raised KeyError, which the error handler turned into a 500. The summary,
    the CSV and the run store all already skipped these."""
    left = _ranked_run("creator", uuid.uuid4(), 1, "TikTok:@a")
    right = _ranked_run("creator", uuid.uuid4(), 2, "TikTok:@b")
    # Run `right` ranks id 1, which it has no snapshot for.
    right["result"]["ranked"] = [{"id": 1, "creator_key": "TikTok:@a", "fit": "strong"}]
    right["result"]["candidates"] = []

    assert compare_runs(left, right, CREATORS)["shared"] == []


def test_comparing_keeps_the_legacy_id_only_creator_key_working():
    """Regression guard for the rewrite: a stored entry whose `creator_key` is
    just its id must still match on the normalised key, which is why the lookup
    goes through the candidate rather than trusting the entry."""
    left = _ranked_run("creator", uuid.uuid4(), 1, "TikTok:@a")
    right = _ranked_run("creator", uuid.uuid4(), 1, "TikTok:@a")
    for run in (left, right):
        for entry in run["result"]["ranked"]:
            entry["creator_key"] = entry["id"]

    shared = compare_runs(left, right, CREATORS)["shared"]
    assert [item["creator_key"] for item in shared] == ["TikTok:@a"]


def test_the_csv_creator_key_reader_falls_back_to_the_handle():
    """Merging the two reader dicts let the prospect one shadow the creator one,
    so a creator with no stored `creator_key` exported its name instead. The
    import-time guards could not see it: they checked a column had *a* reader,
    never that it had the right one."""
    from api.services.csv_export import _READERS

    assert _READERS["creator"]["creator_key"]({"handle": "@a"}, {}, 1) == "@a"
    assert _READERS["prospect"]["creator_key"]({"name": "Acme"}, {}, 1) == "Acme"


def test_an_unknown_kind_cannot_silently_export_a_creator_sheet():
    """The CSV used to fall back to the creator column order for any unknown
    kind, which is the exact failure `src.corpora.get_corpus` refuses to allow."""
    with pytest.raises(KeyError):
        columns_for("leads")


def test_build_run_record_stamps_its_own_corpus():
    """It was left to the caller to add `kind`, so any caller passing a corpus
    and forgetting that persisted a companies run labelled `creator` -- invisible
    to the Companies panel and unserialisable on read."""
    from api.serialization import build_run_record
    from src.corpora import Prospect
    from src.models import Brief

    company = Prospect(
        id=1, name="Acme", industry="logistics", headcount=10, city="Berlin",
        country="DE", description="", website="", founded_year=2020,
        funding_stage="", tags=[], similarity=0.5,
    )
    record = build_run_record(
        {
            "brief": Brief(goal="warehouse robotics" * 3, platform="Any"),
            "params": {"top_k": 1, "top_n": 1},
            "candidates": [company],
            "ranked": [{"id": 1, "fit": "strong"}],
        },
        uuid.uuid4(),
        PROSPECTS,
    )
    assert record["kind"] == "prospect"


def test_the_corpus_of_a_record_is_decided_in_one_place():
    """Four readers used to ask separately and three omitted the summary
    fallback, so a record with an empty `kind` and a prospect summary was a
    creator run to the API and a company to the CSV."""
    from src.corpora import kind_for_record

    assert kind_for_record({"kind": "", "summary": {"kind": "prospect"}}) == "prospect"
    assert kind_for_record({"summary": {}}) == "creator"
    assert kind_for_record({"kind": "prospect"}) == "prospect"
    with pytest.raises(KeyError):
        kind_for_record({"kind": "leads"})


def test_the_csv_uses_the_same_corpus_rule_as_the_api():
    """`build_csv` had its own fallback chain, so it could disagree with
    `run_detail` about the same record."""
    from api.services.csv_export import kind_for_run

    record = _record("prospect")
    record["kind"] = ""          # empty column, as a row written before 010
    record["summary"]["kind"] = "prospect"
    record["result"] = {"candidates": [], "ranked": []}
    assert kind_for_run(record) == "prospect"
    assert run_detail(record).kind == "prospect"
