"""LLM ranking step: asks Gemini to pick and justify the best candidates
from the retrieved pool. Uses response_schema for structured, directly
parseable JSON output rather than hoping the model follows a text format.
"""

import hashlib
import json
import logging
import threading
from collections import OrderedDict

from google import genai
from google.genai import errors, types

from . import config
from .corpora import Influencer
from .gemini_client import DailyQuotaExhausted, generate_content_throttled
from .models import Brief
from .rubrics import CREATOR_RUBRIC, Rubric

logger = logging.getLogger(__name__)

_RANK_CACHE_SIZE = 64
_rank_cache: OrderedDict[str, list[dict]] = OrderedDict()
_rank_cache_lock = threading.Lock()


def _rank_cache_key(
    brief: Brief,
    candidates: list[Influencer],
    top_n: int,
    kind: str,
    relaxed_filters: list[str] | None = None,
) -> str:
    """Key by the corpus, complete brief, candidate order, and requested size.

    Ids alone do not identify a candidate: creator 5 and prospect 5 are
    different entities, and a brief carrying platform "Any" with no audience or
    vibe is identical across both corpora. Without the kind in the key, a
    prospect query that happened to draw the same id set as an earlier creator
    query would be served the creator's ranking -- different companies and
    creators under ids that are valid in both, so it fails silently and looks
    entirely plausible. The full brief and ordered IDs also matter: structured
    preferences now influence the candidate order and are part of the prompt.
    """
    raw = json.dumps(
        {
            "kind": kind,
            "brief": vars(brief),
            "top_n": top_n,
            "candidate_ids": [candidate.id for candidate in candidates],
            "relaxed_filters": relaxed_filters or [],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _clear_rank_cache() -> None:
    """Exposed for tests; not part of the public API."""
    with _rank_cache_lock:
        _rank_cache.clear()

VALID_FIT_LEVELS = {"strong", "partial", "weak"}

#: The CREATOR rubric's citable fields, kept as module-level names because four
#: test modules and the API schema docstring reference them. They are the
#: creator rubric's, not the app's -- PROSPECT_RUBRIC has its own, and a reason
#: is verified against whichever rubric produced it.
GROUNDABLE_FIELDS = CREATOR_RUBRIC.groundable_fields

MAX_GROUNDING_PER_ENTRY = 3
MAX_QUOTE_LENGTH = 80
MAX_RATIONALE_LENGTH = 240

def _schema_for(rubric: Rubric) -> dict:
    """The response schema, with the field enum taken from the rubric.

    Building it per call is what keeps the enum honest: a hardcoded enum would
    let the model name a field the verifier then discards, so the citation
    silently drops instead of being reported as invalid.
    """
    return {
        "type": "object",
    "properties": {
        "ranked": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "fit": {"type": "string", "enum": ["strong", "partial", "weak"]},
                    "rationale": {"type": "string", "maxLength": MAX_RATIONALE_LENGTH},
                    "grounding": {
                        "type": "array",
                        "maxItems": MAX_GROUNDING_PER_ENTRY,
                        "items": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string", "enum": sorted(rubric.groundable_fields)},
                                "quote": {"type": "string", "maxLength": MAX_QUOTE_LENGTH},
                            },
                            "required": ["field", "quote"],
                        },
                    },
                },
                "required": ["id", "fit", "rationale"],
            },
        }
    },
    "required": ["ranked"],
    }


#: The CREATOR response schema, kept as a module name for the same reason as
#: GROUNDABLE_FIELDS. A prospect request builds its own from
#: _schema_for(PROSPECT_RUBRIC) at call time.
RANKING_SCHEMA = _schema_for(CREATOR_RUBRIC)

EXPECTED_RANKING_ERRORS = (errors.APIError, json.JSONDecodeError, KeyError, TypeError)
QUOTA_REASON_TAG = "daily_quota"


def _build_prompt(brief: Brief, candidates: list, top_n: int, rubric: Rubric) -> str:
    """The corpus's own instructions, with its own candidate payload.

    Every field the rubric allows to be cited is also sent, because the reason
    the user reads has to rest on something they can check.
    """
    return rubric.render(
        brief, candidates, top_n,
        grounding_per_entry=MAX_GROUNDING_PER_ENTRY,
        quote_length=MAX_QUOTE_LENGTH,
    )


