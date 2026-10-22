"""Tests for src.ranking: response cleaning, fallbacks, fit capping.

The Gemini call is stubbed via monkeypatching
src.ranking.generate_content_throttled, so these tests are fully offline.
"""

import json

import pytest
from google.genai import errors as genai_errors

from src import config, ranking
from src.corpora import Influencer
from src.models import Brief


@pytest.fixture(autouse=True)
def _clear_ranking_cache():
    ranking._clear_rank_cache()
    yield
    ranking._clear_rank_cache()


class _FakeResponse:
    def __init__(self, payload):
        object.__setattr__(self, "_payload", json.dumps(payload))

    @property
    def text(self) -> str:
        return self._payload


def make_influencer(id_: int, tags=None, **overrides) -> Influencer:
    defaults = dict(
        handle=f"@c{id_}",
        platform="Instagram",
        city="Austin",
        followers=10_000,
        engagement=5.0,
        tags=tags or ["gym", "running"],
        bio="Training tips.",
        content_style="Tutorials",
        audience_age="25-34",
        audience_gender="60% Female",
        audience_country="USA",
        brand_collaborations=["Nike"],
    )
    defaults.update(overrides)
    return Influencer(id=id_, **defaults)


def install_stub(monkeypatch, payload=None, exc=None):
    """Replace the LLM call with a canned response or exception."""
    def fake_generate(client, model, contents, gen_config=None):
        if exc is not None:
            raise exc
        return _FakeResponse(payload)

    monkeypatch.setattr(ranking, "generate_content_throttled", fake_generate)


BRIEF = Brief(goal="high-energy strength training for beginners", platform="TikTok")


def ok_grounding() -> list[dict]:
    """A citation that passes verification, for tests not about grounding."""
    return [{"field": "tags", "quote": "gym"}]


# ---------------------------------------------------------------- happy path

def test_valid_response_cleaned(monkeypatch):
    install_stub(monkeypatch, {"ranked": [
        {"id": 1, "fit": "strong", "rationale": "r1", "grounding": ok_grounding()},
        {"id": 2, "fit": "weak", "rationale": "r2", "grounding": ok_grounding()},
    ]})
    candidates = [make_influencer(1), make_influencer(2)]
    ranked = ranking.rank_candidates(object(), BRIEF, candidates, top_n=2)
    assert [e["id"] for e in ranked] == [1, 2]
    assert all(e["source"] == "llm" for e in ranked)
    assert ranked[0]["fit"] == "strong"
    assert ranked[1]["fit"] == "weak"


def test_gen_config_pins_temperature_and_schema():
    cfg = ranking._gen_config()
    assert cfg.temperature == 0.0
    assert cfg.response_mime_type == "application/json"
    assert cfg.response_schema == ranking.RANKING_SCHEMA
    if getattr(cfg, "thinking_config", None) is not None:
        assert cfg.thinking_config.thinking_budget == 0


# ----------------------------------------------------------------- fallbacks

def test_unparseable_json_falls_back(monkeypatch):
    def broken(client, model, contents, gen_config=None):
        resp = _FakeResponse({"ranked": []})
        object.__setattr__(resp, "_payload", "{not json")
        return resp

    monkeypatch.setattr(ranking, "generate_content_throttled", broken)
    candidates = [make_influencer(1)]
    ranked = ranking.rank_candidates(object(), BRIEF, candidates, top_n=1)
    assert all(e["source"] == "fallback" for e in ranked)


def test_api_error_falls_back(monkeypatch):
    install_stub(monkeypatch, exc=genai_errors.APIError(500, {"message": "boom"}))
    candidates = [make_influencer(1)]
    ranked = ranking.rank_candidates(object(), BRIEF, candidates, top_n=1)
    assert len(ranked) == 1
    assert ranked[0]["source"] == "fallback"
    assert ranked[0]["id"] == 1  # filled from retrieval order


def test_ranked_not_a_list_falls_back(monkeypatch):
    install_stub(monkeypatch, {"ranked": "invalid"})
    candidates = [make_influencer(1)]
    ranked = ranking.rank_candidates(object(), BRIEF, candidates, top_n=1)
    assert all(e["source"] == "fallback" for e in ranked)


def test_no_valid_ids_falls_back(monkeypatch):
    install_stub(monkeypatch, {"ranked": [{"id": 99, "fit": "strong", "rationale": "x", "grounding": ok_grounding()}]})
    candidates = [make_influencer(1)]
    ranked = ranking.rank_candidates(object(), BRIEF, candidates, top_n=1)
    assert all(e["source"] == "fallback" for e in ranked)


