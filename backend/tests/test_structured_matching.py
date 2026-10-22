"""Structured filters and the rerank: what they do, and what they must not do.

Two rules are being tested here, and both were arrived at by measurement rather
than by design:

A filter excludes, a preference ranks. Getting that backwards either empties the
shortlist (filtering on an estimate) or leaves the wrong records in it (reranking
on something that could have been excluded).

A filter the reader cannot see is a filter they cannot trust, so every record
carries the reasons it was selected.
"""

from __future__ import annotations

import pytest

from api.schemas.models import BriefPayload
from src.corpora import CREATORS, PROSPECTS
from src.models import Brief
from src.retrieval import (
    _is_requested, attach_filter_reasons, filter_order, rerank_candidates,
    resolve_filters,
)
from src.scoring import (
    age_band_score, budget_score, equals, floor_score, gender_score, in_list,
    overlap_score, range_score, role_score,
)


# --- the scorers -------------------------------------------------------------

def test_an_exact_age_band_scores_full_and_a_neighbour_scores_half():
    assert age_band_score("18-24", ["18-24"]) == 1.0
    assert age_band_score("25-34", ["18-24"]) == 0.5
    assert age_band_score("45-54", ["18-24"]) == 0.0


def test_age_scoring_ignores_a_brief_that_asked_for_nothing():
    assert age_band_score("18-24", []) == 0.0


def test_a_gender_preference_scores_the_lean_and_not_the_gender():
    assert gender_score("62% Female", "female") == pytest.approx(0.62)
    assert gender_score("50% Female / 50% Male", "female") == 0.5
    # "Any" imposes nothing, so it scores nothing rather than scoring everyone.
    assert gender_score("62% Female", "any") == 0.0


def test_a_reach_floor_is_a_floor_and_not_a_target():
    assert floor_score(0.4, 0.2) == 1.0
    assert floor_score(0.1, 0.2) == 0.5
    assert floor_score(0.0, 0.2) == 0.0


def test_a_band_score_falls_off_outside_the_band_without_excluding():
    assert range_score(500, (200, 2000)) == 1.0
    assert 0.0 < range_score(100, (200, 2000)) < 1.0
    assert range_score(5000, (200, 2000)) == 0.0


def test_a_budget_band_is_read_against_the_funding_stage():
    assert budget_score("Series A", "10k-100k") == 1.0
    assert budget_score("Series A", "1m-10m") == 0.5
    assert budget_score("bootstrapped", "1m-10m") == 0.0


def test_a_role_matches_a_department_by_its_words():
    assert role_score(["operations", "sales"], ["operations manager"]) == 1.0
    assert role_score(["engineering"], ["operations manager"]) == 0.0


def test_a_term_overlap_is_a_share_not_a_switch():
    assert overlap_score(["needs routing", "wants fleet"], ["needs routing"]) == 1.0
    assert overlap_score(["needs routing"], ["wants fleet"]) == 0.0


def test_a_list_membership_is_a_match():
    assert in_list("USA", ["USA", "UK"]) == 1.0
    assert in_list("France", ["USA", "UK"]) == 0.0
    assert in_list(["a", "b"], ["b"]) == 1.0


def test_an_equality_ignores_case_and_space():
    assert equals(" logistics ", "Logistics") == 1.0
    assert equals("logistics", "fintech") == 0.0


# --- what counts as a request ------------------------------------------------

@pytest.mark.parametrize("value", [None, "", [], (), 0, False, "any", "ANY"])
def test_a_value_that_asks_for_nothing_is_not_a_request(value):
    """A zero floor and an "any" preference look like values but impose nothing.
    Counting them put weight in the denominator no candidate could satisfy, which
    lowered every score and shifted the comparison for no reason."""
    assert _is_requested(value) is False


@pytest.mark.parametrize("value", ["female", ["USA"], (51, 2000), 0.2, 5])
def test_a_value_that_asks_for_something_is_a_request(value):
    assert _is_requested(value) is True


def test_a_brief_with_no_structured_fields_resolves_to_no_filters():
    brief = Brief(goal="something", platform="Any")
    assert resolve_filters(brief, CREATORS) == {}
    assert resolve_filters(brief, PROSPECTS) == {}


def test_a_brief_names_the_filters_its_corpus_declares():
    brief = Brief(
        goal="something", platform="Any",
        audience_age=["18-24"], audience_countries=["USA"], languages=["en"],
        target_industries=["logistics"], target_countries=["Germany"],
    )
    assert set(resolve_filters(brief, CREATORS)) == {
        "s.audience_age", "s.audience_country", "language",
    }
    assert set(resolve_filters(brief, PROSPECTS)) == {"industry", "country"}


def test_a_size_band_is_resolved_as_a_band():
    brief = Brief(goal="something", platform="Any", target_size=(51, 2000))
    assert resolve_filters(brief, PROSPECTS)["headcount"] == (51, 2000)