def _verify_entry(entry: dict, creator, fit: str, rubric: Rubric = CREATOR_RUBRIC) -> dict:
    """Check the model's citations against the stored profile, then downgrade.

    The model writes the reason; this decides whether it stands. A citation
    survives only if it names a field in the rubric that produced it and quotes
    field's real value, so a client can read every surviving claim as fact
    rather than as an assertion. A "strong" fit with nothing to stand on is not
    a strong fit, and a reason with no surviving citation at all is replaced
    rather than shown unsupported.
    """
    grounding: list[dict] = []
    seen_fields: set[str] = set()
    for claim in entry.get("grounding") or []:
        if not isinstance(claim, dict):
            continue
        field, quote = claim.get("field"), claim.get("quote")
        if not isinstance(field, str) or not isinstance(quote, str) or not quote.strip():
            continue
        read = rubric.groundable_fields.get(field)
        if read is None or field in seen_fields:
            continue
        value = read(creator)
        if isinstance(value, list):
            ok = quote in [str(item) for item in value]
        else:
            ok = quote in str(value)
        if ok:
            seen_fields.add(field)
            grounding.append({"field": field, "quote": quote})

    rationale = entry.get("rationale", "")
    if not isinstance(rationale, str):
        rationale = ""

    if not grounding:
        # Nothing the model said could be checked.
        return {
            "id": creator.id,
            "fit": "weak" if fit == "weak" else "partial",
            "rationale": _unverified_rationale(creator, rubric),
            "source": "llm_unverified",
            "grounding": [],
        }
    return {
        "id": creator.id,
        "fit": fit,
        "rationale": rationale,
        "source": "llm",
        "grounding": grounding,
    }


def _unverified_rationale(record, rubric: Rubric) -> str:
    """Say what was actually checked, instead of repeating an unsupported claim."""
    return rubric.unverified_rationale(record)


def _truncation_reason(response) -> str | None:
    """Describe a response that stopped early, or None if it looks complete.

    Gemini reports why it stopped on the first candidate. MAX_TOKENS is the one
    that matters here: the text is cut mid-string, so the failure surfaces as
    an unparseable-JSON error that says nothing about the cause. A safety or
    recitation stop is also worth naming, since it looks the same from the
    parse error alone.
    """
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return None
    finish = getattr(candidates[0], "finish_reason", None)
    if finish is None:
        return None
    name = getattr(finish, "name", None) or str(finish)
    if name == "STOP" or name == "FinishReason.STOP":
        return None
    if name.endswith("MAX_TOKENS"):
        return (
            f"Response hit the {config.RANKING_MAX_OUTPUT_TOKENS}-token output cap "
            "before it was complete. Raise RANKING_MAX_OUTPUT_TOKENS, or tighten "
            f"MAX_GROUNDING_PER_ENTRY (currently {MAX_GROUNDING_PER_ENTRY})."
        )
    return f"Response stopped early: finish_reason={name}"


def _fallback_ranking(candidates: list[Influencer], top_n: int, reason: str) -> list[dict]:
    """Used when the model's response can't be trusted at all (API error,
    unparseable JSON, or every returned id was invalid). Falls back to the
    retrieval order -- candidates are already sorted by vector similarity --
    tagged with source="fallback" so callers know to show a real warning
    rather than presenting this as a normal ranked result."""
    logger.warning("Ranking fallback triggered: %s", reason)
    return [
        {
            "id": c.id,
            "fit": "unknown",
            "rationale": "Selected by retrieval ranking (LLM ranking unavailable).",
            "source": "fallback",
            "fallback_reason": reason,
            "grounding": [],
        }
        for c in candidates[:top_n]
    ]


