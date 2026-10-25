import type { CorpusKind, FitLevel, Grounding, RankingSource } from "../types";

/** How much of a result row to show.
 *
 *  `full` is the shortlist as the reader gets it from a search: every field the
 *  card can carry, because there is one shortlist and the job is to judge it.
 *
 *  `compact` is for the Compare page, where the same row appears twice and the
 *  reader is looking for what changed rather than for what each entry is. A
 *  full card shown twice is mostly repetition -- the citation labels, the
 *  evidence, the profile details and the reach bar are the same kind of
 *  information in both columns, and at that volume they bury the comparison.
 *  Everything the compact row drops is still on the run's own card. */
export type CardVariant = "full" | "compact";

export const SIMILARITY_EXPLANATION =
  "Mean cosine similarity between the brief's embedding and each shortlisted "
  + "creator's. This is an embedding distance, not a fit score: it is useful for "
  + "comparing one brief against another, but it does not reliably rank creators "
  + "within a single shortlist. Use the strong-fit count for that.";

/* Keyed by the union, so a new fit level fails to compile until it is labelled. */
const fitLabels: Record<FitLevel, string> = {
  strong: "Strong",
  partial: "Partial",
  weak: "Weak",
  unknown: "Unknown",
};

/** Only rows that did not come back through the normal ranked path need to say
 *  so; labelling every row just adds noise. `llm_unverified` is called out
 *  because the model gave a reason and the server could not confirm any part
 *  of it, which a reader needs to know. */
const fallbackSourceLabels: Record<Exclude<RankingSource, "llm">, string> = {
  filled: "Filled from retrieval",
  fallback: "Retrieval fallback",
  llm_unverified: "Reason not confirmed",
};

/** Must match `QUOTA_REASON_TAG` in backend/src/ranking.py. A spent daily quota
 *  needs different advice from an outage, so the server tags it and the reason
 *  is persisted on the run; the tag is a code, not something to show a reader. */
const DAILY_QUOTA_TAG = "daily_quota";

function displayReason(reason: string): string {
  return reason.startsWith(`${DAILY_QUOTA_TAG}:`)
    ? reason.slice(DAILY_QUOTA_TAG.length + 1).trim()
    : reason;
}

/** Field keys the API can ground a claim in, per corpus. These mirror each
 *  rubric's `groundable_fields`, and the two sets barely overlap -- sharing one
 *  map is what labelled a company's citations "Audience gender". Unknown fields
 *  fall through to the raw key rather than to nothing. */
const groundingLabels: Record<CorpusKind, Record<string, string>> = {
  creator: {
    tags: "Topics",
    bio: "Bio",
    content_style: "Content style",
    audience_age: "Audience age",
    audience_gender: "Audience gender",
    audience_country: "Audience country",
    brand_collaborations: "Brand partners",
    platform: "Platform",
    followers: "Followers",
    engagement_rate: "Engagement",
  },
  prospect: {
    tags: "Topics",
    industry: "Industry",
    headcount: "Headcount",
    country: "Country",
    description: "Description",
    seniority_mix: "Seniority mix",
    department_mix: "Departments",
    growth_trend: "Growth trend",
    tech_stack: "Tech stack",
    buying_signals: "Buying signals",
  },
};

export function GroundingList({ grounding, kind }: { grounding: Grounding[]; kind: CorpusKind }) {
  if (grounding.length === 0) return null;
  const labels = groundingLabels[kind];
  return (
    <ul className="result-grounding">
      {grounding.map((claim) => (
        <li key={`${claim.field}:${claim.quote}`}>
          <span className="grounding-field">{labels[claim.field] ?? claim.field}</span>
          <span className="grounding-quote">{claim.quote}</span>
        </li>
      ))}
    </ul>
  );
}

export function ResultRank({ rank }: { rank: number }) {
  return (
    <div className="result-rank"><span>#</span>{String(rank).padStart(2, "0")}</div>
  );
}

/** Initials are a neutral placeholder until profile image URLs are available. */
export function CandidateAvatar({ name, kind }: { name: string; kind: "creator" | "prospect" }) {
  const words = name.trim().split(/\s+/).filter(Boolean);
  const initials = words.length > 1
    ? `${words[0][0]}${words[words.length - 1][0]}`
    : (words[0] ?? "?").slice(0, 2);
  return (
    <span className={`result-avatar result-avatar-${kind}`} aria-hidden="true">
      {initials.toUpperCase()}
    </span>
  );
}

