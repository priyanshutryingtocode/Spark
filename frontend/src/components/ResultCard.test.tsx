import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { ResultCard } from "./ResultCard";
import { ResultList } from "./ResultList";
import { SummaryMetrics } from "./RunSummary";
import { corpusFromPath, pageFromPath, panelPath } from "../panels";
import type { Brief, CreatorSnapshot, ProspectSnapshot, RankedEntry } from "../types";

afterEach(() => cleanup());

const brief: Brief = {
  goal: "warehouse robotics and fleet routing software for logistics firms",
  platform: "Any",
  audience: "",
  vibe: "",
};

const creator: CreatorSnapshot = {
  id: 1, creator_key: "TikTok:@a", handle: "@a", name: "A Person", platform: "TikTok",
  city: "Austin", language: "en", followers: 24_500, engagement_pct: 4.1, verified: true,
  content_style: "warm", audience_age: "25-34", audience_gender: "",
  brand_collaborations: [], tags: ["home", "kitchen"], similarity: 0.82,
  reach_ratio: 0.31, sponsored_ratio: 0, growth_trend: "steady", audience_top_countries: [],
};

const company: ProspectSnapshot = {
  id: 1, creator_key: "logistics:Acme", name: "Acme Logistics", industry: "logistics",
  headcount: 1_200, city: "Berlin", country: "Germany", description: "Freight tooling.",
  website: "https://acme.test", founded_year: 2019, funding_stage: "Series A",
  tags: ["freight"], similarity: 0.71, seniority_mix: "mid-weighted",
  department_mix: ["engineering", "sales"], tech_stack: ["SAP"],
  buying_signals: ["needs route optimisation"], growth_trend: "rising",
  growth_rate: -0.06, hiring_intensity: 0.4, top_markets: ["Germany"],
};

const creatorEntry: RankedEntry = {
  id: 1, creator_key: "TikTok:@a", rank: 1, fit: "strong", source: "llm",
  rationale: "Direct fit.", evidence: ["States a home-goods focus."],
  grounding: [{ field: "audience_age", quote: "25-34" }], fallback_reason: "",
};

const companyEntry: RankedEntry = {
  id: 1, creator_key: "logistics:Acme", rank: 1, fit: "strong", source: "llm",
  rationale: "Logistics at the requested scale.",
  grounding: [{ field: "headcount", quote: "1200" }], fallback_reason: "",
};

function renderCard(kind: "creator" | "prospect", candidate: CreatorSnapshot | ProspectSnapshot, entry: RankedEntry) {
  return render(
    <MemoryRouter>
      <ResultCard kind={kind} candidate={candidate} entry={entry} brief={brief} />
    </MemoryRouter>,
  );
}

function renderCompact(kind: "creator" | "prospect", candidate: CreatorSnapshot | ProspectSnapshot, entry: RankedEntry) {
  return render(
    <MemoryRouter>
      <ResultCard kind={kind} candidate={candidate} entry={entry} brief={brief} variant="compact" />
    </MemoryRouter>,
  );
}

