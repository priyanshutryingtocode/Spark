import { Icon, type IconName } from "./Icon";

interface EmptyStateProps {
  /** An optional mark above the heading, for a state that has a picture to it. */
  icon?: IconName;
  /** Small uppercase tag above the heading: READY, NO MATCH, SELECT. Omit for
   *  a transient state that does not warrant one. */
  index?: string;
  title: string;
  body?: string;
  /** Optional trailing row, used by the ready state to preview the stages. */
  steps?: string[];
  /** Marks a state that will resolve on its own, so assistive tech is told the
   *  region is updating rather than being left to guess. */
  busy?: boolean;
}

/** The one shape for "there is nothing to show here yet". Four call sites were
 *  open-coding it with drifting structure -- one carried an index and a body,
 *  one carried neither, and only one was a component. */
export function EmptyState({ index, title, body, steps, icon, busy = false }: EmptyStateProps) {
  return (
    <div className="empty-state" {...(busy ? { "aria-live": "polite" as const, "aria-busy": "true" } : {})}>
      {icon && <span className="empty-mark"><Icon name={icon} size={22} /></span>}
      {index && <span className="empty-index">{index}</span>}
      <h2>{title}</h2>
      {body && <p>{body}</p>}
      {steps && <div className="empty-steps">{steps.map((step) => <span key={step}>{step}</span>)}</div>}
    </div>
  );
}
