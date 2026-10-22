import type { CorpusKind, RunDetail } from "../types";
import { ResultCard } from "./ResultCard";
import type { CardVariant } from "./resultShared";

interface ResultListProps {
  /** `run` is a `Pick`, so widening it to whole RunDetail just to read `kind`
   *  would make every caller supply a field Compare's partial runs lack. */
  kind: CorpusKind;
  run: Pick<RunDetail, "brief" | "candidates" | "ranked">;
  /** Candidate keys to tint; Compare uses this to mark the shared entries. */
  highlightKeys?: Set<string>;
  className?: string;
  /** How much of each row to show. Compare asks for `compact`, because the same
   *  row appears in both of its columns. */
  variant?: CardVariant;
}

/** Whole phrases, so each corpus keeps its own wording. "creator details" says
 *  the snapshots are gone; "creators" says the shortlist was empty. */
const emptyPhrases: Record<CorpusKind, { missing: string; none: string }> = {
  creator: {
    missing: "This shortlist's creator details are no longer available.",
    none: "No creators in this shortlist.",
  },
  prospect: {
    missing: "This shortlist's company details are no longer available.",
    none: "No companies in this shortlist.",
  },
};

/** A ranked shortlist, skipping entries whose snapshot is missing. Shared by the
 *  pages so they cannot drift apart. */
export function ResultList({ kind, run, highlightKeys, className, variant = "full" }: ResultListProps) {
  const phrases = emptyPhrases[kind];
  const byId = new Map(run.candidates.map((candidate) => [candidate.id, candidate]));
  const cards = run.ranked.map((entry) => {
    const candidate = byId.get(entry.id);
    if (!candidate) return null;
    return (
      <ResultCard
        key={entry.id}
        kind={kind}
        candidate={candidate}
        entry={entry}
        brief={run.brief}
        highlight={highlightKeys?.has(candidate.creator_key) ?? false}
        variant={variant}
      />
    );
  });

  /* An empty box reads as a broken page rather than an empty result. */
  if (cards.every((card) => card === null)) {
    return (
      <div className={`result-list ${className ?? ""}`}>
        <div className="empty-ledger">
          <p>{run.ranked.length ? phrases.missing : phrases.none}</p>
        </div>
      </div>
    );
  }

  return (
    <div className={`result-list ${className ?? ""}`}>
      {cards}
    </div>
  );
}
