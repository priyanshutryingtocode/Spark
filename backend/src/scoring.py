"""Structured filters and rerank inputs, declared per corpus.

Two mechanisms, one rule: **filter on a discrete requirement the corpus can
afford, rerank on a preference or a continuous magnitude.**

A brief that says "audience in the USA" has stated a requirement, and the
creator corpus has 650 creators who satisfy it -- so those are excluded and the
shortlist is the audience the brief asked for. A brief that says "prefer a
female-skewed audience" has stated a preference, and "55% Female" against a
50/50 split is a difference of degree, not of kind, so it reorders rather than
excludes. A brief that says "at least 20% reach" sets a floor on a continuous
quantity, so it also reorders.

The earlier version of this rule was "filter on what a record states, rerank on
what a third party estimates", which reads well and is wrong. Audience country
and age are inferred, yet they are discrete and the corpus is large enough to
filter on them; gender and reach are also inferred but are continuous, and
filtering on those would empty the shortlist. The stated/inferred split is a
useful proxy for the distinction, not the distinction itself.

Both mechanisms read the brief's optional structured fields. The brief's free
text still drives the embedding, so a user can keep typing in their own words and
get a good result without touching a structured control.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Sequence

#: A filter compares a corpus column against a brief field, and is applied in
#: SQL. Only for attributes a record states exactly.
@dataclass(frozen=True)
class FilterField:
    #: Column on the searchable table, unqualified. Validated as an identifier
    #: before it reaches SQL, because it is interpolated into the statement.
    column: str
    #: The `Brief` attribute holding the requested value.
    brief_field: str
    #: Human-readable name, for the UI and for "we relaxed this filter" messages.
    label: str
    #: How the brief's value is compared to the column. "in" is the default:
    #: the brief's list is a set the column's value must intersect.
    mode: str = "in"
    #: The order filters are dropped in when the filtered set comes back empty.
    #: Most selective first.
    drop_order: int = 0


#: A rerank input scores a candidate against the brief. Applied in Python after
#: retrieval, so it can read any value and explain itself.
@dataclass(frozen=True)
class RerankField:
    #: Column on the searchable table or its signals table.
    column: str
    #: The `Brief` attribute holding the requested value.
    brief_field: str
    label: str
    #: (record_value, brief_value) -> 0..1
    scorer: Callable[[Any, Any], float]
    #: How much this field contributes relative to the others. 0 disables it.
    weight: float = 1.0


def in_list(value: Any, wanted: Sequence[str]) -> float:
    """1.0 when the value is one of the wanted ones, else 0.0."""
    if not wanted:
        return 0.0
    if isinstance(value, (list, tuple, set)):
        return 1.0 if set(map(str, value)) & set(map(str, wanted)) else 0.0
    return 1.0 if str(value) in {str(w) for w in wanted} else 0.0


def equals(value: Any, wanted: Any) -> float:
    """1.0 on an exact match, case- and space-insensitive."""
    if wanted in (None, "", []):
        return 0.0
    return 1.0 if str(value).strip().casefold() == str(wanted).strip().casefold() else 0.0


def age_band_score(value: Any, wanted: Sequence[str]) -> float:
    """How well a record's audience age band matches the bands a brief asked for.

    Exact is 1.0 and a band next to a wanted one is 0.5. Adjacency is a judgement
    call, so it is a named score rather than a constant buried in a lambda: the
    evaluation can tune it, and "25-34" crediting against an "18-24" request is
    the difference between a strict and a forgiving brief.
    """
    if not wanted:
        return 0.0
    order = AGE_ORDER
    current = str(value).strip()
    if current not in order:
        return 0.0
    if current in {str(w).strip() for w in wanted}:
        return 1.0
    positions = [order.index(str(w).strip()) for w in wanted if str(w).strip() in order]
    if not positions:
        return 0.0
    distance = min(abs(order.index(current) - p) for p in positions)
    return 0.5 if distance == 1 else 0.0


def gender_score(value: Any, wanted: Any) -> float:
    """How well a record's audience gender split matches the brief's preference.

    A stated split like "62% Female" against a female-preferring brief scores
    high; "50% Female / 50% Male" scores low but not zero, because a balanced
    audience is not a bad audience. The brief's preference is never a constraint:
    a creator with a mixed audience is still a candidate, just a weaker one.
    """
    if not wanted or str(wanted).strip().lower() in {"any", ""}:
        return 0.0
    text = str(value).lower()
    female = _percent(text, "female")
    male = _percent(text, "male")
    if female is None and male is None:
        return 0.0
    preference = str(wanted).strip().lower()
    if preference.startswith("f"):
        return female if female is not None else 0.0
    if preference.startswith("m"):
        return male if male is not None else 0.0
    if preference.startswith("balanc") or preference.startswith("neutral"):
        return 1.0 - abs((female or 0.0) - (male or 0.0))
    return 0.0


def _percent(text: str, word: str) -> float | None:
    """The percentage attached to `word` in a split like "55% Female"."""
    match = re.search(rf"(\d+(?:\.\d+)?)%\s*{word}", text)
    if match:
        return float(match.group(1)) / 100.0
    if re.search(rf"\b{word}\b", text):
        return 0.5
    return None


def range_score(value: Any, wanted: Any) -> float:
    """How close a numeric value is to a requested band.

    1.0 inside the band, falling off outside it. A value is never excluded by
    this -- it is a preference about scale, and a company one size band away is
    a lead, not a non-lead.
    """
    if wanted in (None, "", []):
        return 0.0
    low, high = wanted if isinstance(wanted, (tuple, list)) and len(wanted) == 2 else (0, 0)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if low <= number <= high:
        return 1.0
    distance = low - number if number < low else number - high
    span = max(high - low, 1)
    return max(0.0, 1.0 - distance / span)


def overlap_score(value: Any, wanted: Any) -> float:
    """The share of the brief's terms the record's list contains.

    Used for a company's stated needs against the offer being sold: a partial
    overlap is a weaker match, not a rejection.
    """
    if not wanted:
        return 0.0
    if isinstance(value, (list, tuple, set)):
        have = {str(v).strip().casefold() for v in value}
    else:
        have = {part.strip().casefold() for part in str(value).split(",") if part.strip()}
    want = {str(v).strip().casefold() for v in wanted if str(v).strip()}
    if not have or not want:
        return 0.0
    return len(have & want) / len(want)


def floor_score(value: Any, wanted: Any) -> float:
    """A score for a magnitude the brief sets a floor on.

    `reach_ratio` is a proportion of followers, so the brief asks for a floor
    ("at least 20%") rather than a target. Anything at or above the floor scores
    1.0, which is the honest answer: the difference between 40% reach and 90%
    reach does not change which creator a brand should buy. Below the floor the
    score is the proportion of the floor met, so a creator at half the required
    reach is a worse match rather than a non-match.
    """
    if wanted in (None, "", 0) or wanted is False:
        return 0.0
    try:
        number = float(value)
        floor = float(wanted)
    except (TypeError, ValueError):
        return 0.0
    if floor <= 0:
        return 0.0
    return max(0.0, min(1.0, number / floor))


def expand_vertical(
    names: list[str],
    verticals: dict[str, tuple[str, ...]],
) -> list[str]:
    """Every industry the named verticals cover.

    A brief names a vertical ("logistics"), and the corpus has three logistics
    industries. Expanding turns the brief's wording into the column's values, so
    the filter selects the market rather than one label inside it.

    A name that is already an industry expands to its own vertical, so
    "freight tech" and "logistics" select the same set. A name that is neither
    is kept as-is, so an unknown industry matches nothing rather than silently
    matching everything.
    """
    if not names:
        return []
    reverse = {
        industry: vertical
        for vertical, industries in verticals.items()
        for industry in industries
    }
    out: set[str] = set()
    for name in names:
        key = str(name).strip()
        if not key:
            continue
        if key in verticals:
            out.update(verticals[key])
            continue
        vertical = reverse.get(key)
        if vertical is not None:
            out.update(verticals[vertical])
            continue
        out.add(key)
    return sorted(out)


def filter_hit(value: Any, wanted: Any, mode: str = "in") -> str | None:
    """Why a record satisfied a filter, or None if it did not.

    The same comparisons the SQL makes, so the explanation a reader sees is the
    one the database actually applied. A filter the user cannot see is a filter
    they cannot trust, and this is the proof that the shortlist is the one they
    asked for.
    """
    if mode == "range" and isinstance(wanted, (tuple, list)) and len(wanted) == 2:
        try:
            number = float(value)
            if float(wanted[0]) <= number <= float(wanted[1]):
                return f"{int(number)}"
        except (TypeError, ValueError):
            return None
        return None
    if isinstance(wanted, (list, tuple, set)):
        wanted_set = {str(w) for w in wanted}
        if isinstance(value, (list, tuple, set)):
            return str(value) if wanted_set & {str(v) for v in value} else None
        return str(value) if str(value) in wanted_set else None
    return str(value) if str(value) == str(wanted) else None


#: A budget bracket and the funding stages that can afford it, cheapest first.
#: The company corpus has no budget column, so the brief's budget is read
#: against what the company has raised. It is a stand-in, not a measurement, and
#: it is scored rather than filtered for that reason.
BUDGET_BANDS = {
    "under 10k": ("bootstrapped", "seed"),
    "10k-100k": ("seed", "Series A"),
    "100k-1m": ("Series A", "Series B"),
    "1m-10m": ("Series B", "Series C"),
    "over 10m": ("Series C", "public"),
}


def budget_score(value: Any, wanted: Any) -> float:
    """How well a company's funding stage fits the brief's budget bracket."""
    band = str(wanted or "").strip().lower()
    if not band:
        return 0.0
    stages = BUDGET_BANDS.get(band)
    if not stages:
        return 0.0
    stage = str(value or "").strip()
    if stage in stages:
        return 1.0
    # Adjacent brackets are a partial match: a Series A company is close enough
    # to a Series B budget to be worth a look.
    order = ["bootstrapped", "seed", "Series A", "Series B", "Series C", "public"]
    if stage not in order:
        return 0.0
    positions = [order.index(s) for s in stages]
    distance = min(abs(order.index(stage) - p) for p in positions)
    return 0.5 if distance == 1 else 0.0


def role_score(value: Any, wanted: Any) -> float:
    """How well a company's departments cover the roles a brief is selling to.

    A brief sells to "operations managers" and a company has an "operations"
    department. The two are not equal, but the words overlap, and a company with
    no matching department is a company with nobody to sell to.
    """
    if not wanted:
        return 0.0
    roles = [str(w).strip().casefold() for w in wanted if str(w).strip()]
    if not roles:
        return 0.0
    if isinstance(value, (list, tuple, set)):
        departments = [str(v).strip().casefold() for v in value]
    else:
        departments = [part.strip().casefold() for part in str(value).split(",") if part.strip()]
    if not departments:
        return 0.0
    hits = 0
    for role in roles:
        words = {w for w in role.replace("-", " ").split() if len(w) > 2}
        if not words:
            continue
        if any(words & set(department.split()) for department in departments):
            hits += 1
    return hits / len(roles)


#: Audience age bands, youngest first. The order is what "adjacent" means.
AGE_ORDER = [
    "13-17", "18-24", "25-34", "35-44", "45-54", "55-64", "65+",
]
