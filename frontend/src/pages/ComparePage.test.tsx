import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MemoryRouter } from "react-router-dom";

import { ComparePage } from "./ComparePage";

const { apiMocks, ApiErrorMock } = vi.hoisted(() => {
  class ApiError extends Error {}
  return {
    ApiErrorMock: ApiError,
    apiMocks: { listRuns: vi.fn(), compareRuns: vi.fn(), getRun: vi.fn() },
  };
});

vi.mock("../api/client", () => ({
  api: apiMocks,
  ApiError: ApiErrorMock,
}));

function listItem(runId: string, goal: string) {
  return {
    run_id: runId,
    created_at: "2026-01-01T00:00:00Z",
    brief: { goal, platform: "Any", audience: "", vibe: "" },
    n_results: 1,
    n_strong: 1,
    has_warnings: false,
    summary: { n_results: 1, avg_match_pct: 70, n_strong: 1, n_weak: 0, avg_engagement_pct: 4, median_followers: 1000 },
  };
}

/** A real snapshot and a real ranked entry, so the result cards render. The
 *  empty fixtures the page used to carry hid the whole card layer from the
 *  tests, which is where the compact variant lives. */
const snapshot = {
  id: 1, creator_key: "Instagram:@a", handle: "@a", name: "A Person", platform: "Instagram",
  city: "Austin", language: "en", followers: 24_500, engagement_pct: 4.1, verified: true,
  content_style: "warm", audience_age: "25-34", audience_gender: "",
  brand_collaborations: [], tags: ["home", "kitchen"], similarity: 0.82,
  reach_ratio: 0.31, sponsored_ratio: 0, growth_trend: "steady", audience_top_countries: [],
};

const entry = {
  id: 1, creator_key: "Instagram:@a", rank: 1, fit: "strong", source: "llm",
  rationale: "Direct fit.", evidence: ["States a home-goods focus."],
  grounding: [{ field: "audience_age", quote: "25-34" }], fallback_reason: "",
};

function detail(runId: string) {
  return {
    run_id: runId,
    created_at: "2026-01-01T00:00:00Z",
    brief: { goal: `goal for ${runId}`, platform: "Any", audience: "", vibe: "" },
    summary: { n_results: 1, avg_match_pct: 70, n_strong: 1, n_weak: 0, avg_engagement_pct: 4, median_followers: 1000 },
    warnings: [],
    candidates: [snapshot],
    ranked: [entry],
  };
}

function comparison() {
  return {
    summary_a: { n_results: 1, avg_match_pct: 70, n_strong: 1, n_weak: 0, avg_engagement_pct: 4, median_followers: 1000 },
    summary_b: { n_results: 1, avg_match_pct: 70, n_strong: 1, n_weak: 0, avg_engagement_pct: 4, median_followers: 1000 },
    shared: [],
  };
}

/** Wrapped in a MemoryRouter because the page reads its panel from the URL. The
 *  route is set per test where it matters; the default is the Creators panel. */
function renderPage(route = "/creators/compare") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <ComparePage />
    </MemoryRouter>,
  );
}

describe("ComparePage", () => {
  beforeEach(() => {
    apiMocks.listRuns.mockReset();
    apiMocks.compareRuns.mockReset();
    apiMocks.getRun.mockReset();
  });

  afterEach(() => cleanup());

  it("prompts for two runs when the archive is empty", async () => {
    apiMocks.listRuns.mockResolvedValue({ items: [], next_cursor: null });
    renderPage();

    await waitFor(() => expect(screen.getByText(/Two runs make a comparison/)).toBeTruthy());
  });

  it("reports a failed archive load with its own retry, not the comparison's", async () => {
    apiMocks.listRuns.mockRejectedValue(new ApiErrorMock("backend asleep"));
    renderPage();

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("backend asleep"));
    // A list failure must not read as a comparison problem.
    expect(screen.queryByText(/Comparison issue/)).toBeNull();
    expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy();
  });

  it("reloads the archive when the list retry is pressed", async () => {
    apiMocks.listRuns.mockRejectedValueOnce(new ApiErrorMock("backend asleep"));
    renderPage();
    await waitFor(() => expect(screen.getByRole("button", { name: "Retry" })).toBeTruthy());

    apiMocks.listRuns.mockResolvedValue({ items: [], next_cursor: null });
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(screen.getByText(/Two runs make a comparison/)).toBeTruthy());
    expect(apiMocks.listRuns).toHaveBeenCalledTimes(2);
  });

  it("falls back to a readable message when the failure is not an ApiError", async () => {
    apiMocks.listRuns.mockRejectedValue(new TypeError("network"));
    renderPage();

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Could not load saved runs."));
  });

  it("compares the two most recent runs automatically", async () => {
    apiMocks.listRuns.mockResolvedValue({ items: [listItem("a", "first"), listItem("b", "second")], next_cursor: null });
    apiMocks.compareRuns.mockResolvedValue(comparison());
    apiMocks.getRun.mockImplementation((runId: string) => Promise.resolve(detail(runId)));
    renderPage();

    // The third argument is the caller's abort signal, so a select change
    // cancels the comparison POST rather than leaving it in flight.
    await waitFor(() => expect(apiMocks.compareRuns).toHaveBeenCalledWith("a", "b", expect.anything()));
    await waitFor(() => expect(screen.getByText(/Shared creators/)).toBeTruthy());
  });

  /* One `error` slot served both fetches, so a failed comparison could render
   * the archive-failure panel that offers a retry which refetches the list --
   * the user was sent to fix the thing that was already working. */
  it("reports a failed comparison separately, with a retry that re-compares", async () => {
    apiMocks.listRuns.mockResolvedValue({ items: [listItem("a", "first"), listItem("b", "second")], next_cursor: null });
    apiMocks.compareRuns.mockRejectedValue(new ApiErrorMock("comparison exploded"));
    apiMocks.getRun.mockImplementation((runId: string) => Promise.resolve(detail(runId)));
    renderPage();

    await waitFor(() => expect(screen.getByText(/Comparison issue/)).toBeTruthy());
    expect(screen.getByRole("alert").textContent).toContain("comparison exploded");
    expect(apiMocks.listRuns).toHaveBeenCalledTimes(1);

    apiMocks.compareRuns.mockResolvedValue(comparison());
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(apiMocks.compareRuns).toHaveBeenCalledTimes(2));
    // The retry re-ran the comparison, not the archive.
    expect(apiMocks.listRuns).toHaveBeenCalledTimes(1);
  });

  it("shows a hint instead of a stale comparison when both selects hold one run", async () => {
    apiMocks.listRuns.mockResolvedValue({ items: [listItem("a", "first"), listItem("b", "second")], next_cursor: null });
    apiMocks.compareRuns.mockResolvedValue(comparison());
    apiMocks.getRun.mockImplementation((runId: string) => Promise.resolve(detail(runId)));
    renderPage();
    await waitFor(() => expect(screen.getByText(/Shared creators/)).toBeTruthy());

    fireEvent.change(screen.getAllByRole("combobox")[0], { target: { value: "b" } });

    await waitFor(() => expect(screen.getByText(/Choose two different runs/)).toBeTruthy());
    expect(screen.queryByText(/Shared creators/)).toBeNull();
  });
});

