export type FitLevel = "strong" | "partial" | "weak" | "unknown";
export type RankingSource = "llm" | "llm_unverified" | "filled" | "fallback";
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type DatasetMode = "synthetic" | "real";

export interface Brief {
  goal: string;
  platform: string;
  audience: string;
  vibe: string;
  /** Structured, optional. The free-text fields above still drive the embedding;
   *  these drive the filters and the rerank. Each corpus reads only its own. */
  audience_age?: string[];
  audience_gender?: string;
  audience_countries?: string[];
  languages?: string[];
  min_reach_ratio?: number;
  target_industries?: string[];
  target_size?: [number, number] | null;
  target_countries?: string[];
  budget_band?: string;
  buyer_roles?: string[];
}

export interface MatchParams {
  top_k: number;
  top_n: number;
}

export interface MatchJob {
  job_id: string;
  status: JobStatus;
  stage: string;
  run_id: string | null;
  outcome: "match" | "no_results" | null;
  error: string | null;
  dataset?: DatasetMode;
}

/** Which searchable corpus a screen, run or candidate belongs to. Mirrors the
 *  backend's `CorpusKind`; the two are checked against each other in the backend
 *  suite rather than kept in sync by hand here. */
export type CorpusKind = "creator" | "prospect";

export interface Grounding {
  /** Key of a profile field on the stored record. */
  field: string;
  quote: string;
}

export interface CreatorSnapshot {
  id: number;
  /** Why this record matched the brief's structured fields. Empty when the brief
   *  asked for nothing structured, which is not a failure. */
  match_reasons?: string[];
  creator_key: string;
  handle: string;
  name: string;
  platform: string;
  city: string;
  language: string;
  followers: number | null;
  engagement_pct: number | null;
  average_views?: number | null;
  average_likes?: number | null;
  average_comments?: number | null;
  verified: boolean | null;
  posts_per_week?: number | null;
  account_age_years?: number | null;
  content_style: string;
  audience_age: string;
  audience_gender: string;
  brand_collaborations: string[];
  tags: string[];
  similarity: number | null;
  reach_ratio: number | null;
  sponsored_ratio: number | null;
  growth_trend: string;
  audience_top_countries: string[];
}

/** A company as stored on a run.
 *
 *  Deliberately a separate shape rather than an extension of CreatorSnapshot.
 *  They share three fields (`id`, `creator_key`, `tags`) and almost nothing
 *  else: a company has no followers, engagement or reach, and a creator has no
 *  headcount or funding stage. A common base would be three fields wide and
 *  would not stop a caller reading `candidate.followers` off a company.
 */
export interface ProspectSnapshot {
  id: number;
  match_reasons?: string[];
  creator_key: string;
  name: string;
  industry: string;
  headcount: number | null;
  city: string;
  country: string;
  description: string;
  website: string;
  founded_year: number | null;
  funding_stage: string;
  tags: string[];
  similarity: number | null;
  /** Inferred signals, parallel to a creator's content_style/audience_*. */
  seniority_mix: string;
  department_mix: string[];
  tech_stack: string[];
  buying_signals: string[];
  growth_trend: string;
  growth_rate: number | null;
  hiring_intensity: number | null;
  top_markets: string[];
}

/** One ranked row from either corpus.
 *
 *  Renamed from `RankedCreator` when the second corpus arrived, matching the
 *  backend's `RankedEntry`. `evidence` is optional because it is per-field
 *  verification against brief signals, and a company run has no such list -- the
 *  server omits the key rather than sending an empty one that would read as
 *  "every claim was checked and unsupported". */
export interface RankedEntry {
  id: number;
  creator_key: string;
  rank: number;
  fit: FitLevel;
  source: RankingSource;
  rationale: string;
  evidence?: string[];
  /** Citations the server verified against the stored profile. */
  grounding: Grounding[];
  /** Why the model did not rank this entry. Prefixed with "daily_quota:" when
   *  the free ranking budget is spent, which is a different situation from an
   *  outage and needs different advice. */
  fallback_reason: string;
}

