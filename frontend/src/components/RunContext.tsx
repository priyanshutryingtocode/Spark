import type { RunDetail } from "../types";
import { Icon } from "./Icon";
import { formatDate } from "../format";

interface RunContextProps {
  /** The whole run. Every caller already had it in hand and passed two of its
   *  fields across, so the pair could be mismatched -- a date from one run
   *  above a goal from another. */
  run: RunDetail;
  /** Distinct label per page, e.g. "Shortlist" or "Run detail". */
  label: string;
  /** A double-click used to fire two downloads before the first resolved. */
  exporting?: boolean;
  onExport: () => void;
}

export function RunContext({ run, label, exporting = false, onExport }: RunContextProps) {
  const { brief, created_at: createdAt } = run;
  return (
    <div className="run-context">
      <div>
        <p className="eyebrow">{label} / {run.dataset === "real" ? "Real data" : "Synthetic data"} / {formatDate(createdAt)}</p>
        <h2 className="run-context-goal">{brief.goal}</h2>
        <p className="run-context-line">
          {brief.platform}
          {brief.audience && <><span>/</span> {brief.audience}</>}
          {brief.vibe && <><span>/</span> {brief.vibe}</>}
        </p>
        {brief.product_context?.category && (
          <details className="run-context-product">
            <summary>Product context used: {brief.product_context.category}</summary>
            {brief.product_context.target_audience && <p>Audience: {brief.product_context.target_audience}</p>}
            {brief.product_context.use_cases.length > 0 && <p>Use cases: {brief.product_context.use_cases.join(", ")}</p>}
            {brief.product_context.differentiators.length > 0 && <p>Differentiators: {brief.product_context.differentiators.join(", ")}</p>}
            {brief.product_context.exclusions.length > 0 && <p>Exclusions: {brief.product_context.exclusions.join(", ")}</p>}
          </details>
        )}
      </div>
      <button className="btn btn-secondary" type="button" onClick={onExport} disabled={exporting} aria-busy={exporting}>
        <Icon name="download" size={14} />
        {exporting ? "Exporting..." : "Export CSV"}
      </button>
    </div>
  );
}
