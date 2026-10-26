from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import AliasChoices, BaseModel, Field, model_validator

from src import config

FitLevel = Literal["strong", "partial", "weak", "unknown"]
# `llm_unverified` is an LLM reason that survived with no citation the server
# could confirm. The UI marks it so a reader knows the claim is unsupported.
RankingSource = Literal["llm", "llm_unverified", "filled", "fallback"]
JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled"]
#: Which searchable corpus a request or run refers to. Duplicated here rather
#: than imported from `src.corpora` so the wire contract is readable on its own;
#: `src.corpora.KINDS` is asserted to cover it in tests.
CorpusKind = Literal["creator", "prospect"]
DatasetMode = Literal["synthetic", "real"]


class BriefPayload(BaseModel):
    """A free-text brand brief.

    The length floor lives on the write path (`_validate_brief`), not here, so
    runs stored before the move to free text - whose "niche" was sometimes a
    four-character vertical - still validate when they are read back. The
    `niche` alias keeps those records readable and is dropped on output.
    """

    goal: str = Field(
        default="",
        max_length=config.MAX_GOAL_LENGTH,
        validation_alias=AliasChoices("goal", "niche"),
    )
    platform: str = Field(default="Any", min_length=1, max_length=50)
    audience: str = Field(default="", max_length=config.AUDIENCE_MAX_LENGTH)
    vibe: str = Field(default="", max_length=config.VIBE_MAX_LENGTH)

    # Structured, optional. The free-text fields above still drive the embedding;
    # these drive the filters and the rerank. Each corpus reads only its own, so
    # one payload serves both without either vocabulary leaking into the other.
    audience_age: list[str] = Field(default_factory=list)
    audience_gender: str = ""
    audience_countries: list[str] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    min_reach_ratio: float = 0.0

    target_industries: list[str] = Field(default_factory=list)
    #: The company size band, as (min, max) headcount. None when unspecified.
    target_size: tuple[int, int] | None = None
    target_countries: list[str] = Field(default_factory=list)
    budget_band: str = ""
    buyer_roles: list[str] = Field(default_factory=list)

    def to_domain(self):
        from src.models import Brief

        return Brief(
            goal=self.goal,
            platform=self.platform,
            audience=self.audience,
            vibe=self.vibe,
            audience_age=list(self.audience_age),
            audience_gender=self.audience_gender,
            audience_countries=list(self.audience_countries),
            languages=list(self.languages),
            min_reach_ratio=self.min_reach_ratio,
            target_industries=list(self.target_industries),
            target_size=self.target_size,
            target_countries=list(self.target_countries),
            budget_band=self.budget_band,
            buyer_roles=list(self.buyer_roles),
        )


class MatchParams(BaseModel):
    top_k: int = Field(default=config.DEFAULT_TOP_K_RETRIEVAL, ge=1, le=config.MAX_TOP_K)
    top_n: int = Field(default=config.DEFAULT_TOP_N_RANKED, ge=1, le=config.MAX_TOP_K)

    @model_validator(mode="before")
    @classmethod
    def apply_default_top_n(cls, data):
        if isinstance(data, dict) and "top_n" not in data:
            top_k = data.get("top_k", config.DEFAULT_TOP_K_RETRIEVAL)
            if isinstance(top_k, int):
                return {**data, "top_n": min(config.DEFAULT_TOP_N_RANKED, top_k)}
        return data

    @model_validator(mode="after")
    def validate_shortlist_size(self):
        if self.top_n > self.top_k:
            raise ValueError("top_n cannot be greater than top_k")
        return self


class MatchJobRequest(BaseModel):
    brief: BriefPayload
    params: MatchParams = Field(default_factory=MatchParams)
    #: Which corpus to search. Defaults to "creator" so a client that predates the
    #: two panels -- and every stored run -- keeps working untouched.
    kind: CorpusKind = "creator"
    dataset: DatasetMode = config.DATASET_MODE


class MatchJobResponse(BaseModel):
    job_id: UUID
    status: JobStatus
    stage: str
    progress: dict[str, Any] = Field(default_factory=dict)
    run_id: UUID | None = None
    outcome: Literal["match", "no_results"] | None = None
    #: Echoed so a client polling a job knows which corpus the resulting run
    #: belongs to without having to fetch it. Carried through job state, since a
    #: job may still be queued when the panel is switched.
    kind: CorpusKind = "creator"
    dataset: DatasetMode = config.DATASET_MODE
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class CreatorSnapshot(BaseModel):
    """A creator as stored on a run.

    Fields 0-16 are what the profile states. From `content_style` down they are
    inferred signals, which live in their own table and refresh on a different
    cadence; they are flattened into the snapshot so a stored run stays a
    complete record of what was known at match time.
    """

    id: int
    creator_key: str
    handle: str
    name: str = ""
    platform: str
    city: str
    country: str = ""
    language: str = ""
    followers: int | None = None
    engagement_pct: float | None = None
    average_views: int | None = None
    average_likes: int | None = None
    average_comments: int | None = None
    verified: bool | None = None
    posts_per_week: float | None = None
    account_age_years: float | None = None
    #: Why this record matched the brief's structured fields. Empty when the
    #: brief asked for nothing structured, which is not a failure.
    match_reasons: list[str] = Field(default_factory=list)
    content_style: str = ""
    audience_age: str = ""
    audience_gender: str = ""
    audience_country: str = ""
    brand_collaborations: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    bio: str = ""
    similarity: float | None = None
    # Stored and displayable, but deliberately not citable: these are not in
    # corpus_text, so retrieval never searched on them and a reason must not
    # claim them.
    reach_ratio: float | None = None
    sponsored_ratio: float | None = None
    growth_trend: str = ""
    audience_top_countries: list[str] = Field(default_factory=list)


