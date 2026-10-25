"""Per-corpus summary numbers, in the same shape as `src.rubrics`: one spec
computes, labels, and decides completeness, so a key cannot be computed under one
name and displayed under another.

`values` are persisted and stay numeric; `cells` are shown and may be ratios.

Every metric runs over the joined (ranked, candidate) pairs, never the raw ranked
list: a stored run can hold a ranked entry whose candidate is gone, and counting
those lets a run report "4/5 strong fits" out of four candidates.
"""

from dataclasses import dataclass
from statistics import median
from typing import Any, Callable

#: The caveat that travels with the similarity cell. It is domain reasoning
#: about what cosine distance means, so it belongs beside the metric it
#: qualifies rather than in a component that may not be the one rendering it.
SIMILARITY_EXPLANATION = (
    "Mean cosine similarity between the brief's embedding and each shortlisted "
    "record's. This is an embedding distance, not a fit score: it is useful for "
    "comparing one brief against another, but it does not reliably rank records "
    "within a single shortlist. Use the strong-fit count for that."
)


def joined(candidates: list[dict], ranked: list[dict]) -> list[tuple[dict, dict]]:
    """(ranked entry, candidate) pairs whose candidate still exists. Takes
    persisted snapshot dicts, not record objects -- that is what a stored run
    holds, and what compare_service recomputes from.
    """
    by_id = {candidate["id"]: candidate for candidate in candidates}
    return [(entry, by_id[entry["id"]]) for entry in ranked if entry.get("id") in by_id]


# --- the values both corpora share -------------------------------------------

def _n_results(pairs: list[tuple[dict, dict]]) -> int:
    return len(pairs)


def _avg_match_pct(pairs: list[tuple[dict, dict]]) -> float:
    similarities = [
        float(record["similarity"])
        for _, record in pairs
        if record.get("similarity") is not None
    ]
    return round(100 * (sum(similarities) / len(similarities)), 1) if similarities else 0.0


def _n_strong(pairs: list[tuple[dict, dict]]) -> int:
    return sum(entry.get("fit") == "strong" for entry, _ in pairs)


def _n_weak(pairs: list[tuple[dict, dict]]) -> int:
    return sum(entry.get("fit") == "weak" for entry, _ in pairs)


# --- the values that genuinely differ ----------------------------------------

def _avg_engagement_pct(pairs: list[tuple[dict, dict]]) -> float | None:
    values = [float(record["engagement_pct"]) for _, record in pairs if record.get("engagement_pct") is not None]
    return sum(values) / len(values) if values else None


def _median_followers(pairs: list[tuple[dict, dict]]) -> int | None:
    values = [int(record["followers"]) for _, record in pairs if record.get("followers") is not None]
    return int(round(median(values))) if values else None


def _median_headcount(pairs: list[tuple[dict, dict]]) -> int | None:
    values = [int(record["headcount"]) for _, record in pairs if record.get("headcount") is not None]
    return int(round(median(values))) if values else None


# --- formatting --------------------------------------------------------------

def pct(value: Any) -> str:
    return f"{float(value):.1f}%"


def compact_count(value: Any) -> str:
    """1,200 -> 1K. Shared by reach and headcount; both read the same raw."""
    value = int(value or 0)
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"{round(value / 1_000)}K"
    return str(value)


@dataclass(frozen=True)
class SummaryCell:
    """One number as displayed. May combine several stored values."""

    key: str
    label: str
    caption: str
    display: Callable[[dict], str]
    #: Rendered in the signal colour as the strip's headline.
    primary: bool = False
    #: A caveat worth reaching on demand. The similarity number is the one metric
    #: here that can be misread as a fit score.
    explanation: str | None = None


