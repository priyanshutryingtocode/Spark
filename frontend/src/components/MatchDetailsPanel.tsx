import type { CreatorSnapshot, CorpusKind, MatchRating, ProspectSnapshot, RankedEntry } from "../types";
import { CandidateAvatar, GroundingList, formatCount } from "./resultShared";
import { MoreLikeThis } from "./MoreLikeThis";

const fitLabel = {
  strong: "Strong fit",
  partial: "Partial fit",
  weak: "Weak fit",
  unknown: "Fit not assessed",
} as const;

const sourceLabel = {
  llm: "AI ranked",
  llm_unverified: "Reason not verified",
  filled: "Filled from retrieval",
  fallback: "Retrieval fallback",
} as const;

export function MatchDetailsPanel({
  kind,
  candidate,
  entry,
  saved = false,
  saving = false,
  saveError,
  onSave,
  feedbackRating,
  feedbackSaving = false,
  feedbackError,
  onFeedback,
  titleId = "match-details-title",
}: {
  kind: CorpusKind;
  candidate: CreatorSnapshot | ProspectSnapshot;
  entry: RankedEntry;
  saved?: boolean;
  saving?: boolean;
  saveError?: string | null;
  onSave?: () => void;
  feedbackRating?: MatchRating | null;
  feedbackSaving?: boolean;
  feedbackError?: string | null;
  onFeedback?: (rating: MatchRating) => void;
  titleId?: string;
}) {
  const title = kind === "creator"
    ? (candidate as CreatorSnapshot).name || (candidate as CreatorSnapshot).handle
    : (candidate as ProspectSnapshot).name;
  const subtitle = kind === "creator"
    ? [(candidate as CreatorSnapshot).handle, (candidate as CreatorSnapshot).platform].filter(Boolean).join(" · ")
    : [
      (candidate as ProspectSnapshot).industry,
      [(candidate as ProspectSnapshot).city, (candidate as ProspectSnapshot).country].filter(Boolean).join(", "),
    ].filter(Boolean).join(" · ");
  const facts = kind === "creator"
    ? creatorFacts(candidate as CreatorSnapshot)
    : companyFacts(candidate as ProspectSnapshot);
  const reasons = candidate.match_reasons ?? [];

  return (
    <aside className="match-details-panel" aria-labelledby={titleId}>
      <p className="eyebrow">Match profile · #{String(entry.rank).padStart(2, "0")}</p>
      <div className="match-details-identity">
        <CandidateAvatar name={title} kind={kind} />
        <div>
          <h2 id={titleId}>{title}</h2>
          <p>{subtitle}</p>
        </div>
      </div>

      <div className="match-details-fit">
        <span className={`fit-mark fit-mark-${entry.fit}`} aria-hidden="true" />
        <strong>{fitLabel[entry.fit]}</strong>
        <span>{sourceLabel[entry.source]}</span>
      </div>

      {onSave && (
        <div className="match-save-action">
          <button className="btn btn-secondary" type="button" disabled={saved || saving} onClick={onSave}>
            {saved ? "Saved to shortlist" : saving ? "Saving..." : "Save to shortlist"}
          </button>
          {saveError && <p role="alert">{saveError}</p>}
        </div>
      )}

      {onFeedback && (
        <section className="match-feedback" aria-label="Match feedback">
          <span>Was this a useful match?</span>
          <div className="match-feedback-actions">
            <button
              className="btn btn-secondary"
              type="button"
              aria-pressed={feedbackRating === "positive"}
              disabled={feedbackSaving}
              onClick={() => onFeedback("positive")}
            >
              Good fit
            </button>
            <button
              className="btn btn-secondary"
              type="button"
              aria-pressed={feedbackRating === "negative"}
              disabled={feedbackSaving}
              onClick={() => onFeedback("negative")}
            >
              Poor fit
            </button>
          </div>
          {feedbackRating && <small role="status">Thanks, your feedback is recorded.</small>}
          {feedbackError && <small role="alert">{feedbackError}</small>}
        </section>
      )}

      {entry.rationale && (
        <section className="match-details-section">
          <h3>Why it matched</h3>
          <p>{entry.rationale}</p>
        </section>
      )}

      {kind === "prospect" && (candidate as ProspectSnapshot).description && (
        <section className="match-details-section">
          <h3>Company overview</h3>
          <p>{(candidate as ProspectSnapshot).description}</p>
        </section>
      )}

      {reasons.length > 0 && (
        <section className="match-details-section">
          <h3>Requirements met</h3>
          <ul className="match-details-tags">
            {reasons.map((reason) => <li key={reason}>{reason}</li>)}
          </ul>
        </section>
      )}

      <section className="match-details-section">
        <h3>Profile</h3>
        <dl className="match-facts">
          {facts.map(([label, value]) => (
            <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
          ))}
          {candidate.similarity !== null && (
            <div><dt>Semantic similarity</dt><dd>{(candidate.similarity * 100).toFixed(1)}%</dd></div>
          )}
        </dl>
        <p className="match-details-caption">Similarity compares profile text with your brief; it is not a fit score.</p>
      </section>

      <MoreLikeThis key={`${kind}:${candidate.id}`} kind={kind} candidateId={candidate.id} />

      {entry.grounding.length > 0 && (
        <section className="match-details-section">
          <h3>Supporting evidence</h3>
          <GroundingList grounding={entry.grounding} kind={kind} />
        </section>
      )}

      {entry.evidence && entry.evidence.length > 0 && (
        <section className="match-details-section">
          <h3>Audience evidence</h3>
          <ul className="match-details-evidence">
            {entry.evidence.map((item) => <li key={item}>{item}</li>)}
          </ul>
        </section>
      )}
    </aside>
  );
}

