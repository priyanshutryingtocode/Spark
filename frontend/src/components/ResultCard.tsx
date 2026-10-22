import type {
  Brief, CorpusKind, CreatorSnapshot, ProspectSnapshot, RankedEntry,
} from "../types";
import { CompanyResultCard } from "./CompanyResultCard";
import { CreatorResultCard } from "./CreatorResultCard";
import type { CardVariant } from "./resultShared";

/** Picks the card from the run's `kind`, never from the candidate's shape: a
 *  shape test would make rendering depend on the data being well-formed, so a
 *  malformed snapshot would silently render as the other kind.
 */
export function ResultCard({
  kind, candidate, entry, brief, highlight = false, variant = "full",
}: {
  kind: CorpusKind;
  candidate: CreatorSnapshot | ProspectSnapshot;
  entry: RankedEntry;
  brief: Brief;
  highlight?: boolean;
  variant?: CardVariant;
}) {
  if (kind === "prospect") {
    return (
      <CompanyResultCard
        company={candidate as ProspectSnapshot}
        entry={entry}
        brief={brief}
        highlight={highlight}
        variant={variant}
      />
    );
  }
  return (
    <CreatorResultCard
      creator={candidate as CreatorSnapshot}
      entry={entry}
      brief={brief}
      highlight={highlight}
      variant={variant}
    />
  );
}