def _gen_config(rubric: Rubric = CREATOR_RUBRIC) -> types.GenerateContentConfig:
    """Response schema + latency/reproducibility tuning.

    - temperature=0 pins ranking so identical briefs produce identical
      shortlists -- without it, run-to-run drift swamps small quality changes
      and makes A/B comparisons (embedding models, prompt edits) meaningless.
    - thinking_budget=0 keeps Gemini 2.5 models from spending time on hidden
      'thinking' tokens; guarded with hasattr so older google-genai SDKs
      (no ThinkingConfig) still work."""
    kwargs = {
        "response_mime_type": "application/json",
        "response_schema": _schema_for(rubric),
        "temperature": 0.0,
        "max_output_tokens": config.RANKING_MAX_OUTPUT_TOKENS,
    }
    thinking = getattr(types, "ThinkingConfig", None)
    if thinking is not None:
        kwargs["thinking_config"] = thinking(thinking_budget=0)
    return types.GenerateContentConfig(**kwargs)


def rank_candidates(
    client: genai.Client,
    brief: Brief,
    candidates: list[Influencer],
    top_n: int = 5,
    corpus_kind: str = "creator",
    rubric: Rubric = CREATOR_RUBRIC,
    relaxed_filters: list[str] | None = None,
) -> list[dict]:
    """Rank `candidates` down to `top_n` under `rubric`.

    `corpus_kind` exists only to key the cache; it is not otherwise used, and it
    is passed separately rather than read off the rubric so the cache can never
    be poisoned by two rubrics sharing a kind.
    """

    cache_key = _rank_cache_key(brief, candidates, top_n, corpus_kind, relaxed_filters)
    with _rank_cache_lock:
        cached = _rank_cache.get(cache_key)
        if cached is not None:
            _rank_cache.move_to_end(cache_key)
            return list(cached)

    valid_ids = {c.id for c in candidates}

    try:
        response = generate_content_throttled(
            client,
            model=config.GEN_MODEL,
            contents=rubric.render(
                brief,
                candidates,
                top_n,
                grounding_per_entry=MAX_GROUNDING_PER_ENTRY,
                quote_length=MAX_QUOTE_LENGTH,
                relaxed_filters=relaxed_filters,
            ),
            gen_config=_gen_config(rubric),
        )
    except DailyQuotaExhausted as e:

        return _fallback_ranking(candidates, top_n, reason=f"{QUOTA_REASON_TAG}: {e}")
    except EXPECTED_RANKING_ERRORS as e:
        return _fallback_ranking(candidates, top_n, reason=f"{type(e).__name__}: {e}")

    truncated = _truncation_reason(response)
    if truncated:
        return _fallback_ranking(candidates, top_n, reason=truncated)

    try:
        parsed = json.loads(response.text)
        raw_ranked = parsed["ranked"]
    except EXPECTED_RANKING_ERRORS as e:
        return _fallback_ranking(candidates, top_n, reason=f"{type(e).__name__}: {e}")

    if not isinstance(raw_ranked, list):
        return _fallback_ranking(candidates, top_n, reason=f"'ranked' was {type(raw_ranked).__name__}, not a list")

    by_id = {c.id: c for c in candidates}
    seen: set[int] = set()
    cleaned: list[dict] = []
    for entry in raw_ranked:
        if not isinstance(entry, dict):
            continue
        entry_id = entry.get("id")

        if not isinstance(entry_id, int) or isinstance(entry_id, bool):
            continue
        if entry_id not in valid_ids or entry_id in seen:
            continue

        fit = entry.get("fit")
        if fit not in VALID_FIT_LEVELS:
            fit = "partial"

        seen.add(entry_id)
        cleaned.append(_verify_entry(entry, by_id[entry_id], fit, rubric))
        if len(cleaned) >= top_n:
            break

    if not cleaned:
        fallback = _fallback_ranking(candidates, top_n, reason="model returned no valid candidate ids")
        with _rank_cache_lock:
            _rank_cache[cache_key] = list(fallback)
            while len(_rank_cache) > _RANK_CACHE_SIZE:
                _rank_cache.popitem(last=False)
        return fallback

    if len(cleaned) < top_n:
        for c in candidates:
            if len(cleaned) >= top_n:
                break
            if c.id in seen:
                continue
            seen.add(c.id)
            cleaned.append({
                "id": c.id,
                "fit": "unknown",
                "rationale": "Filled from retrieval order (not ranked by the model).",
                "source": "filled",
                "grounding": [],
            })

    with _rank_cache_lock:
        _rank_cache[cache_key] = list(cleaned)
        while len(_rank_cache) > _RANK_CACHE_SIZE:
            _rank_cache.popitem(last=False)
    return cleaned