function creatorFacts(creator: CreatorSnapshot): Array<[string, string]> {
  const facts: Array<[string, string]> = [
    ["Platform", creator.platform],
    ["Followers", formatCount(creator.followers)],
    ["Engagement", `${creator.engagement_pct.toFixed(1)}%`],
    ["Reach rate", `${Math.round(creator.reach_ratio * 100)}%`],
  ];
  if (creator.city) facts.push(["Location", creator.city]);
  if (creator.content_style) facts.push(["Content style", creator.content_style]);
  if (creator.audience_age) facts.push(["Audience age", creator.audience_age]);
  if (creator.audience_gender) facts.push(["Audience gender", creator.audience_gender]);
  if (creator.audience_top_countries.length) facts.push(["Top audience markets", creator.audience_top_countries.join(", ")]);
  if (creator.growth_trend) facts.push(["Growth", creator.growth_trend]);
  if (creator.tags.length) facts.push(["Topics", creator.tags.join(", ")]);
  return facts;
}

function companyFacts(company: ProspectSnapshot): Array<[string, string]> {
  const facts: Array<[string, string]> = [
    ["Industry", company.industry],
    ["Team size", formatCount(company.headcount)],
  ];
  const location = [company.city, company.country].filter(Boolean).join(", ");
  if (location) facts.push(["Location", location]);
  if (company.founded_year) facts.push(["Founded", String(company.founded_year)]);
  if (company.funding_stage) facts.push(["Funding stage", company.funding_stage]);
  if (company.growth_trend) facts.push(["Growth", company.growth_trend]);
  if (company.department_mix.length) facts.push(["Teams", company.department_mix.join(", ")]);
  if (company.tech_stack.length) facts.push(["Technology", company.tech_stack.join(", ")]);
  if (company.buying_signals.length) facts.push(["Buying signals", company.buying_signals.join(", ")]);
  if (company.top_markets.length) facts.push(["Top markets", company.top_markets.join(", ")]);
  if (company.website) facts.push(["Website", company.website]);
  return facts;
}
