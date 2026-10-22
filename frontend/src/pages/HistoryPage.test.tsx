import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";
import { useEffect, useRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { HistoryPage } from "./HistoryPage";

const apiMocks = vi.hoisted(() => ({
  listRuns: vi.fn(), getRun: vi.fn(), deleteRun: vi.fn(), downloadRun: vi.fn(),
}));
vi.mock("../api/client", () => ({ api: apiMocks, ApiError: class extends Error {} }));
vi.mock("../components/RunSummary", () => ({ SummaryMetrics: () => null }));

import type { RunDetail } from "../types";

const creatorRun: RunDetail = {
  run_id: "r1",
  created_at: "2026-01-01T00:00:00Z",
  brief: { goal: "home goods", platform: "Any", audience: "", vibe: "" },
  warnings: [],
  summary: { n_results: 1, avg_match_pct: 80, n_strong: 1, n_weak: 0, cells: [] },
  kind: "creator",
  candidates: [{
    id: 1, creator_key: "TikTok:@a", handle: "@a", name: "", platform: "TikTok",
    city: "", language: "", followers: 10, engagement_pct: 1, verified: false,
    content_style: "", audience_age: "", audience_gender: "", brand_collaborations: [],
    tags: [], similarity: 0.8, reach_ratio: 0, sponsored_ratio: 0, growth_trend: "",
    audience_top_countries: [],
  }],
  ranked: [{
    id: 1, creator_key: "TikTok:@a", rank: 1, fit: "strong", source: "llm",
    rationale: "", evidence: [], grounding: [], fallback_reason: "",
  }],
};

function listItem(kind: "creator" | "prospect") {
  return {
    run_id: kind === "creator" ? "r1" : "r2",
    created_at: "2026-01-01T00:00:00Z",
    brief: { goal: `${kind} run`, platform: "Any", audience: "", vibe: "" },
    kind,
    n_results: 1, n_strong: 1, has_warnings: false,
  };
}

afterEach(() => cleanup());

beforeEach(() => {
  apiMocks.listRuns.mockReset();
  apiMocks.getRun.mockReset();
  apiMocks.deleteRun.mockReset();
  apiMocks.downloadRun.mockReset();
});

/** The panel toggle lives inside the matched route, so it survives navigation. */
function Harness({ capture }: { capture: (go: () => void) => void }) {
  return (
    <MemoryRouter initialEntries={["/creators/history"]}>
      <Routes>
        <Route path="/:panel/history" element={<Paneled capture={capture} />} />
      </Routes>
    </MemoryRouter>
  );
}

function Paneled({ capture }: { capture: (go: () => void) => void }) {
  const navigate = useNavigate();
  const go = useRef<() => void>(() => navigate("/companies/history"));
  go.current = () => navigate("/companies/history");
  useEffect(() => capture(() => go.current()), [capture]);
  return <HistoryPage />;
}

describe("HistoryPage across a panel switch", () => {
  it("does not keep a creator run open on the Companies panel", async () => {
    // React Router preserves this component's state across a route change, so
    // the open creator snapshot survived the switch and reached the company
    // card, which threw on `department_mix` -- taking the whole page down.
    apiMocks.listRuns.mockImplementation((kind: string) =>
      Promise.resolve({ items: [listItem(kind as "creator")], next_cursor: null }));
    apiMocks.getRun.mockResolvedValue(creatorRun);

    let switchPanel = () => {};
    render(<Harness capture={(go) => { switchPanel = go; }} />);

    fireEvent.click(await screen.findByText("creator run"));
    await screen.findByText("@a");

    act(() => switchPanel());
    await waitFor(() => expect(apiMocks.listRuns).toHaveBeenCalledTimes(2));

    // No creator card is rendered on the Companies panel. Before the fix this
    // threw inside CompanyResultCard, which the ErrorBoundary turned into a
    // broken page.
    expect(screen.queryByText("@a")).toBeNull();
  });

  it("shows only the active panel's runs", async () => {
    apiMocks.listRuns.mockImplementation((kind: string) =>
      Promise.resolve({ items: [listItem(kind as "creator")], next_cursor: null }));

    let switchPanel = () => {};
    render(<Harness capture={(go) => { switchPanel = go; }} />);

    expect(await screen.findByText("creator run")).toBeTruthy();
    act(() => switchPanel());
    await waitFor(() => expect(apiMocks.listRuns).toHaveBeenCalledTimes(2));

    // The ledger refetched; the previous panel's row must not still be listed.
    expect(screen.queryByText("creator run")).toBeNull();
  });

  it("links its empty state into the panel you are in", async () => {
    apiMocks.listRuns.mockResolvedValue({ items: [], next_cursor: null });
    render(
      <MemoryRouter initialEntries={["/companies/history"]}>
        <Routes>
          <Route path="/:panel/history" element={<HistoryPage />} />
        </Routes>
      </MemoryRouter>,
    );

    const link = await screen.findByRole("link", { name: /run a match/i });
    expect(link.getAttribute("href")).toBe("/companies/search");
  });
});