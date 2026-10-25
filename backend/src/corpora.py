"""Corpus declarations: what a searchable record *is*.

A corpus is one searchable body of records and the text each record is embedded
as. `Influencer`/`CreatorSignals` live here rather than in `models.py` because
they describe one corpus specifically, while `models.Brief` describes the query
and is shared by every corpus. A second corpus gets its pair of dataclasses here
too, so the corpus-specific surface stays in one place and `models.py` does not
accumulate one model per corpus beside the one type they all share.

Nothing in this module may import a generator: the API server imports it to read
`/meta` and run retrieval, and the generators pull in faker, which has no
business in a server process. `src.platforms` states the same rule for the same
reason, and `src.slotting` holds the primitives both sides need.
"""

import hashlib
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

import numpy as np

from . import config
from .rubrics import CREATOR_RUBRIC, PROSPECT_RUBRIC, Rubric
from .scoring import (
    FilterField, RerankField, budget_score, floor_score,
    gender_score, role_score,
)


@dataclass
class CreatorIdentity:
    """Optional person or organization grouping for independently matched accounts."""

    id: int
    identity_key: str
    display_name: str


@dataclass(frozen=True)
class CreatorSourceRecord:
    """One provider's identity for an account and its original payload."""

    provider: str
    external_account_id: str
    profile_url: str = ""
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CreatorMetricSnapshot:
    """Account performance measured over a stated window at a known time."""

    account_id: int
    provider: str
    observed_at: datetime
    period_days: int
    followers: int | None = None
    average_views: int | None = None
    average_likes: int | None = None
    average_comments: int | None = None
    engagement_rate: float | None = None
    posts_per_week: float | None = None
    sample_size: int | None = None


@dataclass(frozen=True)
class CreatorAudienceSnapshot:
    """Provider-estimated audience distributions, kept separate per account."""

    account_id: int
    provider: str
    observed_at: datetime
    age_distribution: dict[str, float] = field(default_factory=dict)
    gender_distribution: dict[str, float] = field(default_factory=dict)
    country_distribution: dict[str, float] = field(default_factory=dict)
    language_distribution: dict[str, float] = field(default_factory=dict)
    sample_size: int | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class CompanySourceRecord:
    """Provider identifier and original payload for one company."""

    provider: str
    external_company_id: str
    profile_url: str = ""
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CompanyMetricSnapshot:
    """Dated operating metrics; unknown values stay null."""

    company_id: int
    provider: str
    observed_at: datetime
    headcount: int | None = None
    headcount_low: int | None = None
    headcount_high: int | None = None
    headcount_growth_rate: float | None = None
    revenue_low: float | None = None
    revenue_high: float | None = None
    revenue_period: str | None = None
    revenue_currency: str | None = None
    monthly_web_visits: int | None = None
    open_roles: int | None = None
    sample_size: int | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class CompanyFundingRound:
    """A funding event, distinct from a company's current funding stage."""

    company_id: int
    provider: str
    external_round_id: str
    round_type: str
    announced_at: datetime | None = None
    amount: float | None = None
    currency: str | None = None
    post_money_valuation: float | None = None
    investors: list[str] = field(default_factory=list)
    source_url: str = ""
    raw_payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class CreatorSignals:
    """Inferred, third-party characteristics, kept out of the searchable row.

    `influencers` holds what a creator's own profile states: handle, reach,
    topics, bio. Everything here is an estimate made *about* that profile by an
    analytics provider, so it belongs in its own table with its own lifecycle.
    The split matters for two reasons: a signal can be refreshed without
    re-embedding a profile, and a reason can say "inferred audience 25-34"
    rather than implying the creator declared it.

    Fields are set in the same order the ranking prompt may cite them, and
    `Influencer.corpus_text` still reads them, so moving them between tables
    did not change the embedded text -- which is what keeps every cached
    vector valid across the split.
    """

    creator_id: int
    content_style: str = ""
    audience_age: str = ""
    audience_gender: str = ""
    audience_country: str = ""
    brand_collaborations: list[str] = field(default_factory=list)
    # views / followers. The honest measure of whether reach is real: a
    # follower count can be large while actual reach stays small.
    reach_ratio: float | None = 0.0
    sponsored_ratio: float | None = 0.0
    growth_trend: str = ""
    audience_top_countries: list[str] = field(default_factory=list)
    source_provider: str = "synthetic"
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float | None = None
    age_distribution: dict[str, float] = field(default_factory=dict)
    gender_distribution: dict[str, float] = field(default_factory=dict)
    country_distribution: dict[str, float] = field(default_factory=dict)
    language_distribution: dict[str, float] = field(default_factory=dict)