describe("ResultCard", () => {
  it("renders a creator with the creator metrics", () => {
    renderCard("creator", creator, creatorEntry);

    expect(screen.getByText("@a")).toBeTruthy();
    expect(screen.getByText("Followers")).toBeTruthy();
    expect(screen.getByText("25K")).toBeTruthy();
    expect(screen.getByText("Engagement")).toBeTruthy();
    expect(screen.getByText("Verified")).toBeTruthy();
  });

  it("renders a company with headcount and no creator metrics", () => {
    renderCard("prospect", company, companyEntry);

    expect(screen.getByText("Acme Logistics")).toBeTruthy();
    // "Headcount" is twice over: the metric label and the citation label for the
    // rubric's headcount grounding. Both are wanted, so this counts them rather
    // than demanding exactly one.
    expect(screen.getAllByText("Headcount").length).toBe(2);
    expect(screen.getByText("1K")).toBeTruthy();
    // The absence is the point: a company has no followers, and printing an
    // empty Followers cell would imply one was measured and found to be zero.
    expect(screen.queryByText("Followers")).toBeNull();
    expect(screen.queryByText("Engagement")).toBeNull();
    expect(screen.queryByText("Verified")).toBeNull();
  });

  it("labels a company's citations with company field names", () => {
    renderCard("prospect", company, companyEntry);

    // The citation label is the map's word for the field, not the raw key. With
    // only the creator map present this would render as "headcount" -- correct,
    // but as an untranslated key next to "Audience age" on the other panel.
    const citation = document.querySelector(".grounding-field");
    expect(citation?.textContent).toBe("Headcount");
  });

  it("keeps creator citations on creator field names", () => {
    renderCard("creator", creator, creatorEntry);
    expect(screen.getByText("Audience age")).toBeTruthy();
  });

  it("offers company details behind a disclosure, with no evidence list", () => {
    renderCard("prospect", company, companyEntry);

    expect(screen.getByText("Company details")).toBeTruthy();
    // A company run has nothing to verify field-by-field; showing the heading as
    // "Profile details" or listing an empty evidence set would both misdescribe it.
    expect(screen.queryByText("Profile details")).toBeNull();
    expect(screen.queryByText("States a home-goods focus.")).toBeNull();
  });

  it("barks hiring intensity, which is a true 0-1 proportion", () => {
    renderCard("prospect", company, companyEntry);
    expect(screen.getByText("Hiring intensity")).toBeTruthy();
  });

  it("does not bar a shrinking growth rate", () => {
    // growth_rate is negative here. Rescaling it to fill a bar would report a
    // -6% decline as a full bar, so it is text in the details, not a bar.
    renderCard("prospect", company, companyEntry);
    expect(screen.queryByText("Growth rate")).toBeNull();
  });

  it("switches on the run's kind, never on the candidate's shape", () => {
    // A creator snapshot handed to the company card throws rather than rendering
    // as a creator. Shape-sniffing ("does it have a handle?") would have picked
    // the creator card here and shown a plausible, wrong row; the backend now
    // names the union arm from the run's kind, so a mismatch is a real bug and
    // is allowed to be loud.
    expect(() => renderCard("prospect", creator, companyEntry)).toThrow();
    // The same candidate in its own panel renders fine, so the failure is the
    // mismatch rather than the fixture.
    expect(() => renderCard("creator", creator, creatorEntry)).not.toThrow();
  });
});

describe("the compact card", () => {
  /* Compare shows the same row in both of its columns. The full card is the
   * same information twice, and the citation labels are the loudest part of
   * it, so the compact row drops them. */
  it("drops the citation labels, the evidence and the details disclosure", () => {
    renderCompact("creator", creator, creatorEntry);

    expect(screen.queryByText("Audience age")).toBeNull();
    expect(screen.queryByText("Profile details")).toBeNull();
    expect(screen.queryByText("States a home-goods focus.")).toBeNull();
    // The topic tags go with them: the citation list carried the same topics
    // with a label beside them.
    expect(screen.queryByText("home  ·  kitchen")).toBeNull();
  });

  it("keeps the identity, the verdict, the metrics and the reason", () => {
    renderCompact("creator", creator, creatorEntry);

    expect(screen.getByText("@a")).toBeTruthy();
    expect(screen.getByText("A Person")).toBeTruthy();
    expect(screen.getByText("Strong")).toBeTruthy();
    expect(screen.getByText("Followers")).toBeTruthy();
    expect(screen.getByText("25K")).toBeTruthy();
    expect(screen.getByText("Engagement")).toBeTruthy();
    expect(screen.getByText("4.1%")).toBeTruthy();
    expect(screen.getByText("Direct fit.")).toBeTruthy();
  });

  it("drops the reach bar, which was the one line the compact row cannot carry", () => {
    renderCompact("creator", creator, creatorEntry);
    expect(screen.queryByText("Reach rate")).toBeNull();
    // The full card still has it.
    cleanup();
    renderCard("creator", creator, creatorEntry);
    expect(screen.getByText("Reach rate")).toBeTruthy();
  });

  it("keeps a fallback label, because it is a warning and not decoration", () => {
    const fellBack: RankedEntry = {
      ...creatorEntry, source: "fallback", fallback_reason: "daily_quota: The daily quota is spent.",
    };
    renderCompact("creator", creator, fellBack);

    expect(screen.getByText("Retrieval fallback")).toBeTruthy();
    expect(screen.getByText("The daily quota is spent.")).toBeTruthy();
  });

  it("drops a company's citations and hiring bar the same way", () => {
    renderCompact("prospect", company, companyEntry);

    expect(screen.queryByText("Company details")).toBeNull();
    expect(screen.queryByText("Hiring intensity")).toBeNull();
    expect(screen.getByText("Acme Logistics")).toBeTruthy();
    expect(screen.getByText("Headcount")).toBeTruthy();
    expect(screen.getByText("Logistics at the requested scale.")).toBeTruthy();
  });
});

