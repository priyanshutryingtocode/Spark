import type { Brief, CreatorSnapshot, RankedEntry } from "../types";
import {
  GroundingList,
  CandidateAvatar,
  Metric,
  ProportionBar,
  ResultFit,
  ResultRank,
  ResultRationale,
  formatCount,
} from "./resultShared";
import type { CardVariant } from "./resultShared";

export function CreatorResultCard({
  creator, entry, brief, highlight = false, selected = false, onSelect, variant = "full",
}: {
  creator: CreatorSnapshot;
  entry: RankedEntry;
  brief: Brief;
  highlight?: boolean;
  selected?: boolean;
  onSelect?: () => void;
  variant?: CardVariant;
}) {
  // Platform is a hard filter on the run, so naming it on every row of a
  // filtered shortlist is noise. On "Any" it is the only thing saying which
  // platform a creator is on, so it is shown only there.
  const showPlatform = brief.platform === "Any";
  // content_style is in the subtitle, so it is kept out of the details below --
  // the same de-duplication that removed reach_ratio from both.
  const subtitle = [showPlatform ? creator.platform : "", creator.city, creator.content_style]
    .filter(Boolean)
    .join(" · ");
  const details = detailPairs(creator);
  const compact = variant === "compact";
  const reasons = creator.match_reasons ?? [];

  return (
    <article
      className={["result-row", compact && "result-row-compact", highlight && "result-row-highlight", selected && "result-row-selected"].filter(Boolean).join(" ")}
      aria-label={`Match ${entry.rank} for ${brief.goal}`}
    >
      <ResultRank rank={entry.rank} />
      <div className="result-identity">
        <div className="result-identity-heading">
          <CandidateAvatar name={creator.name || creator.handle} kind="creator" />
          <div className="result-title-stack">
            <h3>{creator.name || creator.handle}</h3>
            {creator.name && <span className="result-display-name">{creator.handle}</span>}
          </div>
          {creator.verified && <span className="verified-mark">Verified</span>}
        </div>
        {/* The compact row holds the identity to two lines -- the name and one
            meta line -- because the two columns are only comparable if their
            rows line up. The filter reasons share that meta line with the
            subline rather than taking one of their own, and are clipped if
            they will not fit; the full card carries all of them. */}
        {compact ? (
          <div className="result-meta-line">
            {subtitle && <p className="result-subline">{subtitle}</p>}
            {reasons.length > 0 && (
              <span className="match-reasons-inline">
                {reasons.map((reason) => <span className="match-reason" key={reason}>{reason}</span>)}
              </span>
            )}
          </div>
        ) : (
          <>
            {subtitle && <p className="result-subline">{subtitle}</p>}
            {/* The topic tags are dropped in the compact variant: the grounding
                list carries the same topics with a label, and on the Compare
                page that list is dropped too, so keeping both would put a line
                of tokens in the row for no gain. */}
            {creator.tags.length > 0 && <p className="result-tags">{creator.tags.slice(0, 3).join("  ·  ")}</p>}
            {reasons.length > 0 && (
              <ul className="match-reasons">
                {reasons.map((reason) => (
                  <li className="match-reason" key={reason}>{reason}</li>
                ))}
              </ul>
            )}
          </>
        )}
      </div>
      <ResultFit
        fit={entry.fit}
        similarity={creator.similarity}
        source={entry.source}
        fallbackReason={entry.fallback_reason}
        goal={brief.goal}
        compact={compact}
      />
      <div className="result-metrics">
        <Metric label="Followers" value={formatCount(creator.followers)} />
        <Metric label="Engagement" value={creator.engagement_pct === null ? "—" : `${creator.engagement_pct.toFixed(1)}%`} />
        {/* Reach as a share of followers separates real reach from a large
         *  follower count, which is the number a brand is most often misled by.
         *  It was buried under "Profile details" -- the one check the row
         *  actually exists to answer, hidden behind a click. Spans both columns
         *  so the two existing metrics keep their place in the grid. */}
        {!compact && (
          <ProportionBar
            label="Reach rate"
            value={creator.reach_ratio}
            description="of followers"
          />
        )}
      </div>
      <ResultRationale rationale={entry.rationale} compact={compact}>
        {!compact && (
          <>
            <GroundingList grounding={entry.grounding} kind="creator" />
            <details>
              <summary>Profile details</summary>
              {/* Optional because a company run has no evidence list; on this card it
               * is always present, and `entry.evidence.map` on a possibly-undefined
               * would throw rather than render nothing. */}
              {entry.evidence && entry.evidence.length > 0 && (
                <ul>
                  {entry.evidence.map((evidence) => <li key={evidence}>{evidence}</li>)}
                </ul>
              )}
              {details.length > 0 && <p className="result-collaborations">{details.join(" · ")}</p>}
            </details>
          </>
        )}
      </ResultRationale>
      {onSelect && (
        <button
          className="result-detail-trigger"
          type="button"
          aria-pressed={selected}
          onClick={onSelect}
        >
          {selected ? "Profile open" : "View profile"}
        </button>
      )}
    </article>
  );
}

/** Empty attributes are omitted rather than shown as "unavailable", which reads
 *  as broken data. A measured 0% and a single-item list are data, not absence,
 *  so neither is dropped.
 */
function detailPairs(creator: CreatorSnapshot): string[] {
  const pairs: string[] = [];
  if (creator.language) pairs.push(`Language: ${creator.language}`);
  if (creator.audience_age) pairs.push(`Audience: ${creator.audience_age}`);
  if (creator.audience_gender) pairs.push(`Gender: ${creator.audience_gender}`);
  if (creator.sponsored_ratio !== null) {
    pairs.push(`Sponsored: ${Math.round(creator.sponsored_ratio * 100)}%`);
  }
  if (creator.growth_trend) pairs.push(`Growth: ${creator.growth_trend}`);
  if (creator.audience_top_countries.length > 0) {
    pairs.push(`Top markets: ${creator.audience_top_countries.join(", ")}`);
  }
  if (creator.brand_collaborations.length > 0) {
    pairs.push(`Past work: ${creator.brand_collaborations.join(", ")}`);
  }
  return pairs;
}