def test_the_filters_are_ordered_so_the_most_selective_is_dropped_first():
    brief = Brief(
        goal="something", platform="Any",
        audience_age=["18-24"], audience_countries=["USA"], languages=["en"],
    )
    order = filter_order(resolve_filters(brief, CREATORS), CREATORS)
    # The order is the corpus's declared drop order, not a guess made here: the
    # most selective filter is the one that was doing the most work, and it
    # should be the last to go.
    assert order == ["s.audience_country", "s.audience_age", "language"]


# --- the rerank --------------------------------------------------------------

class _Record:
    def __init__(self, **kwargs):
        self.similarity = kwargs.pop("similarity", 0.8)
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_the_rerank_reorders_by_the_match():
    brief = Brief(goal="x", platform="Any", audience_gender="female")
    wrong = _Record(handles="a", audience_gender="45% Male", similarity=0.85)
    right = _Record(handles="b", audience_gender="70% Female", similarity=0.80)
    ordered = rerank_candidates(brief, [wrong, right], CREATORS)
    assert [r.handles for r in ordered] == ["b", "a"]


def test_the_rerank_records_why_it_moved_a_record():
    brief = Brief(goal="x", platform="Any", audience_gender="female")
    record = _Record(audience_gender="70% Female")
    rerank_candidates(brief, [record], CREATORS)
    assert record.match_reasons == ["Audience gender 70%"]


def test_the_rerank_keeps_the_filter_reasons_it_did_not_produce():
    """The filter hits are attached first. Overwriting them with the rerank's
    reasons dropped the explanation of the filter that actually selected the
    record, which is the part the reader asked about."""
    brief = Brief(goal="x", platform="Any", audience_gender="female")
    record = _Record(audience_gender="70% Female", match_reasons=["Audience age 18-24"])
    rerank_candidates(brief, [record], CREATORS)
    assert record.match_reasons == ["Audience age 18-24", "Audience gender 70%"]


def test_the_rerank_does_nothing_when_the_brief_asked_for_nothing():
    brief = Brief(goal="x", platform="Any")
    records = [_Record(audience_gender="70% Female", similarity=0.8),
               _Record(audience_gender="45% Male", similarity=0.85)]
    ordered = rerank_candidates(brief, records, CREATORS)
    assert [r.similarity for r in ordered] == [0.85, 0.8]


def test_a_record_without_a_similarity_does_not_crash_the_rerank():
    """A record that never went through the embedding path has no similarity."""
    brief = Brief(goal="x", platform="Any", audience_gender="female")
    record = _Record(audience_gender="70% Female")
    record.similarity = None
    assert rerank_candidates(brief, [record], CREATORS)


# --- the filter reasons ------------------------------------------------------

def test_a_filter_hit_names_the_value_that_matched():
    brief = Brief(
        goal="x", platform="Any",
        target_industries=["logistics"], target_countries=["Germany"],
        target_size=(51, 2000),
    )
    record = _Record(industry="logistics", country="Germany", headcount=187)
    attach_filter_reasons(brief, [record], PROSPECTS)
    assert "Industry logistics" in record.match_reasons
    assert "Country Germany" in record.match_reasons
    assert "Size 187" in record.match_reasons


def test_a_filter_that_did_not_match_is_not_reported():
    brief = Brief(goal="x", platform="Any", target_industries=["logistics"])
    record = _Record(industry="fintech", country="Germany", headcount=10)
    attach_filter_reasons(brief, [record], PROSPECTS)
    assert not any(r.startswith("Industry") for r in record.match_reasons)


# --- the payload round trip --------------------------------------------------

def test_the_structured_fields_survive_the_payload_round_trip():
    payload = BriefPayload(
        goal="x" * 20, platform="Any",
        audience_age=["18-24"], audience_gender="female",
        audience_countries=["USA"], min_reach_ratio=0.2,
        target_industries=["logistics"], target_size=(51, 2000),
        target_countries=["Germany"], budget_band="10k-100k",
        buyer_roles=["operations manager"],
    )
    brief = payload.to_domain()
    assert brief.audience_age == ["18-24"]
    assert brief.audience_gender == "female"
    assert brief.min_reach_ratio == 0.2
    assert brief.target_size == (51, 2000)
    assert brief.budget_band == "10k-100k"
    assert brief.buyer_roles == ["operations manager"]


def test_a_brief_with_only_free_text_still_works():
    brief = BriefPayload(goal="x" * 20, platform="Any").to_domain()
    assert brief.audience_age == []
    assert brief.target_size is None
    assert brief.query_text().startswith("x")


# --- verticals ---------------------------------------------------------------

def test_a_named_vertical_expands_to_its_industries():
    """A brief names a vertical -- "logistics" -- and the corpus has three
    logistics industries. Without the expansion the filter matches one of them
    and the brief looks like it found nothing."""
    brief = Brief(goal="x", platform="Any", target_industries=["logistics"])
    resolved = resolve_filters(brief, PROSPECTS)
    assert set(resolved["industry"]) == {"logistics", "supply chain", "freight tech"}


