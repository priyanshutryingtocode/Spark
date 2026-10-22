import type { ReactNode } from "react";

/** The marks the app uses.
 *
 *  Hand-drawn rather than pulled from a library, for three reasons: the app
 *  deliberately keeps no runtime dependencies beyond React, Router and the
 *  Supabase client; a set of nine is small enough to own; and owning them means
 *  they share one grid, one stroke weight and one set of terminals.
 *
 *  Every mark is drawn on the same 24-unit grid with a 1.5 stroke, round caps
 *  and round joins, so they line up optically at 16px and at 20px.
 *
 *  Only marks that are actually drawn are here. Five were removed when the
 *  panel switch went text-only, and a mark nobody uses is something somebody
 *  has to maintain well for no reason.
 */
export type IconName =
  | "search"
  | "history"
  | "compare"
  | "swap"
  | "arrow-right"
  | "download"
  | "trash"
  | "alert"
  | "info";

const MARKS: Record<IconName, ReactNode> = {
  search: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M16 16l4.5 4.5" />
    </>
  ),
  history: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3.2 2" />
    </>
  ),
  compare: (
    /* A panel and an arrow, not two bars: two vertical rectangles read as a
     * pause button, and this mark sits in the navigation beside a page called
     * Compare, where the two of them together said "pause". */
    <>
      <rect x="3" y="5" width="8" height="14" rx="2.5" />
      <path d="M14 12h6" />
      <path d="M17 8.5 20.5 12 17 15.5" />
    </>
  ),
  "arrow-right": (
    <>
      <path d="M4.5 12h14" />
      <path d="M14 7.5l4.5 4.5-4.5 4.5" />
    </>
  ),
  swap: (
    <>
      <path d="M4 8.5h13" />
      <path d="M14 5.5l3 3-3 3" />
      <path d="M20 15.5H7" />
      <path d="M10 12.5l-3 3 3 3" />
    </>
  ),
  download: (
    <>
      <path d="M12 3.5v11" />
      <path d="M7.5 10.5L12 15l4.5-4.5" />
      <path d="M4 17v2.5A1.5 1.5 0 005.5 21h13a1.5 1.5 0 001.5-1.5V17" />
    </>
  ),
  trash: (
    <>
      <path d="M4 7h16" />
      <path d="M9.5 7V5.5A1.5 1.5 0 0111 4h2a1.5 1.5 0 011.5 1.5V7" />
      <path d="M6.5 7l.8 12.1a1.5 1.5 0 001.5 1.4h6.4a1.5 1.5 0 001.5-1.4L17.5 7" />
    </>
  ),
  alert: (
    <>
      <path d="M12 3.5L21.5 20.5H2.5z" />
      <path d="M12 10v4" />
      <path d="M12 17.4h.01" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="8.75" />
      <path d="M12 11v6" />
      <path d="M12 7.8h.01" />
    </>
  ),
};

export function Icon({ name, size = 16 }: { name: IconName; size?: number }) {
  return (
    <svg
      className="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      /* Decorative: every mark sits on a control that already carries its
         label, so exposing it would only make screen readers say the name
         twice. */
      aria-hidden="true"
      focusable="false"
    >
      {MARKS[name]}
    </svg>
  );
}