# ------------------------------------------------------------ entry cleaning

def test_non_dict_entries_skipped_without_crash(monkeypatch):
    install_stub(monkeypatch, {"ranked": ["garbage", 42, None,
                                           {"id": 2, "fit": "partial", "rationale": "ok", "grounding": ok_grounding()}]})
    candidates = [make_influencer(i) for i in (1, 2, 3)]
    ranked = ranking.rank_candidates(object(), BRIEF, candidates, top_n=3)
    assert len(ranked) == 3
    assert ranked[0]["id"] == 2 and ranked[0]["source"] == "llm"
    assert {e["source"] for e in ranked[1:]} == {"filled"}


def test_non_int_id_dropped_not_crash(monkeypatch):
    """A list-valued id would previously raise TypeError on set membership."""
    install_stub(monkeypatch, {"ranked": [
        {"id": [1], "fit": "strong", "rationale": "unhashable"},
        {"id": "1", "fit": "strong", "rationale": "string id"},
        {"id": True, "fit": "strong", "rationale": "bool id"},
        {"id": 1, "fit": "partial", "rationale": "real", "grounding": ok_grounding()},
    ]})
    candidates = [make_influencer(1)]
    ranked = ranking.rank_candidates(object(), BRIEF, candidates, top_n=1)
    assert len(ranked) == 1
    assert ranked[0]["id"] == 1 and ranked[0]["source"] == "llm"


def test_duplicate_and_unknown_ids_dropped(monkeypatch):
    install_stub(monkeypatch, {"ranked": [
        {"id": 1, "fit": "partial", "rationale": "a", "grounding": ok_grounding()},
        {"id": 1, "fit": "partial", "rationale": "dup", "grounding": ok_grounding()},
        {"id": 77, "fit": "partial", "rationale": "hallucinated", "grounding": ok_grounding()},
        {"id": 2, "fit": "partial", "rationale": "b", "grounding": ok_grounding()},
    ]})
    candidates = [make_influencer(1), make_influencer(2)]
    ranked = ranking.rank_candidates(object(), BRIEF, candidates, top_n=4)
    ids = [e["id"] for e in ranked]
    assert ids.count(1) == 1
    # id 77 unknown -> dropped; slot filled from retrieval order (only cand 2 left)
    assert 2 in ids
    assert all(e["id"] != 77 for e in ranked)


def test_invalid_fit_coerced_to_partial(monkeypatch):
    install_stub(monkeypatch, {"ranked": [
        {"id": 1, "fit": "amazing", "rationale": "x", "grounding": ok_grounding()},
    ]})
    candidates = [make_influencer(1)]
    ranked = ranking.rank_candidates(object(), BRIEF, candidates, top_n=1)
    assert ranked[0]["fit"] == "partial"


# ------------------------------------------------------------ output budget

def _worst_case_response() -> str:
    """A response at the schema's documented worst case.

    Every bound filled: the longest rationale, the maximum number of
    citations, and the longest permitted quote in each.
    """
    fields = sorted(ranking.GROUNDABLE_FIELDS)
    entries = []
    for i in range(5):
        entries.append({
            "id": i + 1,
            "fit": "strong",
            "rationale": "R" * ranking.MAX_RATIONALE_LENGTH,
            "grounding": [
                {"field": fields[j % len(fields)], "quote": "Q" * ranking.MAX_QUOTE_LENGTH}
                for j in range(ranking.MAX_GROUNDING_PER_ENTRY)
            ],
        })
    return json.dumps({"ranked": entries})


def test_worst_case_response_fits_the_output_cap():
    """The regression this guards.

    Adding `grounding` without bounding it took the worst case from ~199 to
    ~1069 tokens against a 512 cap. A response cut at the cap is truncated
    mid-string, fails to parse, and degrades the whole ranking to retrieval
    order while burning one of 20 daily free-tier calls.
    """
    payload = _worst_case_response()
    # ~4 chars per token is the usual English/JSON ratio. The assertion is
    # deliberately loose so it tracks the real budget, not an exact ratio.
    assert len(payload) / 4 < config.RANKING_MAX_OUTPUT_TOKENS, (
        f"worst case needs ~{len(payload) // 4} tokens but the cap is "
        f"{config.RANKING_MAX_OUTPUT_TOKENS}"
    )


