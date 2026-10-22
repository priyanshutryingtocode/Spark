import type { ReactNode } from "react";

interface PageIntroProps {
  eyebrow: string;
  title: string;
  description: string;
  meta?: ReactNode;
  /** `compact` shrinks the heading.
   *
   *  The display size is for a page a reader arrives at. A working page -- a
   *  comparison table, a ledger -- is a surface the reader is already using,
   *  and at forty pixels the heading was the loudest thing on the screen and
   *  pushed the work itself below the fold. */
  variant?: "default" | "compact";
}

export function PageIntro({ eyebrow, title, description, meta, variant = "default" }: PageIntroProps) {
  return (
    <div className={`page-intro ${variant === "compact" ? "page-intro-compact" : ""}`}>
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="page-description">{description}</p>
      </div>
      {meta && <div className="page-intro-meta">{meta}</div>}
    </div>
  );
}
