import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it } from "vitest";

import { CreatorResultCard } from "./CreatorResultCard";
import type { Brief, CreatorSnapshot, RankedEntry } from "../types";

afterEach(() => cleanup());

const brief: Brief = { goal: "home goods for small kitchens", platform: "Any", audience: "", vibe: "" };

const creator: CreatorSnapshot = {
  id: 1, creator_key: "TikTok:@a", handle: "@a", name: "", platform: "TikTok",
  city: "Austin", language: "", followers: 1_000, engagement_pct: 5, verified: false,
  content_style: "", audience_age: "", audience_gender: "", brand_collaborations: [],
  tags: [], similarity: 0.8, reach_ratio: 2, sponsored_ratio: 0, growth_trend: "",
  audience_top_countries: [],
};

const entry: RankedEntry = {
  id: 1, creator_key: "TikTok:@a", rank: 1, fit: "strong", source: "llm",
  rationale: "", evidence: [], grounding: [], fallback_reason: "",
};

describe("a ratio that exceeds 1", () => {
  // reach_ratio reaches 2.00 and 18% of generated creators exceed 1.0, so the
  // bar was full while the number beside it read "200%" -- which reads as a
  // data error rather than as a real measurement.
  const renderCard = (reach_ratio: number) => render(
    <MemoryRouter>
      <CreatorResultCard creator={{ ...creator, reach_ratio }} entry={entry} brief={brief} />
    </MemoryRouter>,
  );

  it("caps the printed value at 100%", () => {
    renderCard(2);
    expect(screen.getByText("100%")).toBeTruthy();
    expect(screen.queryByText("200%")).toBeNull();
  });

  it("still shows a real under-1 value unchanged", () => {
    renderCard(0.31);
    expect(screen.getByText("31%")).toBeTruthy();
  });

  it("caps a value just over the boundary", () => {
    renderCard(1.04);
    expect(screen.getByText("100%")).toBeTruthy();
  });
});

describe("a measured zero is data, not absence", () => {
  it("shows 0% sponsorship", () => {
    // `> 0` treated a measured 0% as missing, though the other fields render 0
    // when the corpus says zero.
    render(
      <MemoryRouter>
        <CreatorResultCard creator={creator} entry={entry} brief={brief} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Sponsored: 0%")).toBeTruthy();

  });

  it("shows a single top market", () => {
    // `> 1` hid a one-item list, treating it as nothing to say.
    const { container } = render(
      <MemoryRouter>
        <CreatorResultCard
          creator={{ ...creator, audience_top_countries: ["Germany"] }}
          entry={entry}
          brief={brief}
        />
      </MemoryRouter>,
    );
    // The pairs share one " · "-joined node, so match on its contents.
    expect(container.querySelector(".result-collaborations")?.textContent)
      .toContain("Top markets: Germany");
  });
});
