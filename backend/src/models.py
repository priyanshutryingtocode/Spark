"""The query side of the pipeline, shared by every corpus.

The searchable records live in `src.corpora`, one pair of dataclasses per corpus,
because those describe a corpus specifically. `Brief` describes the thing being
searched *for*, which does not change when a second corpus is added, so it stays
here. A corpus model moving in beside it is what made this split necessary.
"""

from dataclasses import dataclass, field


@dataclass
class Brief:
    """A search request.

    The free-text fields are what the user types and what drives the embedding.
    The structured fields are optional and drive the filters and the rerank
    instead -- a brief with none of them set still works, because the corpus's
    own rubric judges the semantic match.

    Each corpus reads only its own structured fields, so one class serving two
    corpora does not mean one corpus's vocabulary leaking into the other. A
    creator brief's `audience_age` is an audience estimate; a company brief's
    `target_size_min` is a fact about the company. They are separate fields for
    that reason, and each corpus declares which of them it reads.
    """

    goal: str
    platform: str
    audience: str = ""
    vibe: str = ""

    # --- creator brief: who should see this
    audience_age: list[str] = field(default_factory=list)
    audience_gender: str = ""
    audience_countries: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    #: Minimum reach as a share of followers, 0-1. 0 means "not specified".
    min_reach_ratio: float = 0.0

    # --- company brief: who should buy this
    target_industries: list[str] = field(default_factory=list)
    #: The company size band, as (min, max) headcount. None when unspecified.
    target_size: tuple[int, int] | None = None
    target_countries: list[str] = field(default_factory=list)
    budget_band: str = ""
    buyer_roles: list[str] = field(default_factory=list)

    def query_text(self) -> str:
        """Text embedded as the retrieval query (the RAG 'query').

        This is the brand's own words, not a templated scaffold. Platform is
        omitted because it is already a hard metadata filter, so repeating it
        here would only dilute the topical signal.

        The structured fields are omitted for the same reason, and more strongly:
        "18-24" and "USA" embedded as words are nearly invisible next to a
        paragraph of topical language, and a filter that does not exclude
        anything should not be pretending to be part of the query.
        """
        parts = [self.goal.strip()]
        if self.audience.strip():
            parts.append(f"Target audience: {self.audience.strip()}.")
        if self.vibe.strip():
            parts.append(f"Tone: {self.vibe.strip()}.")
        return " ".join(parts)