@dataclass
class Influencer:
    id: int
    handle: str
    platform: str
    city: str
    followers: int | None
    engagement: float | None
    tags: list = field(default_factory=list)
    bio: str = ""
    embedding: np.ndarray = None
    similarity: float | None = None
    name: str = ""
    country: str = ""
    language: str = ""
    average_views: int | None = 0
    average_likes: int | None = 0
    average_comments: int | None = 0
    verified: bool | None = False
    posts_per_week: float | None = 0
    account_age_years: float | None = 0
    content_style: str = ""
    audience_age: str = ""
    audience_gender: str = ""
    audience_country: str = ""
    brand_collaborations: list[str] = field(default_factory=list)
    reach_ratio: float | None = 0.0
    sponsored_ratio: float | None = 0.0
    growth_trend: str = ""
    audience_top_countries: list[str] = field(default_factory=list)
    audience_age_distribution: dict[str, float] = field(default_factory=dict)
    audience_gender_distribution: dict[str, float] = field(default_factory=dict)
    audience_country_distribution: dict[str, float] = field(default_factory=dict)
    audience_language_distribution: dict[str, float] = field(default_factory=dict)
    # A creator identity is optional. Search and ranking always operate on this
    # account record, because one person can run channels for different audiences.
    identity_id: int | None = None
    identity_key: str = ""
    identity_name: str = ""
    profile_url: str = ""
    source_records: list[CreatorSourceRecord] = field(default_factory=list)
    metric_snapshots: list[CreatorMetricSnapshot] = field(default_factory=list)
    audience_snapshots: list[CreatorAudienceSnapshot] = field(default_factory=list)

    def signals(self) -> CreatorSignals:
        """The signal row for this creator, as stored."""
        return CreatorSignals(
            creator_id=self.id,
            content_style=self.content_style,
            audience_age=self.audience_age,
            audience_gender=self.audience_gender,
            audience_country=self.audience_country,
            brand_collaborations=list(self.brand_collaborations),
            reach_ratio=self.reach_ratio,
            sponsored_ratio=self.sponsored_ratio,
            growth_trend=self.growth_trend,
            audience_top_countries=list(self.audience_top_countries),
            source_provider=(self.source_records[0].provider if self.source_records else "synthetic"),
            observed_at=(self.source_records[0].observed_at if self.source_records else datetime.now(timezone.utc)),
            age_distribution=dict(self.audience_age_distribution),
            gender_distribution=dict(self.audience_gender_distribution),
            country_distribution=dict(self.audience_country_distribution),
            language_distribution=dict(self.audience_language_distribution),
        )

    def identity(self) -> CreatorIdentity | None:
        if self.identity_id is None or not self.identity_key or not self.identity_name:
            return None
        return CreatorIdentity(self.identity_id, self.identity_key, self.identity_name)

    def metrics_snapshot(self) -> CreatorMetricSnapshot:
        source = self.source_records[0] if self.source_records else None
        return CreatorMetricSnapshot(
            account_id=self.id,
            provider=source.provider if source else "synthetic",
            observed_at=source.observed_at if source else datetime.now(timezone.utc),
            period_days=30,
            followers=self.followers,
            average_views=self.average_views,
            average_likes=self.average_likes,
            average_comments=self.average_comments,
            engagement_rate=self.engagement,
            posts_per_week=self.posts_per_week,
        )

    def audience_snapshot(self) -> CreatorAudienceSnapshot:
        signal = self.signals()
        return CreatorAudienceSnapshot(
            account_id=self.id,
            provider=signal.source_provider,
            observed_at=signal.observed_at,
            age_distribution=signal.age_distribution,
            gender_distribution=signal.gender_distribution,
            country_distribution=signal.country_distribution,
            language_distribution=signal.language_distribution,
        )

    def corpus_text(self) -> str:
        """The text this creator is embedded as, and the text a reason may cite.

        This is the single source of truth for what a profile "says". It
        deliberately includes every field the ranking model is allowed to cite
        as evidence, so retrieval can match on it and a grounded reason can
        quote it. Changing this invalidates every cached vector.

        The signal fields are emitted in `corpus_text` from this row either way,
        which is what let those columns move to `creator_signals` without
        invalidating a single cached vector. Retrieval reads them through the
        LEFT JOIN in `vector_store.search`, not through an accessor.
        """
        facts = [
            f"Creator {self.handle} on {self.platform}, based in {self.city}, {self.country}.",
            f"Topics: {', '.join(self.tags)}.",
        ]
        if self.content_style:
            facts.append(f"Content style: {self.content_style}.")
        audience = ", ".join(p for p in (self.audience_age, self.audience_gender, self.audience_country) if p)
        if audience:
            facts.append(f"Audience: {audience}.")
        if self.brand_collaborations:
            facts.append(f"Past brand partners: {', '.join(self.brand_collaborations)}.")
        if self.bio:
            facts.append(self.bio)
        return " ".join(facts)