def test_the_previously_unbounded_shape_would_not_have_fit():
    """Documents why the bounds exist.

    Eight unbounded citations with long bio spans -- which the prompt's
    original "cite every claim" wording invited -- is what overflowed the old
    512-token cap.
    """
    fields = sorted(ranking.GROUNDABLE_FIELDS)
    unbounded = json.dumps({"ranked": [
        {
            "id": 1,
            "fit": "strong",
            "rationale": "R" * 160,
            "grounding": [
                {"field": fields[j % len(fields)],
                 "quote": "Lifting daily. Notes on form and mobility." * 2}
                for j in range(len(fields))
            ],
        }
        for _ in range(5)
    ]})
    assert len(unbounded) / 4 > 512, "the old shape is expected to overflow a 512-token cap"


def test_schema_bounds_are_applied():
    props = ranking.RANKING_SCHEMA["properties"]["ranked"]["items"]["properties"]
    assert props["grounding"]["maxItems"] == ranking.MAX_GROUNDING_PER_ENTRY
    assert props["grounding"]["items"]["properties"]["quote"]["maxLength"] == ranking.MAX_QUOTE_LENGTH
    assert props["rationale"]["maxLength"] == ranking.MAX_RATIONALE_LENGTH


def test_gen_config_uses_the_configured_cap():
    assert ranking._gen_config().max_output_tokens == config.RANKING_MAX_OUTPUT_TOKENS


def test_output_cap_is_configurable(monkeypatch):
    monkeypatch.setattr(config, "RANKING_MAX_OUTPUT_TOKENS", 4096)
    assert ranking._gen_config().max_output_tokens == 4096


# ----------------------------------------------------- grounded reasons

def test_valid_citation_is_kept_and_fit_stands(monkeypatch):
    install_stub(monkeypatch, {"ranked": [
        {"id": 1, "fit": "strong", "rationale": "trains at home",
         "grounding": [{"field": "tags", "quote": "gym"}]},
    ]})
    ranked = ranking.rank_candidates(object(), BRIEF, [make_influencer(1)], top_n=1)
    assert ranked[0]["source"] == "llm"
    assert ranked[0]["fit"] == "strong"
    assert ranked[0]["grounding"] == [{"field": "tags", "quote": "gym"}]


def test_prose_field_accepts_a_verbatim_span(monkeypatch):
    install_stub(monkeypatch, {"ranked": [
        {"id": 1, "fit": "strong", "rationale": "teaches form",
         "grounding": [{"field": "bio", "quote": "Training tips"}]},
    ]})
    ranked = ranking.rank_candidates(object(), BRIEF, [make_influencer(1)], top_n=1)
    assert ranked[0]["grounding"] == [{"field": "bio", "quote": "Training tips"}]


def test_list_field_requires_an_exact_item(monkeypatch):
    """A prefix of a tag must not pass; a list is a set of discrete facts."""
    install_stub(monkeypatch, {"ranked": [
        {"id": 1, "fit": "strong", "rationale": "x",
         "grounding": [{"field": "tags", "quote": "run"}]},
    ]})
    ranked = ranking.rank_candidates(object(), BRIEF, [make_influencer(1)], top_n=1)
    assert ranked[0]["grounding"] == []
    assert ranked[0]["source"] == "llm_unverified"


def test_fabricated_quote_is_rejected(monkeypatch):
    install_stub(monkeypatch, {"ranked": [
        {"id": 1, "fit": "strong", "rationale": "yoga every day",
         "grounding": [{"field": "tags", "quote": "yoga"}]},
    ]})
    ranked = ranking.rank_candidates(object(), BRIEF, [make_influencer(1)], top_n=1)
    assert ranked[0]["grounding"] == []


def test_field_outside_the_allowlist_is_rejected(monkeypatch):
    install_stub(monkeypatch, {"ranked": [
        {"id": 1, "fit": "strong", "rationale": "x",
         "grounding": [{"field": "follower_count", "quote": "gym"}]},
    ]})
    ranked = ranking.rank_candidates(object(), BRIEF, [make_influencer(1)], top_n=1)
    assert ranked[0]["grounding"] == []