describe("ResultList", () => {
  it("uses the panel's own empty-state wording", () => {
    const { rerender } = render(
      <MemoryRouter>
        <ResultList kind="prospect" run={{ brief, candidates: [], ranked: [] }} />
      </MemoryRouter>,
    );
    expect(screen.getByText("No companies in this shortlist.")).toBeTruthy();

    rerender(
      <MemoryRouter>
        <ResultList kind="creator" run={{ brief, candidates: [], ranked: [] }} />
      </MemoryRouter>,
    );
    // The creator wording is unchanged: "creator details" says the snapshots are
    // gone, "creators" says the shortlist was empty, and swapping them would
    // misreport which happened.
    expect(screen.getByText("No creators in this shortlist.")).toBeTruthy();
  });

  it("distinguishes a missing snapshot from an empty shortlist", () => {
    render(
      <MemoryRouter>
        <ResultList kind="prospect" run={{ brief, candidates: [], ranked: [companyEntry] }} />
      </MemoryRouter>,
    );
    expect(screen.getByText("This shortlist's company details are no longer available.")).toBeTruthy();
  });
});

describe("panel routing", () => {
  it("reads the panel from the path", () => {
    expect(corpusFromPath("/creators/search")).toBe("creator");
    expect(corpusFromPath("/companies/history")).toBe("prospect");
    // Unknown or root paths fall back to creators: every run stored before the
    // split is one, so that is the safe default.
    expect(corpusFromPath("/")).toBe("creator");
    expect(corpusFromPath("/nonsense")).toBe("creator");
    expect(corpusFromPath("/creators")).toBe("creator");
  });

  it("keeps the reader on the same sub-page across a panel switch", () => {
    expect(pageFromPath("/creators/history")).toBe("history");
    expect(pageFromPath("/companies/compare")).toBe("compare");
    expect(panelPath("prospect", "history")).toBe("/companies/history");
    // A URL with no page segment switches to Search rather than nowhere.
    expect(pageFromPath("/companies")).toBe("search");
    expect(pageFromPath("/companies/typo")).toBe("search");
  });

  it("builds a distinct path per panel", () => {
    expect(panelPath("creator", "search")).toBe("/creators/search");
    expect(panelPath("prospect", "search")).toBe("/companies/search");
  });
});

describe("a company summary strip needs no client-side corpus branch", () => {
  it("renders from the server's cells alone", () => {
    // The strip is driven entirely by `cells`, which the backend fills per
    // corpus. That is why splitting the app needed no change here -- a company
    // strip is the same component with different cells, and there is no second
    // table of labels on the client to keep in step.
    render(
      <SummaryMetrics summary={{
        kind: "prospect",
        cells: [
          { key: "n_results", label: "Quality", caption: "strong fits", value: "1/2", primary: true },
          { key: "median_headcount", label: "Median headcount", caption: "employees", value: "720" },
        ],
        n_results: 2, avg_match_pct: 70, n_strong: 1, n_weak: 0, median_headcount: 720,
      }} />,
    );

    expect(screen.getByText("1/2")).toBeTruthy();
    expect(screen.getByText("Median headcount")).toBeTruthy();
    expect(screen.getByText("employees")).toBeTruthy();
    expect(screen.queryByText("Avg engagement")).toBeNull();
  });
});