# The legacy name is kept while matching, API snapshots, and tests migrate.
# `Influencer` rows are account-level records; identity is only an optional link.
CreatorAccount = Influencer

@dataclass
class ProspectSignals:
    """Inferred, third-party characteristics of a company.

    The prospect-side mirror of `CreatorSignals`, with the same reasoning: the
    searchable row holds what the company says, and everything here is an
    estimate made *about* it, so it belongs in its own table with its own
    lifecycle. A signal can be refreshed without re-embedding the company, and a
    reason can say "inferred growth" rather than implying the company declared it.

    Fields are set in the same order the ranking prompt may cite them, and
    `Prospect.corpus_text` reads the same subset it does for creators.
    """

    prospect_id: int
    seniority_mix: str = ""
    department_mix: list[str] = field(default_factory=list)
    # What the company already runs. The prospect analogue of a creator's past
    # brand partners: it says who can currently reach this account.
    tech_stack: list[str] = field(default_factory=list)
    # What the company appears to be trying to solve. The analogue of
    # content_style, and the field a sales-oriented match should key on.
    buying_signals: list[str] = field(default_factory=list)
    growth_trend: str = ""
    # Annual headcount growth. Derived from the row rather than copied, so a
    # reader cannot catch the row contradicting its own headcount.
    growth_rate: float | None = 0.0
    hiring_intensity: float | None = 0.0
    top_markets: list[str] = field(default_factory=list)
    source_provider: str = "synthetic"
    observed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float | None = None


@dataclass
class Prospect:
    id: int
    name: str
    industry: str
    headcount: int | None
    city: str
    country: str
    description: str
    tags: list = field(default_factory=list)
    website: str = ""
    founded_year: int | None = 0
    funding_stage: str = ""
    embedding: np.ndarray = None
    similarity: float | None = None
    seniority_mix: str = ""
    department_mix: list[str] = field(default_factory=list)
    tech_stack: list[str] = field(default_factory=list)
    buying_signals: list[str] = field(default_factory=list)
    growth_trend: str = ""
    growth_rate: float | None = 0.0
    hiring_intensity: float | None = 0.0
    top_markets: list[str] = field(default_factory=list)
    profile_url: str = ""
    source_records: list[CompanySourceRecord] = field(default_factory=list)
    metric_snapshots: list[CompanyMetricSnapshot] = field(default_factory=list)
    funding_rounds: list[CompanyFundingRound] = field(default_factory=list)
    source_provider: str = "synthetic"
    observed_at: datetime | None = None
    confidence: float | None = None

    def signals(self) -> ProspectSignals:
        """The signal row for this prospect, as stored."""
        source = self.source_records[0] if self.source_records else None
        return ProspectSignals(
            prospect_id=self.id,
            seniority_mix=self.seniority_mix,
            department_mix=list(self.department_mix),
            tech_stack=list(self.tech_stack),
            buying_signals=list(self.buying_signals),
            growth_trend=self.growth_trend,
            growth_rate=self.growth_rate,
            hiring_intensity=self.hiring_intensity,
            top_markets=list(self.top_markets),
            source_provider=source.provider if source else self.source_provider,
            observed_at=source.observed_at if source else self.observed_at or datetime.now(timezone.utc),
            confidence=self.confidence,
        )

    def metrics_snapshot(self) -> CompanyMetricSnapshot:
        source = self.source_records[0] if self.source_records else None
        return CompanyMetricSnapshot(
            company_id=self.id,
            provider=source.provider if source else self.source_provider,
            observed_at=source.observed_at if source else self.observed_at or datetime.now(timezone.utc),
            headcount=self.headcount,
            headcount_growth_rate=self.growth_rate,
            confidence=self.confidence,
        )

    def corpus_text(self) -> str:
        """The text this company is embedded as, and the text a reason may cite.

        Frozen by migration 009's header comment: changing this invalidates every
        cached vector, so the format is decided once, here.

        `growth_trend` is emitted, which is the one deliberate divergence from
        `Influencer.corpus_text` -- for creators growth_trend is display-only,
        because for a prospect it is a primary ICP-fit signal. `growth_rate`,
        `hiring_intensity` and `top_markets` stay out on both sides, matching the
        creator split: they are derivable from what is already here.
        """
        facts = [
            f"Company {self.name}, a {self.industry} company of "
            f"{self.headcount} employees, based in {self.city}, {self.country}.",
            f"Topics: {', '.join(self.tags)}.",
        ]
        if self.seniority_mix:
            facts.append(f"Seniority mix: {self.seniority_mix}.")
        if self.department_mix:
            facts.append(f"Departments: {', '.join(self.department_mix)}.")
        if self.growth_trend:
            facts.append(f"Growth: {self.growth_trend}.")
        if self.tech_stack:
            facts.append(f"Tools in use: {', '.join(self.tech_stack)}.")
        if self.buying_signals:
            facts.append(f"Signals it needs: {', '.join(self.buying_signals)}.")
        if self.description:
            facts.append(self.description)
        return " ".join(facts)


