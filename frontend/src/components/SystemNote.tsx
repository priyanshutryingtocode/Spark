import { Icon } from "./Icon";

interface SystemNoteProps {
  /** `error` claims something failed; `info` is neutral guidance. Drives both
   *  the accent colour and the live-region role, so a failure is always
   *  announced and guidance is never urgent. */
  tone: "error" | "info";
  title: string;
  children: React.ReactNode;
  /** Offered beside the message. A failure the user cannot act on is half a
   *  failure, and the retriable ones should not make them re-navigate. */
  action?: React.ReactNode;
}

/** One inline note for every page, so a message never looks different depending
 *  on where it happened. Three call sites were hand-rolling this markup -- two of
 *  them in ComparePage, byte-identical apart from the text. */
export function SystemNote({ tone, title, children, action }: SystemNoteProps) {
  return (
    <div className={`system-note system-note-${tone}`} role={tone === "error" ? "alert" : "status"}>
      <span className="system-note-signal" aria-hidden="true">
        <Icon name={tone === "error" ? "alert" : "info"} size={15} />
      </span>
      <strong>{title}</strong>
      <span>{children}</span>
      {action && <span className="note-actions">{action}</span>}
    </div>
  );
}

/** A failure, phrased as a failure. */
export function ErrorNote({ title, children, action }: Omit<SystemNoteProps, "tone">) {
  return <SystemNote tone="error" title={title} action={action}>{children}</SystemNote>;
}

/** Neutral guidance: a prompt to act, not a problem. */
export function InfoNote({ title, children }: Omit<SystemNoteProps, "tone" | "action">) {
  return <SystemNote tone="info" title={title}>{children}</SystemNote>;
}

/** The recurring failure titles, written once.
 *
 *  "Export issue" and "Archive issue" were each typed at two call sites in two
 *  different files, so the same failure could read differently on two pages --
 *  the kind of drift that only shows up when you happen to be looking at both.
 *  A one-off title is still passed directly; this covers the recurring kinds.
 */
export const NOTE_TITLES = {
  connection: "Connection issue",
  request: "Request issue",
  archive: "Archive issue",
  export: "Export issue",
  comparison: "Comparison issue",
  authConfig: "Auth not configured",
  crashed: "Something broke on this page",
} as const;
