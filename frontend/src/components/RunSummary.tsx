import { useId, useState } from "react";

import type { RunSummary } from "../types";
import { Icon } from "./Icon";
import { SIMILARITY_EXPLANATION, formatCount } from "./resultShared";

interface Cell {
  label: string;
  value: string;
  caption: string;
  /** The cell's value is the headline; rendered in the signal colour. */
  primary?: boolean;
  /** A caveat worth reaching on demand. The similarity number is the one
   *  metric here that can be misread as a fit score, so it carries the
   *  explanation rather than leaving it to a hover-only tooltip. */
  explanation?: string;
}

/** Prefer the server's cells; rebuild from the flat keys only for a summary
 *  stored before `cells` existed.
 *
 *  The fallback is here rather than deleted because summaries are immutable
 *  history: every run already in the database predates the field. It is also the
 *  single place a label is written on the client, which is what the backend's
 *  self-describing cells exist to remove going forward -- if these two ever
 *  disagree, the server wins for every new run and only old ones drift. */
function cellsFor(summary: RunSummary): Cell[] {
  if (summary.cells?.length) {
    return summary.cells.map((cell) => ({
      label: cell.label,
      value: cell.value,
      caption: cell.caption,
      primary: cell.primary,
      explanation: cell.explanation,
    }));
  }
  const cells: Cell[] = [
    { label: "Quality", value: `${summary.n_strong}/${summary.n_results}`, caption: "strong fits", primary: true },
    { label: "Avg similarity", value: `${summary.avg_match_pct.toFixed(1)}%`, caption: "cosine vs. brief", explanation: SIMILARITY_EXPLANATION },
  ];
  if (summary.avg_engagement_pct != null) {
    cells.push({ label: "Avg engagement", value: `${summary.avg_engagement_pct.toFixed(1)}%`, caption: "reach quality" });
  }
  if (summary.median_followers != null) {
    cells.push({ label: "Median reach", value: formatCount(summary.median_followers), caption: "followers" });
  }
  if (summary.median_headcount != null) {
    cells.push({ label: "Median headcount", value: formatCount(summary.median_headcount), caption: "employees" });
  }
  cells.push({ label: "Needs review", value: String(summary.n_weak), caption: "weak fits" });
  return cells;
}

export function SummaryMetrics({ summary, compact = false }: { summary: RunSummary; compact?: boolean }) {
  const [explained, setExplained] = useState(false);
  const explanationId = useId();

  return (
    <dl className={`summary-strip ${compact ? "summary-strip-compact" : ""}`}>
      {cellsFor(summary).map((cell) => {
        const body = (
          <>
            <strong>{cell.value}</strong>
            <span>{cell.caption}</span>
            {cell.explanation && explained && (
              <span className="summary-explain-body" id={explanationId}>{cell.explanation}</span>
            )}
          </>
        );
        return (
          <div className={`summary-item ${cell.primary ? "summary-item-primary" : ""}`} key={cell.label}>
            {cell.explanation
              ? (
                /* A disclosure, not a title= attribute: a <dt> is not focusable,
                 * so the caveat used to be reachable by mouse only. */
                <dt>
                  <button
                    className="summary-explain-toggle"
                    type="button"
                    aria-expanded={explained}
                    aria-controls={explained ? explanationId : undefined}
                    onClick={() => setExplained((open) => !open)}
                  >
                    {cell.label}
                    <Icon name="info" size={12} />
                  </button>
                </dt>
              )
              : <dt>{cell.label}</dt>}
            <dd>{body}</dd>
          </div>
        );
      })}
    </dl>
  );
}

