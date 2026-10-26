import type { CorpusKind } from "../types";

/** The structured fields each corpus reads, and how the form collects them.
 *
 *  These are the brief's *requirements* rather than its wording: the free text
 *  still drives the embedding, and these drive the filters and the rerank. A
 *  corpus only ever shows its own, so a creator brief never offers a company
 *  field and the two forms cannot drift into each other.
 */

export const AGE_BANDS = [
  "13-17", "18-24", "25-34", "35-44", "45-54", "55-64", "65+",
];

export const GENDER_PREFERENCES = [
  { value: "", label: "Any" },
  { value: "female", label: "Mostly female" },
  { value: "male", label: "Mostly male" },
  { value: "balanced", label: "Balanced" },
];

export const BUDGET_BANDS = [
  { value: "", label: "Any" },
  { value: "under 10k", label: "Under 10k" },
  { value: "10k-100k", label: "10k - 100k" },
  { value: "100k-1m", label: "100k - 1m" },
  { value: "1m-10m", label: "1m - 10m" },
  { value: "over 10m", label: "Over 10m" },
];

/** The size bands offered for a company, as headcount ranges. */
export const SIZE_BANDS = [
  { value: "", label: "Any size" },
  { value: "2-10", label: "2 - 10 staff" },
  { value: "11-50", label: "11 - 50 staff" },
  { value: "51-200", label: "51 - 200 staff" },
  { value: "201-1000", label: "201 - 1,000 staff" },
  { value: "1001-5000", label: "1,001 - 5,000 staff" },
  { value: "5001-40000", label: "5,001+ staff" },
];

/** Split "51-200" into the (min, max) the brief carries. */
export function parseSizeBand(value: string): [number, number] | null {
  if (!value) return null;
  const [low, high] = value.split("-").map((part) => Number(part));
  if (!Number.isFinite(low) || !Number.isFinite(high)) return null;
  return [low, high];
}

/** Which structured fields a corpus shows. */
export const PANEL_TARGETS: Record<CorpusKind, string[]> = {
  creator: ["audience_age", "audience_gender", "audience_countries", "languages", "min_reach_ratio"],
  prospect: ["target_industries", "target_size", "target_countries", "budget_band", "buyer_roles"],
};

/** A short, plain description of what a filter will do, for the field's help
 *  text. The wording matters: a user has to be able to tell that a filter
 *  excludes records, not that it steers the model. */
export const TARGET_HELP: Record<CorpusKind, Record<string, string>> = {
  creator: {
    audience_age: "Excludes creators whose audience is outside these bands.",
    audience_gender: "Ranks creators whose audience leans this way. Never excludes.",
    audience_countries: "Excludes creators whose audience is not in these countries.",
    languages: "Prioritizes creators who publish in these languages.",
    min_reach_ratio: "Ranks creators whose average views reach a share of their followers.",
  },
  prospect: {
    target_industries: "Excludes companies outside these verticals. Naming one industry selects the whole vertical, so \"logistics\" also covers supply chain and freight tech.",
    target_size: "Excludes companies outside this size band.",
    target_countries: "Excludes companies outside these countries.",
    budget_band: "Ranks companies by the funding stage that matches this budget.",
    buyer_roles: "Ranks companies with signals relevant to these buying roles.",
  },
};
