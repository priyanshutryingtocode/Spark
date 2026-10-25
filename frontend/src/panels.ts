import { useLocation } from "react-router-dom";

import type { CorpusKind } from "./types";

/** What the two panels call their results. The nouns live here because the same
 *  word appears in a heading, an empty state and a slider's aria-valuetext, and
 *  a mismatch between them reads as a bug even when nothing is wrong. */
export interface Panel {
  kind: CorpusKind;
  /** URL segment. */
  slug: "creators" | "companies";
  /** Segmented-control label. */
  label: string;
  singular: string;
  plural: string;
  describe: string;
}

export const PANELS: Record<CorpusKind, Panel> = {
  creator: {
    kind: "creator",
    slug: "creators",
    label: "Creators",
    singular: "creator",
    plural: "creators",
    describe: "Look up creators based on your requirements.",
  },
  prospect: {
    kind: "prospect",
    slug: "companies",
    label: "Companies",
    singular: "company",
    plural: "companies",
    describe: "Look up companies based on what you sell.",
  },
};

const SLUG_TO_KIND: Record<string, CorpusKind> = {
  creators: "creator",
  companies: "prospect",
};

/** Workspace pages, in nav order. Shared by the router and navigation. */
export const PAGES = [
  { slug: "search", label: "Search" },
  { slug: "saved", label: "Saved" },
  { slug: "history", label: "History" },
  { slug: "compare", label: "Compare" },
] as const;

export type PageSlug = (typeof PAGES)[number]["slug"];

export const DEFAULT_PAGE: PageSlug = "search";

/** Which panel the current URL belongs to.
 *
 *  Derived from the path on every render rather than held in state. That is the
 *  whole reason the two panels can share a layout: there is nothing to keep in
 *  sync, so a deep link, the browser back button and a toggle click all agree by
 *  construction. State would let those three disagree -- arriving at
 *  /companies/search with the toggle reading "Creators" is the bug this avoids. */
export function useCorpus(): CorpusKind {
  const { pathname } = useLocation();
  return corpusFromPath(pathname);
}

export function corpusFromPath(pathname: string): CorpusKind {
  const segment = pathname.split("/").filter(Boolean)[0];
  return SLUG_TO_KIND[segment] ?? "creator";
}

export function panelPath(kind: CorpusKind, page: PageSlug = DEFAULT_PAGE): string {
  return `/${PANELS[kind].slug}/${page}`;
}

/** The current sub-page, so switching panels keeps the reader where they were.
 *  Falls back to Search for a URL with no recognised page segment. */
export function pageFromPath(pathname: string): PageSlug {
  const segments = pathname.split("/").filter(Boolean);
  const candidate = segments[1];
  const match = PAGES.find((page) => page.slug === candidate);
  return match ? match.slug : DEFAULT_PAGE;
}