def test_strong_downgrades_when_nothing_can_be_confirmed(monkeypatch):
    """An unbacked 'strong' is exactly the claim the check exists to stop."""
    install_stub(monkeypatch, {"ranked": [
        {"id": 1, "fit": "strong", "rationale": "perfect match",
         "grounding": [{"field": "tags", "quote": "yoga"}]},
    ]})
    ranked = ranking.rank_candidates(object(), BRIEF, [make_influencer(1)], top_n=1)
    assert ranked[0]["fit"] == "partial"
    assert ranked[0]["source"] == "llm_unverified"
    assert "could not be confirmed" in ranked[0]["rationale"]


def test_unverified_reason_names_what_was_checked(monkeypatch):
    install_stub(monkeypatch, {"ranked": [
        {"id": 1, "fit": "partial", "rationale": "good energy"},
    ]})
    ranked = ranking.rank_candidates(object(), BRIEF, [make_influencer(1)], top_n=1)
    assert "gym" in ranked[0]["rationale"]


def test_weak_stays_weak_when_unverified(monkeypatch):
    install_stub(monkeypatch, {"ranked": [
        {"id": 1, "fit": "weak", "rationale": "off topic"},
    ]})
    ranked = ranking.rank_candidates(object(), BRIEF, [make_influencer(1)], top_n=1)
    assert ranked[0]["fit"] == "weak"


def test_one_field_is_cited_once(monkeypatch):
    install_stub(monkeypatch, {"ranked": [
        {"id": 1, "fit": "strong", "rationale": "x",
         "grounding": [{"field": "tags", "quote": "gym"},
                       {"field": "tags", "quote": "running"}]},
    ]})
    ranked = ranking.rank_candidates(object(), BRIEF, [make_influencer(1)], top_n=1)
    assert len(ranked[0]["grounding"]) == 1


def test_partial_grounding_is_kept_alongside_valid_citations(monkeypatch):
    install_stub(monkeypatch, {"ranked": [
        {"id": 1, "fit": "partial", "rationale": "some overlap",
         "grounding": [{"field": "tags", "quote": "yoga"},
                       {"field": "audience_age", "quote": "25-34"}]},
    ]})
    ranked = ranking.rank_candidates(object(), BRIEF, [make_influencer(1)], top_n=1)
    assert ranked[0]["grounding"] == [{"field": "audience_age", "quote": "25-34"}]
    assert ranked[0]["source"] == "llm"


def test_malformed_grounding_does_not_crash(monkeypatch):
    install_stub(monkeypatch, {"ranked": [
        {"id": 1, "fit": "strong", "rationale": "x",
         "grounding": ["garbage", {"field": "tags"}, {"quote": "gym"}, None,
                       {"field": "tags", "quote": "  "}]},
    ]})
    ranked = ranking.rank_candidates(object(), BRIEF, [make_influencer(1)], top_n=1)
    assert ranked[0]["grounding"] == []


def test_every_groundable_field_exists_on_the_model():
    """A field the model may cite must exist on Influencer, or the allowlist
    is a promise the code cannot keep."""
    from dataclasses import fields
    names = {f.name for f in fields(Influencer)}
    for field in ranking.GROUNDABLE_FIELDS:
        assert field in names, f"{field} is groundable but not an Influencer field"


def test_reach_figures_are_not_groundable():
    """Followers and engagement cannot support a topical claim, and they are
    not in corpus_text, so a reason must not be able to cite them."""
    assert "followers" not in ranking.GROUNDABLE_FIELDS
    assert "engagement_rate" not in ranking.GROUNDABLE_FIELDS


def test_short_list_filled_from_retrieval_order(monkeypatch):
    install_stub(monkeypatch, {"ranked": [
        {"id": 3, "fit": "partial", "rationale": "only this one", "grounding": ok_grounding()},
    ]})
    candidates = [make_influencer(i) for i in (1, 2, 3)]
    ranked = ranking.rank_candidates(object(), BRIEF, candidates, top_n=3)
    assert [e["id"] for e in ranked] == [3, 1, 2]
    assert ranked[0]["source"] == "llm"
    assert {e["source"] for e in ranked[1:]} == {"filled"}


def test_ranking_cache_hit_avoids_second_llm_call(monkeypatch):
    calls = []

    def counting_stub(client, model, contents, gen_config=None):
        calls.append(1)
        return _FakeResponse({"ranked": [{"id": 1, "fit": "strong", "rationale": "cached", "grounding": ok_grounding()}]})

    monkeypatch.setattr(ranking, "generate_content_throttled", counting_stub)
    candidates = [make_influencer(1)]
    first = ranking.rank_candidates(object(), BRIEF, candidates, top_n=1)
    second = ranking.rank_candidates(object(), BRIEF, candidates, top_n=1)
    assert len(calls) == 1
    assert first == second

    # Different top_n must miss
    ranking.rank_candidates(object(), BRIEF, candidates, top_n=2)
    assert len(calls) == 2