class ProspectSnapshot(BaseModel):
    """The stored shape of one company in a run.

    The mirror of `CreatorSnapshot`, and separate from it on purpose: `handle`,
    `platform`, `followers` and `engagement_pct` are required there and have no
    company meaning, so a single model covering both would either make a company
    carry a handle or make a creator's follower count optional. Two models means
    each is honest about its own record, at the cost of Phase 6 having to choose
    between them in the `RunDetail` response.

    Field order mirrors `CreatorSnapshot`: what the company states, then what was
    inferred about it, then similarity and the display-only ratios.
    """

    id: int
    creator_key: str
    name: str
    industry: str
    headcount: int | None = None
    city: str
    country: str = ""
    description: str = ""
    website: str = ""
    founded_year: int | None = None
    funding_stage: str = ""
    tags: list[str] = Field(default_factory=list)
    similarity: float | None = None
    match_reasons: list[str] = Field(default_factory=list)
    seniority_mix: str = ""
    department_mix: list[str] = Field(default_factory=list)
    tech_stack: list[str] = Field(default_factory=list)
    buying_signals: list[str] = Field(default_factory=list)
    growth_trend: str = ""
    # Display-only, per migration 009: not in corpus_text, so not citable.
    growth_rate: float | None = None
    hiring_intensity: float | None = None
    top_markets: list[str] = Field(default_factory=list)


class Grounding(BaseModel):
    """One claim a ranking reason rests on, and the profile field that backs it.

    `field` is a key of `src.ranking.GROUNDABLE_FIELDS` and `quote` is a
    verbatim substring of that field on the stored creator. Both are checked
    server-side before they reach this model, so a client can treat a grounding
    entry as fact rather than as a model's assertion.
    """

    field: str
    quote: str


class RankedEntry(BaseModel):
    """One ranked row, from either corpus.

    Neutral rather than `RankedCreator` plus a near-identical prospect twin:
    every field but `evidence` means the same thing for both, and two classes
    free to drift is the failure mode this refactor exists to remove.

    `evidence` is optional because it is not universal. It is per-field
    verification against brief signals, and `MatchSignals` is the creator's
    signal set. A company is matched on text similarity and has no signals to
    check, so a prospect row omits the key rather than shipping an empty list
    that reads as "checked, found nothing".

    `creator_key` keeps its name for both corpora until the stored-JSONB
    migration that renames it; changing it now would orphan every existing run.
    """
    id: int
    creator_key: str
    rank: int
    fit: FitLevel
    source: RankingSource
    rationale: str = ""
    evidence: list[str] | None = None
    grounding: list[Grounding] = Field(default_factory=list)
    # Why the model did not rank this entry, when `source` is a fallback. Kept
    # on the record rather than only in the log: a run re-read later needs to be
    # able to say whether ranking was skipped for a spent quota or an outage,
    # because those call for different advice.
    fallback_reason: str = ""


class Warning(BaseModel):
    code: str
    severity: Literal["info", "warning", "error"]
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class SummaryCell(BaseModel):
    """One summary number with its own label, so the client renders what arrives
    rather than holding a second table of what each key is called."""

    key: str
    label: str
    caption: str
    value: str
    #: None rather than False, so exclude_none can drop it. False is a real
    #: value that exclude_none keeps, which would leave every non-primary cell
    #: carrying "primary": false in the stored JSONB for no reader.
    primary: bool | None = None
    explanation: str | None = None


class RunSummary(BaseModel):
    """A run's summary, plus the cells that describe it.

    `cells` is the display surface and is authoritative. The flat numeric keys
    stay for stored-run compatibility and for anything computing over them, but
    `avg_engagement_pct` and `median_followers` are optional because a company
    has neither: `median_headcount` replaces one and nothing replaces the other.
    """

    kind: str = "creator"
    dataset: DatasetMode = config.DATASET_MODE
    cells: list[SummaryCell] = Field(default_factory=list)
    n_results: int
    avg_match_pct: float
    n_strong: int
    n_weak: int
    avg_engagement_pct: float | None = None
    median_followers: int | None = None
    median_headcount: int | None = None


