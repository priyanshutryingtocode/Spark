import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { SummaryMetrics } from "./RunSummary";
import type { RunSummary } from "../types";

// No global setup file, so each suite cleans up after itself -- ComparePage's
// suite does the same. Without it a rendered strip outlives its test and the
// next `getByText` finds two.
afterEach(() => cleanup());

const creator: RunSummary = {
  n_results: 12, avg_match_pct: 63.4, n_strong: 5, n_weak: 2,
  avg_engagement_pct: 4.1, median_followers: 24_500,
};

const prospect: RunSummary = {
  kind: "prospect",
  n_results: 8, avg_match_pct: 71.2, n_strong: 3, n_weak: 1,
  median_headcount: 1_200,
};

describe("SummaryMetrics", () => {
  it("renders the server's cells rather than labels of its own", () => {
    render(<SummaryMetrics summary={{
      ...creator,
      cells: [
        { key: "n_results", label: "Good matches", caption: "of the shortlist", value: "5/12", primary: true },
        { key: "avg_match_pct", label: "Avg similarity", caption: "cosine vs. brief", value: "63.4%" },
      ],
    }} />);

    // A label the component no longer contains. If it rendered its own, this
    // test would fail the moment the backend renamed a cell.
    expect(screen.getByText("Good matches")).toBeTruthy();
    expect(screen.getByText("of the shortlist")).toBeTruthy();
    expect(screen.getByText("5/12")).toBeTruthy();
    expect(screen.queryByText("strong fits")).toBeNull();
  });

  it("renders a prospect strip without engagement or reach", () => {
    render(<SummaryMetrics summary={{
      ...prospect,
      cells: [
        { key: "n_results", label: "Quality", caption: "strong fits", value: "3/8", primary: true },
        { key: "median_headcount", label: "Median headcount", caption: "employees", value: "1K" },
      ],
    }} />);

    expect(screen.getByText("Median headcount")).toBeTruthy();
    expect(screen.getByText("employees")).toBeTruthy();
    // Absent from the payload, so it must not be synthesised as 0.
    expect(screen.queryByText("Avg engagement")).toBeNull();
    expect(screen.queryByText("Median reach")).toBeNull();
  });

  it("falls back to the flat keys for a summary stored before cells existed", () => {
    render(<SummaryMetrics summary={creator} />);

    expect(screen.getByText("5/12")).toBeTruthy();
    expect(screen.getByText("63.4%")).toBeTruthy();
    expect(screen.getByText("4.1%")).toBeTruthy();
    expect(screen.getByText("25K")).toBeTruthy();
  });

  it("picks the size metric from whichever key is present", () => {
    render(<SummaryMetrics summary={prospect} />);
    expect(screen.getByText("1K")).toBeTruthy();
    expect(screen.queryByText("25K")).toBeNull();
  });

  it("reveals a cell's explanation on click and toggles it back", () => {
    render(<SummaryMetrics summary={{
      ...creator,
      cells: [
        { key: "n_results", label: "Quality", caption: "strong fits", value: "5/12", primary: true },
        {
          key: "avg_match_pct", label: "Avg similarity", caption: "cosine vs. brief",
          value: "63.4%", explanation: "An embedding distance, not a fit score.",
        },
      ],
    }} />);

    const toggle = screen.getByRole("button", { name: /avg similarity/i });
    // Closed by default: the caveat is the thing most likely to be misread, so
    // it must not sit in the strip permanently.
    expect(screen.queryByText(/embedding distance/i)).toBeNull();
    expect(toggle.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(toggle);
    expect(screen.getByText(/embedding distance/i)).toBeTruthy();
    expect(toggle.getAttribute("aria-expanded")).toBe("true");

    fireEvent.click(toggle);
    expect(screen.queryByText(/embedding distance/i)).toBeNull();
  });

  it("gives the explanation toggle a name for assistive tech", () => {
    render(<SummaryMetrics summary={{
      ...creator,
      cells: [{
        key: "avg_match_pct", label: "Avg similarity", caption: "cosine vs. brief",
        value: "63.4%", explanation: "Not a fit score.",
      }],
    }} />);

    // A <dt> is not focusable, so this was previously mouse-only.
    expect(screen.getByRole("button", { name: /avg similarity/i })).toBeTruthy();
  });

  it("does not render a toggle for a cell with no explanation", () => {
    render(<SummaryMetrics summary={{
      ...creator,
      cells: [{ key: "n_results", label: "Quality", caption: "strong fits", value: "5/12", primary: true }],
    }} />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});