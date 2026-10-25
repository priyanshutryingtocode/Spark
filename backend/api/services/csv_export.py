from __future__ import annotations

import csv
import io

from src.corpora import DEFAULT_KIND, PROSPECTS, kind_for_record

#: Fields both corpora have, so one reader serves both column sets.
_COMMON = {
    "rank": lambda c, e, r: r,
    "semantic_similarity": lambda c, e, r: c.get("similarity", ""),
    "fit": lambda c, e, r: e.get("fit", ""),
    "source": lambda c, e, r: e.get("source", ""),
    "rationale": lambda c, e, r: e.get("rationale", ""),
    "grounding": lambda c, e, r: "; ".join(
        f"{claim.get('field')}={claim.get('quote')}" for claim in e.get("grounding", [])
    ),
    "fallback_reason": lambda c, e, r: e.get("fallback_reason", ""),
    "tags": lambda c, e, r: "|".join(c.get("tags", [])),
}

#: The creator header, pinned in the order this export has always written it: it
#: is a deliverable people paste into a spreadsheet, so moving a column shifts
#: every column after it for anyone reusing an old template.
_CREATOR_ONLY = {
    "creator_key": lambda c, e, r: c.get("creator_key") or c.get("handle", ""),
    "handle": lambda c, e, r: c.get("handle", ""),
    "name": lambda c, e, r: c.get("name", ""),
    "platform": lambda c, e, r: c.get("platform", ""),
    "city": lambda c, e, r: c.get("city", ""),
    "country": lambda c, e, r: c.get("country", ""),
    "followers": lambda c, e, r: c.get("followers", 0),
    "engagement_pct": lambda c, e, r: c.get("engagement_pct", 0),
    "average_views": lambda c, e, r: c.get("average_views", 0),
    "average_likes": lambda c, e, r: c.get("average_likes", 0),
    "average_comments": lambda c, e, r: c.get("average_comments", 0),
    "verified": lambda c, e, r: c.get("verified", False),
    "posts_per_week": lambda c, e, r: c.get("posts_per_week", 0),
    "account_age_years": lambda c, e, r: c.get("account_age_years", 0),
    "content_style": lambda c, e, r: c.get("content_style", ""),
    "language": lambda c, e, r: c.get("language", ""),
    "audience_age": lambda c, e, r: c.get("audience_age", ""),
    "audience_gender": lambda c, e, r: c.get("audience_gender", ""),
    "audience_country": lambda c, e, r: c.get("audience_country", ""),
    "reach_ratio": lambda c, e, r: f"{c['reach_ratio']:.3f}" if c.get("reach_ratio") is not None else "",
    "sponsored_ratio": lambda c, e, r: f"{c['sponsored_ratio']:.3f}" if c.get("sponsored_ratio") is not None else "",
    "growth_trend": lambda c, e, r: c.get("growth_trend", ""),
    "audience_top_countries": lambda c, e, r: "|".join(c.get("audience_top_countries", [])),
    "evidence": lambda c, e, r: "; ".join(e.get("evidence", [])),
    "brand_collaborations": lambda c, e, r: "|".join(c.get("brand_collaborations", [])),
}

#: Company columns. `evidence` is deliberately absent rather than blank: it is
#: per-field verification against MatchSignals, which is the creator's signal set,
#: so a company run has no such list to print. An empty column would read as
#: "every claim was checked and unsupported".
_PROSPECT_ONLY = {
    "creator_key": lambda c, e, r: c.get("creator_key") or c.get("name", ""),
    "name": lambda c, e, r: c.get("name", ""),
    "industry": lambda c, e, r: c.get("industry", ""),
    "headcount": lambda c, e, r: c.get("headcount", 0),
    "city": lambda c, e, r: c.get("city", ""),
    "country": lambda c, e, r: c.get("country", ""),
    "founded_year": lambda c, e, r: c.get("founded_year", 0),
    "funding_stage": lambda c, e, r: c.get("funding_stage", ""),
    "seniority_mix": lambda c, e, r: c.get("seniority_mix", ""),
    "department_mix": lambda c, e, r: "|".join(c.get("department_mix", [])),
    "tech_stack": lambda c, e, r: "|".join(c.get("tech_stack", [])),
    "buying_signals": lambda c, e, r: "|".join(c.get("buying_signals", [])),
    "growth_trend": lambda c, e, r: c.get("growth_trend", ""),
    # Emitted as numbers, not formatted strings. A company can be shrinking, and
    # `f"{growth_rate:.3f}"` turns a legitimate -0.064 into the string "-0.064" --
    # which `_safe_cell` then prefixes with an apostrophe as spreadsheet formula
    # injection, shipping a shrinking company's growth rate into the sheet as the
    # text `'-0.064`. A real float also lets the sheet sum and sort the column.
    "growth_rate": lambda c, e, r: float(c["growth_rate"]) if c.get("growth_rate") is not None else "",
    "hiring_intensity": lambda c, e, r: float(c["hiring_intensity"]) if c.get("hiring_intensity") is not None else "",
    "top_markets": lambda c, e, r: "|".join(c.get("top_markets", [])),
    "website": lambda c, e, r: c.get("website", ""),
    "description": lambda c, e, r: c.get("description", ""),
}


