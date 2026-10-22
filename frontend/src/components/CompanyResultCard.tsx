import type { Brief, ProspectSnapshot, RankedEntry } from "../types";
import {
  GroundingList,
  Metric,
  ProportionBar,
  ResultFit,
  ResultRank,
  ResultRationale,
  formatCount,
} from "./resultShared";
import type { CardVariant } from "./resultShared";

export function CompanyResultCard({
  company, entry, brief, highlight = false, variant = "full",
}: {
  company: ProspectSnapshot;
  entry: RankedEntry;
  brief: Brief;
  highlight?: boolean;
  variant?: CardVariant;
}) {
  // No platform facet: a company is not on TikTok and the server does not filter
  // prospects by one, so the subtitle leads with what a seller screens on.
  const location = [company.city, company.country].filter(Boolean).join(", ");
  const subtitle = [company.industry, location].filter(Boolean).join(" · ");
  const details = detailPairs(company);
  const compact = variant === "compact";
  const reasons = company.match_reasons ?? [];

  return (
    <article
      className={["result-row", compact && "result-row-compact", highlight && "result-row-highlight"].filter(Boolean).join(" ")}
      aria-label={`Match ${entry.rank} for ${brief.goal}`}
    >
      <ResultRank rank={entry.rank} />
      <div className="result-identity">
        <div className="result-identity-heading">
          <h3>{company.name}</h3>
          {company.funding_stage && (
            <span className="result-display-name">{company.funding_stage}</span>
          )}
        </div>
        {/* Two lines in the compact variant, so the two columns' rows line up.
            See the creator card for why the filter reasons share the meta line
            rather than taking one of their own. */}
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
            {company.tags.length > 0 && <p className="result-tags">{company.tags.slice(0, 3).join("  ·  ")}</p>}
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
        similarity={company.similarity}
        source={entry.source}
        fallbackReason={entry.fallback_reason}
        goal={brief.goal}
        compact={compact}
      />
      <div className="result-metrics">
        {/* Headcount is the scale dimension the prospect rubric judges fit on, so
         *  it takes the slot followers held: it is the number that says whether
         *  this company is the size the brief described. */}
        <Metric label="Headcount" value={formatCount(company.headcount)} />
        <Metric label="Founded" value={company.founded_year ? String(company.founded_year) : "—"} />
        {/* Hiring intensity is a true 0-1 proportion, so unlike growth_rate -- which
         * goes negative for a shrinking company -- it can honestly fill a bar. */}
        {!compact && (
          <ProportionBar
            label="Hiring intensity"
            value={company.hiring_intensity}
            description="of the workforce"
          />
        )}
      </div>
      <ResultRationale rationale={entry.rationale} compact={compact}>
        {!compact && (
          <>
            <GroundingList grounding={entry.grounding} kind="prospect" />
            <details>
              <summary>Company details</summary>
              {/* No evidence list. `evidence` is per-field verification against brief
               * signals, and a company run has none -- the server omits the key rather
               * than sending an empty list that would read as "checked, found
               * nothing". */}
              {details.length > 0 && <p className="result-collaborations">{details.join(" · ")}</p>}
            </details>
          </>
        )}
      </ResultRationale>
    </article>
  );
}

/** Signed on purpose: a shrinking company is a real answer, and flattening it to
 *  "0%" would hide the signal that makes it a poor lead. */
function growthLabel(company: ProspectSnapshot): string {
  const percent = company.growth_rate * 100;
  if (percent === 0) return "";
  return `Growth: ${percent > 0 ? "+" : ""}${percent.toFixed(1)}%`;
}

function detailPairs(company: ProspectSnapshot): string[] {
  const pairs: string[] = [];
  const growth = growthLabel(company);
  if (growth) pairs.push(growth);
  if (company.growth_trend) pairs.push(`Trend: ${company.growth_trend}`);
  if (company.seniority_mix) pairs.push(`Seniority: ${company.seniority_mix}`);
  if (company.department_mix.length > 0) pairs.push(`Teams: ${company.department_mix.join(", ")}`);
  if (company.tech_stack.length > 0) pairs.push(`Tech: ${company.tech_stack.join(", ")}`);
  if (company.buying_signals.length > 0) pairs.push(`Needs: ${company.buying_signals.join(", ")}`);
  if (company.top_markets.length > 0) pairs.push(`Top markets: ${company.top_markets.join(", ")}`);
  if (company.website) pairs.push(company.website);
  if (company.description) pairs.push(company.description);
  return pairs;
}