# ------------------------------------------------------ truncation detection

class _Candidate:
    def __init__(self, finish_reason):
        self.finish_reason = finish_reason


class _FinishResponse:
    """A response shaped like the SDK's, with a controllable finish reason."""

    def __init__(self, payload, finish_reason=None):
        self._payload = json.dumps(payload) if not isinstance(payload, str) else payload
        self.candidates = [_Candidate(finish_reason)] if finish_reason else []
        self.text = self._payload

    @property
    def reason(self):
        return self._payload


class _Enumish:
    def __init__(self, name):
        self.name = name

    def __str__(self):
        return f"FinishReason.{self.name}"


def test_truncation_at_the_output_cap_is_named_in_the_log(monkeypatch, caplog):
    """The whole point: "Unterminated string" does not say why.

    A response stopped at the token cap is cut mid-string, so the parse error
    mentions neither the cause nor the fix. The log must name the cap and the
    knob that changes it.
    """
    # A response cut at the cap ends mid-string, exactly as it does live.
    truncated = '{"ranked": [{"id": 1, "fit": "strong", "rationale": "cut off here'
    monkeypatch.setattr(
        ranking, "generate_content_throttled",
        lambda client, model, contents, gen_config=None: _FinishResponse(
            truncated, _Enumish("MAX_TOKENS")
        ),
    )
    with caplog.at_level("WARNING", logger="src.ranking"):
        ranked = ranking.rank_candidates(object(), BRIEF, [make_influencer(1)], top_n=1)

    assert all(e["source"] == "fallback" for e in ranked)
    logged = caplog.text
    assert "output cap" in logged
    assert str(config.RANKING_MAX_OUTPUT_TOKENS) in logged
    assert "MAX_GROUNDING_PER_ENTRY" in logged
    # The vague parse error is the thing being replaced.
    assert "Unterminated string" not in logged


def test_a_complete_response_is_not_reported_as_truncated(monkeypatch, caplog):
    monkeypatch.setattr(
        ranking, "generate_content_throttled",
        lambda client, model, contents, gen_config=None: _FinishResponse(
            {"ranked": [{"id": 1, "fit": "strong", "rationale": "ok", "grounding": ok_grounding()}]},
            _Enumish("STOP"),
        ),
    )
    with caplog.at_level("WARNING", logger="src.ranking"):
        ranked = ranking.rank_candidates(object(), BRIEF, [make_influencer(1)], top_n=1)

    assert ranked[0]["source"] == "llm"
    assert "output cap" not in caplog.text


def test_a_non_token_stop_is_still_named(monkeypatch, caplog):
    """Safety and recitation stops look identical from the parse error alone."""
    monkeypatch.setattr(
        ranking, "generate_content_throttled",
        lambda client, model, contents, gen_config=None: _FinishResponse(
            json.dumps({"ranked": []}), _Enumish("SAFETY")
        ),
    )
    with caplog.at_level("WARNING", logger="src.ranking"):
        ranked = ranking.rank_candidates(object(), BRIEF, [make_influencer(1)], top_n=1)

    assert all(e["source"] == "fallback" for e in ranked)
    assert "SAFETY" in caplog.text


def test_a_response_with_no_candidates_is_not_treated_as_truncated(monkeypatch):
    """Some responses carry no candidates list; that is not a truncation.

    Asserted by the absence of a fallback: the payload parsed and went through
    verification, which downgrades an entry with no citations to
    `llm_unverified` rather than discarding the ranking.
    """
    monkeypatch.setattr(
        ranking, "generate_content_throttled",
        lambda client, model, contents, gen_config=None: _FinishResponse(
            {"ranked": [{"id": 1, "fit": "partial", "rationale": "r", "grounding": []}]}
        ),
    )
    ranked = ranking.rank_candidates(object(), BRIEF, [make_influencer(1)], top_n=1)
    assert all(e["source"] != "fallback" for e in ranked)


