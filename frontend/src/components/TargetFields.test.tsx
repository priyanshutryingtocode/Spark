import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TargetFields } from "./TargetFields";
import type { Brief } from "../types";

afterEach(() => cleanup());

function renderTargets(kind: "creator" | "prospect", brief: Partial<Brief> = {}) {
  const onChange = vi.fn();
  const view = render(
    <TargetFields kind={kind} values={brief} onChange={onChange} />,
  );
  return { onChange, view };
}

describe("TargetFields", () => {
  it("shows the creator fields on the creator panel", () => {
    renderTargets("creator");
    expect(screen.getByLabelText(/audience gender/i)).toBeTruthy();
    expect(screen.getByLabelText(/audience countries/i)).toBeTruthy();
    expect(screen.getByLabelText(/minimum reach/i)).toBeTruthy();
    expect(screen.queryByLabelText(/industries/i)).toBeNull();
  });

  it("shows the company fields on the company panel", () => {
    renderTargets("prospect");
    expect(screen.getByLabelText(/industries/i)).toBeTruthy();
    expect(screen.getByLabelText(/company size/i)).toBeTruthy();
    expect(screen.getByLabelText(/buyer budget/i)).toBeTruthy();
    expect(screen.queryByLabelText(/audience gender/i)).toBeNull();
  });

  it("says whether a field excludes or only ranks", () => {
    // "Excludes" and "ranks" are different promises. A user who thinks a field
    // filters when it only reorders will read the shortlist wrongly.
    renderTargets("creator");
    expect(screen.getByText(/excludes creators whose audience is outside/i)).toBeTruthy();
    expect(screen.getByText(/ranks creators whose audience leans/i)).toBeTruthy();
  });

  it("adds an age band when it is switched on", () => {
    const { onChange } = renderTargets("creator", { audience_age: [] });
    fireEvent.click(screen.getByRole("button", { name: "18-24" }));
    expect(onChange).toHaveBeenCalledWith("audience_age", ["18-24"]);
  });

  it("removes an age band when it is switched off", () => {
    const { onChange } = renderTargets("creator", { audience_age: ["18-24"] });
    fireEvent.click(screen.getByRole("button", { name: "18-24" }));
    expect(onChange).toHaveBeenCalledWith("audience_age", []);
  });

  it("marks a selected age band as pressed", () => {
    renderTargets("creator", { audience_age: ["18-24"] });
    expect(screen.getByRole("button", { name: "18-24" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "25-34" }).getAttribute("aria-pressed")).toBe("false");
  });

  it("splits a country list on commas", () => {
    const { onChange } = renderTargets("creator", { audience_countries: [] });
    fireEvent.change(screen.getByLabelText(/audience countries/i), {
      target: { value: "USA, UK , Germany" },
    });
    expect(onChange).toHaveBeenCalledWith("audience_countries", ["USA", "UK", "Germany"]);
  });

  it("converts the reach floor to a percentage", () => {
    const { onChange } = renderTargets("creator", { min_reach_ratio: 0 });
    fireEvent.change(screen.getByLabelText(/minimum reach/i), { target: { value: "25" } });
    expect(onChange).toHaveBeenCalledWith("min_reach_ratio", 0.25);
  });

  it("shows the size band it was given", () => {
    renderTargets("prospect", { target_size: [51, 200] });
    expect((screen.getByLabelText(/company size/i) as HTMLSelectElement).value).toBe("51-200");
  });

  it("sends a size band as a range", () => {
    const { onChange } = renderTargets("prospect", { target_size: null });
    fireEvent.change(screen.getByLabelText(/company size/i), { target: { value: "51-200" } });
    expect(onChange).toHaveBeenCalledWith("target_size", [51, 200]);
  });
});