@dataclass(frozen=True)
class Corpus:
    """Everything retrieval needs to know about one searchable body of records.

    `vector_store.search` used to take a table name and hardcode the signals
    table, its join key and its whole column list in SQL. Those are what this
    carries. `rubric` is set by both corpora; one without it cannot be ranked.
    """

    kind: str
    table: str
    signals_table: str
    signals_key: str
    #: EVERY selected expression must be aliased: psycopg's dict_row keys on the
    #: column name, so an unaliased COALESCE(...) comes back as "coalesce" --
    #: sixteen of them, colliding on one key.
    search_sql: str
    row_builder: Callable[[Mapping[str, Any]], Any]
    #: Searchable table columns, INSERT order, conflict key first. The column
    #: list, VALUES placeholders and ON CONFLICT SET are all derived from this
    #: one tuple, because writing all three by hand is how a dropped column
    #: becomes a silent column shift rather than a syntax error.
    write_columns: tuple[str, ...]
    #: record -> {column: value} for `write_columns`, including the storage
    #: columns, which is what keeps the writer corpus-agnostic.
    row_from_record: Callable[[Any], Mapping[str, Any]]
    #: The signals table's columns, conflict key first.
    signal_columns: tuple[str, ...]
    #: The facet a caller may filter on, if any.
    facet_column: str | None = None
    #: The vertical each of this corpus's industries belongs to, as
    #: {vertical: its industries}. A filter on `vertical_column` expands a named
    #: vertical to those industries.
    verticals: dict[str, tuple[str, ...]] = field(default_factory=dict)
    #: The column `verticals` applies to, if any.
    vertical_column: str | None = None
    #: Structured filters this corpus supports, in the order they are relaxed
    #: when a filtered search comes back empty. Only for attributes a record
    #: states exactly -- see src.scoring for why.
    filters: tuple[FilterField, ...] = ()
    #: Rerank inputs, for attributes a third party estimates. These reorder the
    #: retrieved set; they never exclude from it.
    rerank: tuple[RerankField, ...] = ()
    def supports_facet(self) -> bool:
        """Whether this corpus has a facet to offer in /meta."""
        return self.facet_column is not None

    def filters_by_facet(self) -> bool:
        """Whether a facet value becomes a WHERE clause.

        Retrieval used to test `facet_is_hard_filter` here while brief validation
        tested `facet_column`, which disagree for any corpus that has a facet but
        does not filter on it.
        """
        return self.facet_column is not None and self.facet_is_hard_filter

    #: False for prospects: industry is text the ranker judges, and a hard filter
    #: would hide the cross-industry leads that are often the answer.
    facet_is_hard_filter: bool = False
    #: How this corpus is ranked, or None when it has no rubric of its own. The
    #: evaluator reads this to decide whether to score a ranked list at all, so a
    #: corpus without one is left on retrieval order rather than scored with
    #: another corpus's rules. Doubles as the "can be reranked" flag, which is
    #: why it is a field and not a separate boolean.
    rubric: Rubric | None = None
    real_data: bool = False