def test_naming_one_industry_selects_its_vertical():
    """A seller who says "freight tech" means the logistics market."""
    brief = Brief(goal="x", platform="Any", target_industries=["freight tech"])
    resolved = resolve_filters(brief, PROSPECTS)
    assert set(resolved["industry"]) == {"logistics", "supply chain", "freight tech"}


def test_an_unknown_industry_is_kept_and_matches_nothing():
    """Not expanded to everything. An unrecognised name should fail to match
    rather than quietly widen the search."""
    brief = Brief(goal="x", platform="Any", target_industries=["made up sector"])
    assert resolve_filters(brief, PROSPECTS)["industry"] == ["made up sector"]


def test_the_creator_filters_are_not_vertically_expanded():
    """Creators have no vertical structure, and the field that is expanded is
    the corpus's own."""
    brief = Brief(goal="x", platform="Any", audience_countries=["USA"])
    assert set(resolve_filters(brief, CREATORS)) == {"s.audience_country"}


# --- the relaxation order ----------------------------------------------------

def test_country_is_relaxed_last():
    """Country is the constraint a seller least wants dropped, so it survives
    longest; the size band is the most adjustable and goes first."""
    brief = Brief(
        goal="x", platform="Any",
        target_industries=["logistics"], target_countries=["USA"], target_size=(51, 2000),
    )
    order = filter_order(resolve_filters(brief, PROSPECTS), PROSPECTS)
    assert order == ["headcount", "industry", "country"]


# --- the ranking prompt ------------------------------------------------------

def test_the_prompt_states_the_briefs_hard_requirements():
    """The rubric asks the model to judge size against what the seller asked
    for. Without the structured brief in the prompt, that question is
    unanswerable when the size was set in a control rather than in the goal."""
    from src.rubrics import PROSPECT_RUBRIC
    brief = Brief(
        goal="fleet routing software", platform="Any",
        target_industries=["logistics"], target_size=(51, 2000), target_countries=["USA"],
    )
    prompt = PROSPECT_RUBRIC.render(brief, [], 3, 2, 80)
    assert "companies with 51 to 2000 employees" in prompt
    assert "industries logistics" in prompt
    assert "based in USA" in prompt


def test_the_prompt_states_the_briefs_preferences_separately():
    """A filter already removed the records that failed it; a preference only
    reordered the ones that came back. They are not the same kind of claim and
    the model should not treat them as one."""
    from src.rubrics import PROSPECT_RUBRIC
    brief = Brief(
        goal="fleet routing software", platform="Any",
        target_industries=["logistics"], budget_band="10k-100k", buyer_roles=["ops manager"],
    )
    prompt = PROSPECT_RUBRIC.render(brief, [], 3, 2, 80)
    assert "- Must match: industries logistics" in prompt
    assert "- Prefer: a budget around 10k-100k" in prompt


def test_the_creator_prompt_states_its_requirements_and_preferences():
    from src.rubrics import CREATOR_RUBRIC
    brief = Brief(
        goal="clean beauty", platform="Any",
        audience_age=["18-24"], audience_countries=["USA"],
        audience_gender="female", min_reach_ratio=0.2,
    )
    prompt = CREATOR_RUBRIC.render(brief, [], 3, 2, 80)
    assert "- Must match: audience age 18-24; audience in USA" in prompt
    assert "- Prefer: audience leaning female" in prompt


def test_a_brief_with_nothing_structured_adds_no_requirement_lines():
    from src.rubrics import CREATOR_RUBRIC, PROSPECT_RUBRIC
    brief = Brief(goal="something", platform="Any")
    for rubric in (CREATOR_RUBRIC, PROSPECT_RUBRIC):
        prompt = rubric.render(brief, [], 3, 2, 80)
        assert "Must match:" not in prompt
        assert "Prefer:" not in prompt


# --- the metric and the filter must agree ------------------------------------

def test_the_icp_metric_expands_verticals_the_way_the_filter_does():
    """The filter expands "logistics" to its three industries; the metric must
    too, or a supply-chain company passes the filter and is then scored wrong,
    and the report understates the corpus it measured."""
    from evaluate import icp_match

    class _Company:
        industry = "supply chain"
        headcount = 500
        country = "USA"

    icp = {"industries": ["logistics"], "size": [51, 2000], "countries": ["USA"]}
    assert icp_match(_Company(), icp, PROSPECTS) is True
    # Without the corpus it compares exactly, which is the older behaviour.
    assert icp_match(_Company(), icp) is False


def test_a_company_outside_the_vertical_is_not_a_match():
    from evaluate import icp_match

    class _Company:
        industry = "bakery"
        headcount = 500
        country = "USA"

    icp = {"industries": ["logistics"], "size": [51, 2000], "countries": ["USA"]}
    assert icp_match(_Company(), icp, PROSPECTS) is False