def test_verification_survives_citations_the_schema_bound_should_have_stopped():
    """The bounds are a model-side guard, so the server must not assume them.

    If a fourth citation or a long quote arrives anyway, verification drops it
    or keeps it without crashing.
    """
    creator = make_influencer(1)
    entry = {
        "id": 1,
        "fit": "strong",
        "rationale": "r",
        "grounding": [
            {"field": "tags", "quote": "gym"},
            {"field": "bio", "quote": "Training tips"},
            {"field": "audience_age", "quote": "25-34"},
            {"field": "tags", "quote": "running"},
        ],
    }
    result = ranking._verify_entry(entry, creator, "strong")
    assert result["source"] == "llm"
    assert len(result["grounding"]) == 3
    # The fourth repeats a field already cited, so it is not re-listed.
    assert [g["field"] for g in result["grounding"]] == ["tags", "bio", "audience_age"]


# ------------------------------------------------------------ daily quota

def _quota_error():
    from src.gemini_client import DailyQuotaExhausted

    return DailyQuotaExhausted(
        "generate_content(gemini-2.5-flash-lite)",
        "GenerateRequestsPerDayPerProjectPerModel-FreeTier",
        20,
    )


def test_daily_quota_does_not_propagate_out_of_ranking(monkeypatch):
    """The regression.

    `DailyQuotaExhausted` extends RuntimeError, not APIError, so the general
    handler never saw it. It escaped through the job manager and failed the
    whole match, when retrieval order was perfectly usable.
    """
    def boom(client, model, contents, gen_config=None):
        raise _quota_error()

    monkeypatch.setattr(ranking, "generate_content_throttled", boom)
    candidates = [make_influencer(1)]

    ranked = ranking.rank_candidates(object(), BRIEF, candidates, top_n=1)  # must not raise

    assert [e["source"] for e in ranked] == ["fallback"]
    assert ranked[0]["fallback_reason"].startswith(ranking.QUOTA_REASON_TAG)
    assert ranked[0]["fit"] == "unknown"


def test_quota_reason_carries_the_reset_hint(monkeypatch):
    """The user needs to know retrying will not help, and when it will."""
    monkeypatch.setattr(
        ranking, "generate_content_throttled",
        lambda client, model, contents, gen_config=None: (_ for _ in ()).throw(_quota_error()),
    )
    ranked = ranking.rank_candidates(object(), BRIEF, [make_influencer(1)], top_n=1)
    assert "midnight Pacific" in ranked[0]["fallback_reason"]
    assert "20 requests/day" in ranked[0]["fallback_reason"]


def test_quota_reason_is_not_tagged_as_an_outage(monkeypatch):
    """A cap and an outage need different advice, so the tags must differ."""
    monkeypatch.setattr(
        ranking, "generate_content_throttled",
        lambda client, model, contents, gen_config=None: (_ for _ in ()).throw(_quota_error()),
    )
    ranked = ranking.rank_candidates(object(), BRIEF, [make_influencer(1)], top_n=1)

    monkeypatch.setattr(ranking, "generate_content_throttled", lambda *a, **k: _FakeResponse(
        {"ranked": [{"id": 1, "fit": "partial", "rationale": "r", "grounding": ok_grounding()}]}
    ))
    other = ranking.rank_candidates(object(), BRIEF, [make_influencer(1)], top_n=1)
    other_reason = other[0].get("fallback_reason", "")

    assert ranked[0]["fallback_reason"] != other_reason
    assert not other_reason.startswith(ranking.QUOTA_REASON_TAG)


def test_a_per_minute_throttle_still_falls_back(monkeypatch):
    """Regression guard on the neighbouring branch.

    A 429 that exhausts its retries is re-raised as ClientError, an APIError
    subclass, so it was already handled. That must not change.
    """
    def throttle(client, model, contents, gen_config=None):
        raise genai_errors.ClientError(429, {"message": "RESOURCE_EXHAUSTED"})

    monkeypatch.setattr(ranking, "generate_content_throttled", throttle)
    ranked = ranking.rank_candidates(object(), BRIEF, [make_influencer(1)], top_n=1)

    assert all(e["source"] == "fallback" for e in ranked)
    assert not ranked[0]["fallback_reason"].startswith(ranking.QUOTA_REASON_TAG)


def test_a_successful_ranking_has_no_fallback_reason():
    ranked = ranking._verify_entry(
        {"id": 1, "fit": "strong", "rationale": "r", "grounding": ok_grounding()},
        make_influencer(1), "strong",
    )
    assert "fallback_reason" not in ranked