def content_hash(text: str) -> str:
    """Hash of the exact text a vector was built from.

    Lives here rather than in vector_store because it is a property of
    corpus_text, and the write path needs it without knowing which corpus it is
    writing.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


CREATOR_WRITE_COLUMNS = (
    "id", "handle", "platform", "city", "followers", "engagement", "tags", "bio",
    "embedding", "embed_model", "content_hash", "identity_id", "profile_url",
    "name", "country", "language",
    "average_views", "average_likes", "average_comments", "verified",
    "posts_per_week", "account_age_years",
)

CREATOR_SIGNAL_COLUMNS = (
    "creator_id", "content_style", "audience_age", "audience_gender",
    "audience_country", "brand_collaborations", "reach_ratio", "sponsored_ratio",
    "growth_trend", "audience_top_countries", "source_provider", "observed_at", "confidence",
)

PROSPECT_WRITE_COLUMNS = (
    "id", "name", "industry", "headcount", "city", "country", "description",
    "tags", "website", "founded_year", "funding_stage",
    "embedding", "embed_model", "content_hash", "profile_url",
)

PROSPECT_SIGNAL_COLUMNS = (
    "prospect_id", "seniority_mix", "department_mix", "tech_stack",
    "buying_signals", "growth_trend", "growth_rate", "hiring_intensity",
    "top_markets", "source_provider", "observed_at", "confidence",
)


def _creator_record(inf: Influencer) -> dict[str, Any]:
    return {
        "id": inf.id, "handle": inf.handle, "platform": inf.platform, "city": inf.city,
        "followers": inf.followers, "engagement": inf.engagement,
        "tags": inf.tags, "bio": inf.bio, "embedding": inf.embedding,
        "embed_model": config.EMBED_MODEL, "content_hash": content_hash(inf.corpus_text()),
        "identity_id": inf.identity_id, "profile_url": inf.profile_url or None,
        "name": inf.name, "country": inf.country, "language": inf.language,
        "average_views": inf.average_views, "average_likes": inf.average_likes,
        "average_comments": inf.average_comments, "verified": inf.verified,
        "posts_per_week": inf.posts_per_week, "account_age_years": inf.account_age_years,
    }


def _creator_signal_row(signals: CreatorSignals) -> dict[str, Any]:
    return {
        "creator_id": signals.creator_id, "content_style": signals.content_style,
        "audience_age": signals.audience_age, "audience_gender": signals.audience_gender,
        "audience_country": signals.audience_country,
        "brand_collaborations": signals.brand_collaborations,
        "reach_ratio": signals.reach_ratio, "sponsored_ratio": signals.sponsored_ratio,
        "growth_trend": signals.growth_trend,
        "audience_top_countries": signals.audience_top_countries,
        "source_provider": signals.source_provider,
        "observed_at": signals.observed_at,
        "confidence": signals.confidence,
    }


def _prospect_record(pr: Prospect) -> dict[str, Any]:
    return {
        "id": pr.id, "name": pr.name, "industry": pr.industry, "headcount": pr.headcount,
        "city": pr.city, "country": pr.country, "description": pr.description,
        "tags": pr.tags, "website": pr.website, "founded_year": pr.founded_year,
        "funding_stage": pr.funding_stage, "embedding": pr.embedding,
        "embed_model": config.EMBED_MODEL, "content_hash": content_hash(pr.corpus_text()),
        "profile_url": pr.profile_url or None,
    }


def _prospect_signal_row(signals: ProspectSignals) -> dict[str, Any]:
    return {
        "prospect_id": signals.prospect_id, "seniority_mix": signals.seniority_mix,
        "department_mix": signals.department_mix, "tech_stack": signals.tech_stack,
        "buying_signals": signals.buying_signals, "growth_trend": signals.growth_trend,
        "growth_rate": signals.growth_rate, "hiring_intensity": signals.hiring_intensity,
        "top_markets": signals.top_markets,
        "source_provider": signals.source_provider,
        "observed_at": signals.observed_at,
        "confidence": signals.confidence,
    }


def _creator_row(row: Mapping[str, Any]) -> Influencer:
    return Influencer(
        id=row["id"], handle=row["handle"], platform=row["platform"], city=row["city"] or "",
        followers=row["followers"],
        engagement=float(row["engagement"]) if row["engagement"] is not None else None,
        tags=list(row["tags"] or []), bio=row["bio"] or "",
        similarity=float(row["similarity"]),
        name=row["name"] or "", country=row["country"] or "", language=row["language"] or "",
        average_views=row["average_views"], average_likes=row["average_likes"],
        average_comments=row["average_comments"], verified=row["verified"],
        posts_per_week=row["posts_per_week"], account_age_years=row["account_age_years"],
        identity_id=row["identity_id"], profile_url=row["profile_url"] or "",
        identity_key=row.get("identity_key") or "",
        identity_name=row.get("identity_name") or "",
        content_style=row["content_style"] or "", audience_age=row["audience_age"] or "",
        audience_gender=row["audience_gender"] or "", audience_country=row["audience_country"] or "",
        brand_collaborations=list(row["brand_collaborations"] or []),
        reach_ratio=float(row["reach_ratio"]) if row["reach_ratio"] is not None else None,
        sponsored_ratio=float(row["sponsored_ratio"]) if row["sponsored_ratio"] is not None else None,
        growth_trend=row["growth_trend"] or "",
        audience_top_countries=list(row["audience_top_countries"] or []),
    )


def _prospect_row(row: Mapping[str, Any]) -> Prospect:
    return Prospect(
        id=row["id"], name=row["name"], industry=row["industry"] or "",
        headcount=row["headcount"], city=row["city"] or "", country=row["country"] or "",
        description=row["description"] or "", tags=list(row["tags"] or []),
        website=row["website"], founded_year=row["founded_year"],
        profile_url=row.get("profile_url") or "",
        source_provider=row.get("source_provider") or "synthetic",
        observed_at=row.get("observed_at"), confidence=row.get("confidence"),
        funding_stage=row["funding_stage"],
        similarity=float(row["similarity"]),
        seniority_mix=row["seniority_mix"] or "",
        department_mix=list(row["department_mix"] or []),
        tech_stack=list(row["tech_stack"] or []),
        buying_signals=list(row["buying_signals"] or []),
        growth_trend=row["growth_trend"] or "",
        growth_rate=float(row["growth_rate"]) if row["growth_rate"] is not None else None,
        hiring_intensity=float(row["hiring_intensity"]) if row["hiring_intensity"] is not None else None,
        top_markets=list(row["top_markets"] or []),
    )


#: The verticals a company's industry can belong to, and the industries each
#: one covers.
#:
#: A brief names a vertical -- "logistics" -- not one of the three industries
#: inside it, so the industry filter expands a named vertical to its industries.
#: Naming any industry in the vertical selects the whole vertical, because a
#: seller who says "freight tech" means the logistics market.
PROSPECT_VERTICALS: dict[str, tuple[str, ...]] = {
    "b2b_saas": ("B2B SaaS", "developer tools", "business intelligence"),
    "fintech": ("fintech", "payments", "accounting software"),
    "healthtech": ("healthtech", "clinical software", "medical devices"),
    "ecommerce": ("e-commerce", "retail", "consumer goods"),
    "logistics": ("logistics", "supply chain", "freight tech"),
    "construction": ("construction", "real estate", "property management"),
    "professional_services": ("consulting", "legal services", "accounting services"),
    "edtech": ("education technology", "corporate training", "edtech platform"),
}

#: The reverse lookup, so a name can be resolved from either side.
PROSPECT_INDUSTRY_VERTICAL: dict[str, str] = {
    industry: vertical
    for vertical, industries in PROSPECT_VERTICALS.items()
    for industry in industries
}


CREATORS = Corpus(
    kind="creator",
    table="influencers",
    signals_table="creator_signals",
    signals_key="creator_id",
    facet_column="platform",
    facet_is_hard_filter=True,
    # Discrete requirements, excluded rather than merely preferred. The corpus
    # is large enough to afford each: 424 creators in the 18-24 band, 650 in the
    # five biggest audience countries, 295 in both. They are read from the
    # signals table because that is where the inferred fields live.
    filters=(
        FilterField(column="s.audience_age", brief_field="audience_age", label="Audience age", drop_order=2),
        FilterField(column="s.audience_country", brief_field="audience_countries", label="Audience country", drop_order=1),
        FilterField(column="language", brief_field="languages", label="Language", drop_order=3),
    ),
    # Preferences and continuous magnitudes. A gender split is a degree of
    # lean, not a kind, and reach is a floor on a proportion: both reorder.
    rerank=(
        RerankField(
            column="audience_gender", brief_field="audience_gender", label="Audience gender",
            scorer=gender_score, weight=1.0,
        ),
        RerankField(
            column="reach_ratio", brief_field="min_reach_ratio", label="Reach",
            scorer=floor_score, weight=1.0,
        ),
    ),
    rubric=CREATOR_RUBRIC,
    row_builder=_creator_row,
    write_columns=CREATOR_WRITE_COLUMNS,
    row_from_record=_creator_record,
    signal_columns=CREATOR_SIGNAL_COLUMNS,
    search_sql="""
        SELECT i.id, i.identity_id, ci.identity_key, ci.display_name AS identity_name,
               i.profile_url, i.handle, i.platform, i.city, i.followers, i.engagement,
               i.tags, i.bio,
               1 - (i.embedding <=> %s) AS similarity,
               COALESCE(i.name, '') AS name,
               COALESCE(i.country, '') AS country, COALESCE(i.language, '') AS language,
               COALESCE(i.average_views, 0) AS average_views,
               COALESCE(i.average_likes, 0) AS average_likes,
               COALESCE(i.average_comments, 0) AS average_comments,
               COALESCE(i.verified, FALSE) AS verified,
               COALESCE(i.posts_per_week, 0) AS posts_per_week,
               COALESCE(i.account_age_years, 0) AS account_age_years,
               COALESCE(s.content_style, '') AS content_style,
               COALESCE(s.audience_age, '') AS audience_age,
               COALESCE(s.audience_gender, '') AS audience_gender,
               COALESCE(s.audience_country, '') AS audience_country,
               COALESCE(s.brand_collaborations, ARRAY[]::TEXT[]) AS brand_collaborations,
               COALESCE(s.reach_ratio, 0) AS reach_ratio,
               COALESCE(s.sponsored_ratio, 0) AS sponsored_ratio,
               COALESCE(s.growth_trend, '') AS growth_trend,
               COALESCE(s.audience_top_countries, ARRAY[]::TEXT[]) AS audience_top_countries
        FROM {table} AS i
        LEFT JOIN {signals_table} AS s ON s.{signals_key} = i.id
        LEFT JOIN creator_identities AS ci ON ci.id = i.identity_id
    """,
)

PROSPECTS = Corpus(
    kind="prospect",
    verticals=PROSPECT_VERTICALS,
    vertical_column="industry",
    # A company states its industry, its size and where it is, so a brief that
    # names them can exclude the rest. The corpus is small enough that the three
    # together can match nothing, which is what the filter floor is for.
    # Relaxed in this order: size, then industry, then country. Size is a band
    # over scale and the most adjustable; the industry is the ICP's core; and
    # the country is the constraint a seller least wants dropped, so it is the
    # last to go.
    filters=(
        FilterField(column="headcount", brief_field="target_size", label="Size", mode="range", drop_order=1),
        FilterField(column="industry", brief_field="target_industries", label="Industry", drop_order=2),
        FilterField(column="country", brief_field="target_countries", label="Country", drop_order=3),
    ),
    # Who decides, and what they can afford. Both are estimates -- the
    # departments are inferred and the budget is read against the funding stage --
    # so both reorder rather than exclude.
    rerank=(
        RerankField(
            column="department_mix", brief_field="buyer_roles", label="Departments",
            scorer=role_score, weight=1.0,
        ),
        RerankField(
            column="funding_stage", brief_field="budget_band", label="Budget",
            scorer=budget_score, weight=1.0,
        ),
    ),
    table="prospects",
    signals_table="prospect_signals",
    signals_key="prospect_id",
    # No facet. Industry is deliberately not a filter: see Corpus.facet_is_hard_filter.
    facet_column=None,
    facet_is_hard_filter=False,
    rubric=PROSPECT_RUBRIC,
    row_builder=_prospect_row,
    write_columns=PROSPECT_WRITE_COLUMNS,
    row_from_record=_prospect_record,
    signal_columns=PROSPECT_SIGNAL_COLUMNS,
    search_sql="""
        SELECT i.id, i.name, i.industry, i.headcount, i.city, i.country, i.profile_url,
               i.description, i.tags,
               COALESCE(i.website, '') AS website,
               COALESCE(i.founded_year, 0) AS founded_year,
               COALESCE(i.funding_stage, '') AS funding_stage,
               1 - (i.embedding <=> %s) AS similarity,
               COALESCE(s.seniority_mix, '') AS seniority_mix,
               COALESCE(s.department_mix, ARRAY[]::TEXT[]) AS department_mix,
               COALESCE(s.tech_stack, ARRAY[]::TEXT[]) AS tech_stack,
               COALESCE(s.buying_signals, ARRAY[]::TEXT[]) AS buying_signals,
               COALESCE(s.growth_trend, '') AS growth_trend,
               COALESCE(s.growth_rate, 0) AS growth_rate,
               COALESCE(s.hiring_intensity, 0) AS hiring_intensity,
               COALESCE(s.top_markets, ARRAY[]::TEXT[]) AS top_markets,
               COALESCE(s.source_provider, 'synthetic') AS source_provider,
               s.observed_at AS observed_at, s.confidence AS confidence
        FROM {table} AS i
        LEFT JOIN {signals_table} AS s ON s.{signals_key} = i.id
    """,
)

REAL_CREATORS = replace(
    CREATORS,
    table="real_creator_accounts",
    signals_table="real_creator_signals",
    search_sql=(
        CREATORS.search_sql
        .replace("LEFT JOIN creator_identities AS ci", "LEFT JOIN real_creator_identities AS ci")
        .replace("COALESCE(i.average_views, 0)", "i.average_views")
        .replace("COALESCE(i.average_likes, 0)", "i.average_likes")
        .replace("COALESCE(i.average_comments, 0)", "i.average_comments")
        .replace("COALESCE(i.verified, FALSE)", "i.verified")
        .replace("COALESCE(i.posts_per_week, 0)", "i.posts_per_week")
        .replace("COALESCE(i.account_age_years, 0)", "i.account_age_years")
        .replace("COALESCE(s.reach_ratio, 0)", "s.reach_ratio")
        .replace("COALESCE(s.sponsored_ratio, 0)", "s.sponsored_ratio")
    ),
    real_data=True,
)

REAL_PROSPECTS = replace(
    PROSPECTS,
    table="real_companies",
    signals_table="real_company_signals",
    signals_key="company_id",
    search_sql=PROSPECTS.search_sql
        .replace("i.profile_url", "i.website AS profile_url")
        .replace("COALESCE(i.founded_year, 0)", "i.founded_year")
        .replace("COALESCE(s.growth_rate, 0)", "s.growth_rate")
        .replace("COALESCE(s.hiring_intensity, 0)", "s.hiring_intensity")
        .replace("COALESCE(s.source_provider, 'synthetic')", "COALESCE(s.source_provider, 'public_source')"),
    real_data=True,
)

SYNTHETIC_KINDS: dict[str, Corpus] = {c.kind: c for c in (CREATORS, PROSPECTS)}
REAL_KINDS: dict[str, Corpus] = {c.kind: c for c in (REAL_CREATORS, REAL_PROSPECTS)}
DATASET_MODES = {"synthetic": SYNTHETIC_KINDS, "real": REAL_KINDS}
ALL_KINDS = tuple((*SYNTHETIC_KINDS.values(), *REAL_KINDS.values()))
KINDS: dict[str, Corpus] = REAL_KINDS if config.DATASET_MODE == "real" else SYNTHETIC_KINDS

#: What a request means when it does not say. Every run stored before the panels
#: existed is a creator run, so this is also the migration 010 column default.
DEFAULT_KIND = "creator"
assert DEFAULT_KIND in KINDS, "the default corpus must exist"


def get_corpus(kind: str, dataset: str | None = None) -> Corpus:
    """The corpus for `kind`. Raises rather than defaulting: a typo that silently
    returned creators for a request that asked for prospects is the worse failure.
    """
    selected = dataset or config.DATASET_MODE
    corpora = DATASET_MODES.get(selected)
    if corpora is None:
        raise ValueError(f"unknown dataset mode {selected!r}; expected 'synthetic' or 'real'")
    try:
        return corpora[kind]
    except KeyError:
        raise KeyError(f"unknown corpus kind {kind!r}; known: {sorted(corpora)}") from None


def dataset_for_record(record: Mapping[str, Any]) -> str:
    """Read the dataset persisted with a run, falling back for older runs."""
    dataset = record.get("dataset") or (record.get("summary") or {}).get("dataset") or config.DATASET_MODE
    if dataset not in DATASET_MODES:
        raise KeyError(f"run has unknown dataset mode {dataset!r}; known: {sorted(DATASET_MODES)}")
    return dataset


def kind_for_record(record: Mapping[str, Any]) -> str:
    """Which corpus a stored run belongs to. Four readers once asked separately
    and three omitted the summary fallback, so a record with an empty `kind` and a
    prospect summary was a creator run to the API and a company to the CSV.
    """
    kind = record.get("kind") or (record.get("summary") or {}).get("kind") or DEFAULT_KIND
    if kind not in KINDS:
        raise KeyError(f"run has unknown corpus kind {kind!r}; known: {sorted(KINDS)}")
    return kind


def corpus_for_record(record: Mapping[str, Any]) -> Corpus:
    return get_corpus(kind_for_record(record), dataset_for_record(record))