export interface Warning {
  code: string;
  severity: "info" | "warning" | "error";
  message: string;
  details: Record<string, unknown>;
}

/** One summary number as displayed. `key` names the stored value it came from,
 *  which is not always a single value -- Quality is a ratio of two. */
export interface SummaryCell {
  key: string;
  label: string;
  caption: string;
  value: string;
  primary?: boolean;
  explanation?: string;
}

export interface RunSummary {
  /** Which corpus produced this summary. */
  kind?: string;
  dataset?: DatasetMode;
  /** Authoritative for display: each cell carries its own label and caption.
   *  Absent on summaries stored before cells existed, so the UI falls back to
   *  the flat keys below. */
  cells?: SummaryCell[];
  n_results: number;
  avg_match_pct: number;
  n_strong: number;
  n_weak: number;
  /** Creator-only. A company has no engagement rate, so it is absent rather
   *  than zero -- a 0.0 would read as "measured, and measured nothing". */
  avg_engagement_pct?: number | null;
  median_followers?: number | null;
  /** Prospect-only: the scale dimension that replaces follower count. */
  median_headcount?: number | null;
}

export interface RunListItem {
  run_id: string;
  created_at: string;
  brief: Brief;
  kind: CorpusKind;
  dataset?: DatasetMode;
  n_results: number;
  n_strong: number;
  has_warnings: boolean;
}

export interface RunListResponse {
  items: RunListItem[];
  next_cursor: string | null;
}

export interface RunDetail {
  run_id: string;
  created_at: string;
  brief: Brief;
  warnings: Warning[];
  summary: RunSummary;
  /** Which corpus this run searched. Read this before touching `candidates` --
   *  they are a union, and `kind` is what says which arm is in hand. */
  kind: CorpusKind;
  dataset?: DatasetMode;
  candidates: Array<CreatorSnapshot | ProspectSnapshot>;
  ranked: RankedEntry[];
}

export interface SavedMatch {
  saved_id: string;
  run_id: string;
  kind: CorpusKind;
  brief: Brief;
  candidate: CreatorSnapshot | ProspectSnapshot;
  ranked: RankedEntry;
  status: SavedMatchStatus;
  note: string;
  source_created_at: string;
  created_at: string;
  updated_at: string;
}

export type SavedMatchStatus = "to_review" | "contacted" | "in_conversation" | "partnered" | "passed";
export type MatchRating = "positive" | "negative";

export interface MatchFeedback {
  run_id: string;
  candidate_id: number;
  kind: CorpusKind;
  rating: MatchRating;
  reason: string;
  updated_at: string;
}

export interface LookalikeResponse {
  kind: CorpusKind;
  source_id: number;
  candidates: Array<CreatorSnapshot | ProspectSnapshot>;
}

export interface SavedMatchListResponse {
  items: SavedMatch[];
}

export interface Comparison {
  summary_a: RunSummary;
  summary_b: RunSummary;
  /** Renamed from `shared_creators`: a company is not a creator. `label` is the
   *  display name the server chose -- a creator's handle or a company's name --
   *  so the client never has to branch to label the overlap. */
  shared: Array<{ id: number; creator_key: string; label: string }>;
}

export interface Meta {
  dataset?: DatasetMode;
  platforms: string[];
  defaults: {
    goal: string;
    audience: string;
    vibe: string;
    top_k: number;
    top_n: number;
  };
  limits: {
    top_k_min: number;
    top_k_max: number;
    top_n_min: number;
    top_n_max: number;
    goal_min_length: number;
    goal_max_length: number;
    audience_max_length: number;
    vibe_max_length: number;
  };
  index: {
    status: "ready" | "unavailable" | "reindex_required";
    count: number;
  };
}