/** Fit verdict, cosine similarity, and any reason the row fell back.
 *
 *  Identical for both corpora: the ranking contract and its failure modes do not
 *  vary by what was searched, and the similarity caveat is corpus-neutral by
 *  design (the server sends it in both summaries).
 *
 *  `compact` folds the fallback label and its reason onto one line and holds the
 *  block to two lines either way. The Compare page sets a fixed height on its
 *  rows so the two columns line up against each other, and a row that grew a
 *  third line because it fell back would push everything below it out of
 *  alignment in its own column only. The reason is still there, just
 *  truncated, and the full text is on the title. */
export function ResultFit({
  fit, similarity, source, fallbackReason, goal, compact = false,
}: {
  fit: FitLevel;
  similarity: number | null;
  source: RankingSource;
  fallbackReason: string;
  goal: string;
  compact?: boolean;
}) {
  const shown = similarity === null ? "—" : `${(similarity * 100).toFixed(1)}%`;
  return (
    <div className={`result-fit ${compact ? "result-fit-compact" : ""}`}>
      <span className="result-fit-line">
        <span className={`fit-mark fit-mark-${fit}`} aria-hidden="true" />
        <span className="fit-label">{fitLabels[fit]}</span>
        {/* title is a mouse affordance only; aria-label is what a screen
         *  reader announces, and it has to name the metric rather than leave
         *  a bare percentage next to a fit verdict. */}
        <span className="fit-match" title={SIMILARITY_EXPLANATION}>
          {/* aria-label on a <span> with no role is not exposed -- the name is
            dropped, so this read as a bare percentage again. The visible
            number is hidden from AT and the full phrase carries it instead,
            which also avoids announcing the same value twice. */}
          <span aria-hidden="true">{shown}</span>
          <span className="visually-hidden">{`Cosine similarity to your brief: ${shown}`}</span>
        </span>
      </span>
      {compact ? (
        /* Label and reason on one line: the label keeps the warning colour and
           the reason is truncated rather than dropped. */
        <span className="source-compact">
          {source !== "llm" && <span className="source-label">{fallbackSourceLabels[source]}</span>}
          {fallbackReason && (
            <span className="source-detail" title={displayReason(fallbackReason)}>
              {displayReason(fallbackReason)}
            </span>
          )}
        </span>
      ) : (
        <>
          {source !== "llm" && <span className="source-label">{fallbackSourceLabels[source]}</span>}
          {/* The server persists why a row fell back -- a metered daily ranking
           *  cap needs different advice from a truncated response -- and that
           *  reason was reaching this component and being dropped. */}
          {fallbackReason && (
            <span className="source-detail">{displayReason(fallbackReason)}</span>
          )}
        </>
      )}
      <span className="visually-hidden">{`Ranked for ${goal}`}</span>
    </div>
  );
}

export function ResultRationale({
  rationale, children, compact = false,
}: {
  rationale: string;
  children: React.ReactNode;
  /** One line instead of a paragraph. Compare's rows are fixed height so the
   *  two columns line up, and a rationale that wrapped to two lines on one side
   *  would break that alignment for every row below it. */
  compact?: boolean;
}) {
  return (
    <div className={`result-rationale ${compact ? "result-rationale-compact" : ""}`}>
      {rationale && <p title={compact ? rationale : undefined}>{rationale}</p>}
      {children}
    </div>
  );
}

export function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="result-metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

/** A proportion shown as a bar.
 *
 *  Cosine similarity and growth_rate are excluded by their callers: creators sit
 *  in a narrow band and companies can shrink, so rescaling either would inflate
 *  it. `reach_ratio` does exceed 1.0 (18% of generated creators), so both the
 *  bar and the number are clamped -- an uncapped "200%" read as a data error. */
export function ProportionBar({
  label, value, description,
}: {
  label: string;
  value: number;
  /** Spoken after the percentage, e.g. "of followers" -- what the bar means. */
  description: string;
}) {
  if (!(value > 0)) return null;
  const shown = Math.min(value, 1);
  return (
    <div className="result-metric result-metric-wide">
      <span>{label}</span>
      <span className="micro-bar" aria-hidden="true">
        <span className="micro-bar-fill" style={{ inlineSize: `${shown * 100}%` }} />
      </span>
      <strong>
        {Math.round(shown * 100)}%<span className="visually-hidden"> {description}</span>
      </strong>
    </div>
  );
}

/** Compact a count: 940, 24K, 1.2M. */
export function formatCount(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${Math.round(value / 1_000)}K`;
  return String(value);
}