#: The creator header, in the exact order this export has always written it.
#: Pinned as an explicit tuple rather than derived from dict order because the
#: order is a contract: this file is a deliverable people paste into a
#: spreadsheet, and moving a column shifts every column after it for whoever
#: reuses an old template.
_CREATOR_ORDER = (
    "rank", "creator_key", "handle", "name", "platform", "city", "country",
    "followers", "engagement_pct", "average_views", "average_likes",
    "average_comments", "verified", "posts_per_week", "account_age_years",
    "content_style", "language", "audience_age", "audience_gender",
    "audience_country", "semantic_similarity", "reach_ratio", "sponsored_ratio",
    "growth_trend", "audience_top_countries", "fit", "source", "rationale",
    "evidence", "grounding", "fallback_reason", "tags", "brand_collaborations",
)

#: The company header: identity first, then what a seller filters on (industry
#: and headcount), then inferred signals, then free text last because
#: `description` is the widest column.
_PROSPECT_ORDER = (
    "rank", "creator_key", "name", "industry", "headcount", "city", "country",
    "founded_year", "funding_stage", "seniority_mix", "department_mix",
    "tech_stack", "buying_signals", "growth_trend", "growth_rate",
    "hiring_intensity", "top_markets", "website", "description",
    "semantic_similarity", "fit", "source", "rationale", "grounding",
    "fallback_reason", "tags",
)

#: Per corpus, not merged into one table. Merging let `_PROSPECT_ONLY` shadow
#: `_CREATOR_ONLY` on `creator_key`, so the creator handle fallback went dead and
#: a creator without a stored key exported its name -- invisible to a guard that
#: only checks a column *has* a reader, never that it has the right one.
_ORDERS = {DEFAULT_KIND: _CREATOR_ORDER, PROSPECTS.kind: _PROSPECT_ORDER}
_READERS = {
    DEFAULT_KIND: {**_CREATOR_ONLY, **_COMMON},
    PROSPECTS.kind: {**_PROSPECT_ONLY, **_COMMON},
}

for _kind, _order in _ORDERS.items():
    _missing = [name for name in _order if name not in _READERS[_kind]]
    assert not _missing, f"{_kind} CSV columns with no reader: {_missing}"
    _unused = [name for name in _READERS[_kind] if name not in _order]
    assert not _unused, f"{_kind} CSV readers no column selects: {_unused}"


def _order_for(kind: str) -> tuple[str, ...]:
    """Column order for `kind`, raising on an unknown one.

    Not defaulted: an unmigrated or typo'd kind would otherwise write a
    33-column creator sheet for a companies run, which `src.corpora.get_corpus`
    deliberately refuses to do.
    """
    try:
        return _ORDERS[kind]
    except KeyError:
        raise KeyError(f"unknown corpus kind {kind!r}; known: {sorted(_ORDERS)}") from None


def columns_for(kind: str) -> list[str]:
    """Header row for one corpus."""
    return list(_order_for(kind))


#: The one rule for "which corpus is this run" lives in src.corpora; this is a
#: local alias so the CSV module reads without reaching across.
kind_for_run = kind_for_record


def build_csv(run: dict) -> str:
    kind = kind_for_run(run)
    readers = _READERS[kind]
    cell = {name: readers[name] for name in _order_for(kind)}
    candidates = {item["id"]: item for item in run["result"]["candidates"]}
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(list(cell))
    for position, entry in enumerate(run["result"]["ranked"], start=1):
        candidate = candidates.get(entry.get("id"))
        # A ranked entry whose snapshot is missing is skipped rather than
        # raising. The stored rank wins over the loop position, or skipping a row
        # would shift every rank after it and the sheet would disagree with the
        # rank the UI shows for the same run.
        if candidate is None:
            continue
        rank = entry.get("rank") or position
        writer.writerow([
            _safe_cell(read(candidate, entry, rank)) for read in cell.values()
        ])
    return output.getvalue()


def _safe_cell(value):
    """Neutralise spreadsheet formula injection. A company's description and
    buying_signals are free text, so a leading `=` is likelier here than in a
    creator handle.
    """
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-")):
        return "'" + value
    return value