class RunListItem(BaseModel):
    run_id: UUID
    created_at: datetime
    brief: BriefPayload
    #: Which corpus produced it. Defaults to "creator" because the summary of a
    #: run stored before migration 010 has no kind to read.
    kind: CorpusKind = "creator"
    dataset: DatasetMode = config.DATASET_MODE
    n_results: int
    n_strong: int
    has_warnings: bool


class RunListResponse(BaseModel):
    items: list[RunListItem]
    next_cursor: str | None = None


class RunDetail(BaseModel):
    run_id: UUID
    created_at: datetime
    brief: BriefPayload
    params: MatchParams
    warnings: list[Warning] = Field(default_factory=list)
    summary: RunSummary
    kind: CorpusKind = "creator"
    dataset: DatasetMode = config.DATASET_MODE
    #: A union, not a base type. The two snapshots share only `id`,
    #: `creator_key` and `similarity` -- a company has no followers and a creator
    #: has no headcount -- so a common base would be three fields wide and would
    #: not stop a client reading `candidate.followers` off a company. The `kind`
    #: above is what tells a client which arm it is holding.
    candidates: list[CreatorSnapshot | ProspectSnapshot]
    ranked: list[RankedEntry]


class SaveMatchRequest(BaseModel):
    run_id: UUID
    candidate_id: int = Field(ge=0)


class SavedMatchResponse(BaseModel):
    saved_id: UUID
    run_id: UUID
    kind: CorpusKind
    dataset: DatasetMode = config.DATASET_MODE
    brief: BriefPayload
    candidate: dict[str, Any]
    ranked: dict[str, Any]
    status: Literal["to_review", "contacted", "in_conversation", "partnered", "passed"] = "to_review"
    note: str = ""
    source_created_at: datetime
    created_at: datetime
    updated_at: datetime


class SavedMatchListResponse(BaseModel):
    items: list[SavedMatchResponse]


class SavedMatchUpdateRequest(BaseModel):
    status: Literal["to_review", "contacted", "in_conversation", "partnered", "passed"] | None = None
    note: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def require_update(self):
        if not ({"status", "note"} & self.model_fields_set):
            raise ValueError("Provide a status or note to update.")
        return self


class MatchFeedbackRequest(BaseModel):
    run_id: UUID
    candidate_id: int = Field(ge=0)
    rating: Literal["positive", "negative"]
    reason: str = Field(default="", max_length=1000)


class MatchFeedbackResponse(BaseModel):
    run_id: UUID
    candidate_id: int
    kind: CorpusKind
    rating: Literal["positive", "negative"]
    reason: str
    updated_at: datetime


class LookalikeRequest(BaseModel):
    kind: CorpusKind
    dataset: DatasetMode = config.DATASET_MODE
    candidate_id: int = Field(ge=0)
    top_k: int = Field(default=5, ge=1, le=10)


class LookalikeResponse(BaseModel):
    kind: CorpusKind
    dataset: DatasetMode = config.DATASET_MODE
    source_id: int
    candidates: list[dict[str, Any]]


class ComparisonRequest(BaseModel):
    run_id_a: UUID
    run_id_b: UUID


class CandidateReference(BaseModel):
    """A candidate that appears in both compared runs.

    Renamed from `CreatorReference` and `handle` became `label` because a company
    has no handle. `creator_key` keeps its name for both corpora until the stored
    JSONB migration that renames it.
    """
    id: int
    creator_key: str
    label: str


class ComparisonResponse(BaseModel):
    run_ids: list[UUID]
    summary_a: RunSummary
    summary_b: RunSummary
    #: Renamed from `shared_creators`: a company is not a creator, and the field
    #: lists whatever both runs happened to surface.
    shared: list[CandidateReference] = Field(default_factory=list)


class MetaDefaults(BaseModel):
    """Prefill values the Search form starts from.

    Typed rather than `dict[str, Any]`. That was the defect that let a missing
    `goal` key ship: the frontend type promised it, the backend silently omitted
    it, and neither side noticed because a dict validates nothing.
    """

    goal: str = ""
    audience: str = ""
    vibe: str = ""
    top_k: int = config.DEFAULT_TOP_K_RETRIEVAL
    top_n: int = config.DEFAULT_TOP_N_RANKED


class MetaLimits(BaseModel):
    top_k_min: int
    top_k_max: int
    top_n_min: int
    top_n_max: int
    goal_min_length: int
    goal_max_length: int
    audience_max_length: int
    vibe_max_length: int


class MetaIndex(BaseModel):
    status: Literal["ready", "unavailable", "reindex_required"]
    count: int
    embedding_model: str
    embed_dimensions: int
    memory_rss_mb: float | None = None


class MetaRanking(BaseModel):
    model: str
    fit_levels: list[FitLevel]


class MetaResponse(BaseModel):
    dataset: DatasetMode = config.DATASET_MODE
    platforms: list[str]
    defaults: MetaDefaults
    limits: MetaLimits
    index: MetaIndex
    ranking: MetaRanking
