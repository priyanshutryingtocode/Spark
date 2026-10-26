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

    The user's free-text fields drive the primary retrieval channel. Reviewed
    product context is a separate soft retrieval signal; structured targeting
    fields drive filters and reranking.

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
    product_context: dict | None = None

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

    def intent_query_text(self) -> str:
        """The user's original search intent, excluding attached product context."""
        parts = [self.goal.strip()]
        if self.audience.strip():
            parts.append(f"Target audience: {self.audience.strip()}.")
        if self.vibe.strip():
            parts.append(f"Tone: {self.vibe.strip()}.")
        return " ".join(parts)

    def context_query_text(self) -> str:
        """A bounded retrieval query from reviewed, structured product context."""
        context = self.product_context or {}

        def clean(value: object, limit: int = 180) -> str:
            return " ".join(str(value or "").split())[:limit]

        parts = []
        for key, label in (("category", "Category"), ("target_audience", "Audience")):
            value = clean(context.get(key, ""))
            if value:
                parts.append(f"{label}: {value}")
        for key, label in (("use_cases", "Use cases"), ("differentiators", "Differentiators")):
            values = context.get(key, [])
            if isinstance(values, str):
                values = [values]
            if not isinstance(values, (list, tuple)):
                values = []
            values = [clean(value, 120) for value in values[:4] if clean(value, 120)]
            if values:
                parts.append(f"{label}: {', '.join(values)}")
        return "Product context. " + ". ".join(parts) if parts else ""

    def query_text(self) -> str:
        """Combined query retained for callers and single-query comparisons.

        This combines the user's words with reviewed product category and
        audience. Platform is omitted because it is already a hard filter.

        The structured fields are omitted for the same reason, and more strongly:
        "18-24" and "USA" embedded as words are nearly invisible next to a
        paragraph of topical language, and a filter that does not exclude
        anything should not be pretending to be part of the query.
        """
        parts = [self.intent_query_text()]
        context = self.product_context or {}
        if context.get("category"):
            parts.append(f"Product category: {context['category']}.")
        if context.get("target_audience"):
            parts.append(f"Product audience: {context['target_audience']}.")
        return " ".join(parts)