@dataclass(frozen=True)
class SummarySpec:
    kind: str
    #: (stored key, compute) for everything persisted. Keys must stay numeric.
    values: tuple[tuple[str, Callable[[list[tuple[dict, dict]]], Any]], ...]
    #: Display order. Independent of `values` because a cell can be a ratio.
    cells: tuple[SummaryCell, ...]

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(key for key, _ in self.values)

    def compute(self, candidates: list[dict], ranked: list[dict]) -> dict:
        """Every stored value, computed once over one joined set."""
        pairs = joined(candidates, ranked)
        return {key: compute(pairs) for key, compute in self.values}

    def render_cells(self, values: dict) -> list[dict]:
        """Self-describing, so the client holds no second table of what each
        stored key is called.
        """
        out = []
        for cell in self.cells:
            item = {
                "key": cell.key,
                "label": cell.label,
                "caption": cell.caption,
                "value": cell.display(values),
            }
            if cell.primary:
                item["primary"] = True
            if cell.explanation:
                item["explanation"] = cell.explanation
            out.append(item)
        return out


_QUALITY = SummaryCell(
    key="n_results", label="Quality", caption="strong fits", primary=True,
    display=lambda v: f'{v.get("n_strong", 0)}/{v.get("n_results", 0)}',
)
_SIMILARITY = SummaryCell(
    key="avg_match_pct", label="Avg similarity", caption="cosine vs. brief",
    display=lambda v: pct(v.get("avg_match_pct", 0.0)),
    explanation=SIMILARITY_EXPLANATION,
)
_REVIEW = SummaryCell(
    key="n_weak", label="Needs review", caption="weak fits",
    display=lambda v: str(v.get("n_weak", 0)),
)

#: Key order matches the tuple SUMMARY_KEYS used to hold, so a stored creator
#: summary is complete under exactly the same test it passed before this file
#: existed. `compare_service` compares two summaries key by key.
_CREATOR_VALUES: tuple[tuple[str, Callable], ...] = (
    ("n_results", _n_results),
    ("avg_match_pct", _avg_match_pct),
    ("n_strong", _n_strong),
    ("n_weak", _n_weak),
    ("avg_engagement_pct", _avg_engagement_pct),
    ("median_followers", _median_followers),
)

_PROSPECT_VALUES: tuple[tuple[str, Callable], ...] = (
    ("n_results", _n_results),
    ("avg_match_pct", _avg_match_pct),
    ("n_strong", _n_strong),
    ("n_weak", _n_weak),
    ("median_headcount", _median_headcount),
)

CREATOR_SUMMARY = SummarySpec(
    kind="creator",
    values=_CREATOR_VALUES,
    cells=(
        _QUALITY,
        _SIMILARITY,
        SummaryCell(
            key="avg_engagement_pct", label="Avg engagement", caption="reach quality",
            display=lambda v: pct(v["avg_engagement_pct"]) if v.get("avg_engagement_pct") is not None else "—",
        ),
        SummaryCell(
            key="median_followers", label="Median reach", caption="followers",
            display=lambda v: compact_count(v["median_followers"]) if v.get("median_followers") is not None else "—",
        ),
        _REVIEW,
    ),
)

#: Same shape, one fewer cell. `avg_engagement_pct` has no company analogue --
#: nothing measures how engaged a company is -- and inventing one would be a
#: number with no meaning. `median_headcount` replaces `median_followers`
#: because scale is the dimension the rubric judges.
PROSPECT_SUMMARY = SummarySpec(
    kind="prospect",
    values=_PROSPECT_VALUES,
    cells=(
        _QUALITY,
        _SIMILARITY,
        SummaryCell(
            key="median_headcount", label="Median headcount", caption="employees",
            display=lambda v: compact_count(v["median_headcount"]) if v.get("median_headcount") is not None else "—",
        ),
        _REVIEW,
    ),
)

SUMMARIES: dict[str, SummarySpec] = {
    spec.kind: spec for spec in (CREATOR_SUMMARY, PROSPECT_SUMMARY)
}


def summary_spec(kind: str) -> SummarySpec:
    try:
        return SUMMARIES[kind]
    except KeyError:
        raise KeyError(f"no summary spec for corpus {kind!r}; known: {sorted(SUMMARIES)}") from None
