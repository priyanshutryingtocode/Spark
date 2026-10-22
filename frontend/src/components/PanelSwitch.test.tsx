import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Layout } from "./Layout";

// The layout reads BackendStatus and AccountMenu, both of which fetch or read
// auth. Stubbed so these tests exercise routing and selection only.
vi.mock("../backend/BackendProvider", () => ({ useBackend: () => ({ status: "online", entered: true }) }));
vi.mock("../auth/AuthProvider", () => ({ useAuth: () => ({ user: null, isConfigured: false, signOut: vi.fn() }) }));

afterEach(() => cleanup());

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route element={<Layout />}>
          <Route path=":panel/:page" element={<div>page body</div>} />
          <Route path=":panel" element={<div>page body</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  );
}

function toggle(name: string) {
  return screen.getByRole("link", { name });
}

describe("panel switch", () => {
  it("keeps the reader on the same sub-page", () => {
    // It linked to /creators/search unconditionally, so switching panel from
    // History dropped you onto Search.
    renderAt("/companies/history");
    expect(toggle("Creators").getAttribute("href")).toBe("/creators/history");
    expect(toggle("Companies").getAttribute("href")).toBe("/companies/history");
  });

  it("preserves compare, not just the two obvious pages", () => {
    renderAt("/creators/compare");
    expect(toggle("Companies").getAttribute("href")).toBe("/companies/compare");
  });

  it("marks the active panel on every sub-page", () => {
    // NavLink matches on path prefix, and "/creators/history" does not start
    // with "/creators/search", so on two of three pages neither toggle lit up.
    for (const page of ["search", "history", "compare"]) {
      const view = renderAt(`/creators/${page}`);
      expect(toggle("Creators").className).toContain("active");
      expect(toggle("Companies").className).not.toContain("active");
      view.unmount();
    }
  });

  it("marks the company panel active on the companies routes", () => {
    renderAt("/companies/history");
    expect(toggle("Companies").className).toContain("active");
    expect(toggle("Creators").className).not.toContain("active");
  });

  it("falls back to Search from a URL with no sub-page", () => {
    renderAt("/companies");
    expect(toggle("Creators").getAttribute("href")).toBe("/creators/search");
  });

  it("exposes the selection to assistive tech", () => {
    renderAt("/creators/history");
    expect(toggle("Creators").getAttribute("aria-current")).toBe("true");
    expect(toggle("Companies").getAttribute("aria-current")).toBeNull();
  });
});