describe("ComparePage layout", () => {
  beforeEach(() => {
    apiMocks.listRuns.mockReset();
    apiMocks.compareRuns.mockReset();
    apiMocks.getRun.mockReset();
  });

  afterEach(() => cleanup());

  async function renderTwoRuns(result = comparison()) {
    apiMocks.listRuns.mockResolvedValue({ items: [listItem("a", "first"), listItem("b", "second")], next_cursor: null });
    apiMocks.compareRuns.mockResolvedValue(result);
    apiMocks.getRun.mockImplementation((runId: string) => Promise.resolve(detail(runId)));
    renderPage();
    await waitFor(() => expect(screen.getByText(/Shared creators/)).toBeTruthy());
  }

  /* The toolbar is a three-column grid. It had four children -- Run A, a
   * decorative icon, the swap button and Run B -- so Run B wrapped onto a
   * second row and the swap button sat alone in the middle of an empty column.
   * The count is the contract: three children for three columns. */
  it("gives the toolbar one child per grid column", async () => {
    await renderTwoRuns();

    const toolbar = document.querySelector(".compare-toolbar");
    expect(toolbar).toBeTruthy();
    expect(toolbar?.children).toHaveLength(3);
    expect(toolbar?.querySelectorAll("select")).toHaveLength(2);
    expect(toolbar?.querySelector(".swap-button")).toBeTruthy();
  });

  it("swaps the two runs", async () => {
    await renderTwoRuns();

    fireEvent.click(screen.getByRole("button", { name: "Swap runs" }));

    await waitFor(() => expect(apiMocks.compareRuns).toHaveBeenLastCalledWith("b", "a", expect.anything()));
  });

  it("says what each run is worth before it is compared", async () => {
    await renderTwoRuns();

    // The dropdown shows the goal; the line under it shows the size and the
    // quality, which is what decides whether the pair is worth comparing.
    expect(screen.getAllByText("1 results · 1 strong")).toHaveLength(2);
  });

  it("shows the compact row by default and the full card on request", async () => {
    await renderTwoRuns();

    // Compact: the citation labels and the details disclosure are gone. The
    // same row appears in both columns, so they were the same information
    // twice.
    expect(screen.queryByText("Profile details")).toBeNull();
    expect(screen.queryByText("Audience age")).toBeNull();
    // What carries the comparison is still there.
    expect(screen.getAllByText("@a").length).toBe(2);
    expect(screen.getAllByText("Direct fit.").length).toBe(2);

    fireEvent.click(screen.getByRole("button", { name: "Full" }));

    expect(screen.getAllByText("Profile details").length).toBe(2);
    expect(screen.getAllByText("Audience age").length).toBe(2);
  });

  it("states the empty overlap once, without a heading for it", async () => {
    await renderTwoRuns();

    expect(screen.getByText(/do not share a ranked creator/)).toBeTruthy();
    // The count is already on the overview strip above, so a heading saying
    // "Creators in both runs" above a sentence saying there are none was the
    // same fact twice.
    expect(screen.queryByText("Creators in both runs")).toBeNull();
    expect(screen.queryByText("Overlap")).toBeNull();
  });

  it("shows the review count only once a run has something to review", async () => {
    await renderTwoRuns();
    // 0 -> 0 carries no information, and it took a sixth of the strip.
    expect(screen.queryByText("Needs review")).toBeNull();

    cleanup();
    await renderTwoRuns({
      ...comparison(),
      summary_b: { ...comparison().summary_b, n_weak: 2 },
    });
    expect(screen.getByText("Needs review")).toBeTruthy();
  });
});
