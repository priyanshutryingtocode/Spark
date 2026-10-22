import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { Layout } from "./Layout";

/* The layout reads BackendStatus and AccountMenu, both of which fetch or read
 * auth. Stubbed so these tests exercise the shell itself. */
vi.mock("../backend/BackendProvider", () => ({ useBackend: () => ({ status: "online", entered: true, checkedAt: null, wake: vi.fn(), recheck: vi.fn() }) }));
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

const shellCss = readFileSync(resolve(process.cwd(), "src/styles/shell.css"), "utf-8");
const tokensCss = readFileSync(resolve(process.cwd(), "src/styles/tokens.css"), "utf-8");

/** The declarations of one rule, by selector. */
function ruleFor(css: string, selector: string): string {
  let from = 0;
  for (;;) {
    const at = css.indexOf(selector, from);
    if (at === -1) throw new Error(`${selector} is not in the stylesheet`);
    if (css.slice(at + selector.length).trimStart().startsWith("{")) {
      const open = css.indexOf("{", at);
      const close = css.indexOf("}", open);
      return css.slice(open + 1, close);
    }
    from = at + selector.length;
  }
}

describe("navigation does not move the page", () => {
  /** The focus call on the page content, if there was one.
   *
   *  A spy records the element it was called on in `instances` and the
   *  arguments in `calls`, so the two have to be read from different places.
   *  Typed structurally rather than as a vitest generic, which varies between
   *  versions and says nothing about what is being read. */
  function focusOfPageContent(focus: { mock: { instances: unknown[]; calls: unknown[][] } }) {
    const at = focus.mock.instances.findIndex((element) => (element as HTMLElement)?.id === "main-content");
    return at === -1 ? undefined : focus.mock.calls[at]?.[0];
  }

  it("focuses the page content without scrolling to it", async () => {
    /* Focusing an element makes the browser scroll it into view: it aligns the
     * element's start edge with the top of the viewport, whenever the element
     * is not fully visible. <main> is the whole page body, so it is never
     * fully visible, so every tab change ended at exactly the topbar's height
     * -- the page was always left one topbar down, with its top hidden under
     * the sticky bar.
     *
     * The focus still announces the page change and puts the next Tab back at
     * the top of the new page; it just does not drag the viewport with it. */
    const focus = vi.spyOn(HTMLElement.prototype, "focus");
    renderAt("/creators/search");

    fireEvent.click(screen.getByRole("link", { name: "History" }));

    await waitFor(() => expect(focusOfPageContent(focus)).toBeTruthy());
    expect(focusOfPageContent(focus)).toEqual({ preventScroll: true });
    focus.mockRestore();
  });

  it("does not focus the page content on the first render", () => {
    /* The unguarded version stole focus to the account button on every page
     * load, including straight after the skip link. */
    const focus = vi.spyOn(HTMLElement.prototype, "focus");
    renderAt("/creators/search");
    expect(focusOfPageContent(focus)).toBeUndefined();
    focus.mockRestore();
  });
});

describe("a tab change starts a new page at the top", () => {
  function atScroll(y: number) {
    Object.defineProperty(window, "scrollY", { value: y, configurable: true, writable: true });
  }

  it("scrolls to the top when the tab changes", async () => {
    const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    atScroll(640);
    renderAt("/creators/search");

    fireEvent.click(screen.getByRole("link", { name: "History" }));

    await waitFor(() => expect(scrollTo).toHaveBeenCalled());
    expect(scrollTo.mock.calls[0]?.[0]).toMatchObject({ top: 0 });
    scrollTo.mockRestore();
  });

  it("scrolls to the top when the panel changes", async () => {
    /* The panel switch rewrites every route below it, so it is a page change
     * by any reasonable reading of "tab". */
    const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    atScroll(640);
    renderAt("/creators/search");

    fireEvent.click(screen.getByRole("link", { name: "Companies" }));

    await waitFor(() => expect(scrollTo).toHaveBeenCalled());
    expect(scrollTo.mock.calls[0]?.[0]).toMatchObject({ top: 0 });
    scrollTo.mockRestore();
  });

  it("does not scroll when the page is already at the top", async () => {
    /* Scrolling to a position it is already at is a no-op, and issuing it
     * anyway would ask the browser to do work for nothing. */
    const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    atScroll(0);
    renderAt("/creators/search");

    fireEvent.click(screen.getByRole("link", { name: "History" }));

    await waitFor(() => expect(screen.getByRole("link", { name: "Compare" })).toBeTruthy());
    expect(scrollTo).not.toHaveBeenCalled();
    scrollTo.mockRestore();
  });

  it("does not scroll on the first render", async () => {
    /* A reload restores the browser's own scroll position, and the page
     * should open where the reader left it, not at the top. */
    const scrollTo = vi.spyOn(window, "scrollTo").mockImplementation(() => {});
    atScroll(640);
    renderAt("/creators/search");

    await waitFor(() => expect(screen.getByRole("link", { name: "Compare" })).toBeTruthy());
    expect(scrollTo).not.toHaveBeenCalled();
    scrollTo.mockRestore();
  });
});

describe("the sticky bar and the scroll targets", () => {
  it("leaves room for the bar above the page content", () => {
    /* The skip link jumps to #main-content, which with a sticky topbar landed
     * the page's top *under* the bar, hiding the page title behind it. */
    expect(ruleFor(shellCss, ".page-content")).toMatch(/scroll-margin-top:\s*var\(--topbar-height\)/);
  });

  it("takes the bar's height from one token, so the two cannot drift", () => {
    /* The bar's own height and the scroll margin that clears it are the same
     * number. If they were written out separately they would drift the first
     * time the bar was resized. */
    expect(tokensCss).toMatch(/--topbar-height:\s*[^;]+;/);
    expect(ruleFor(shellCss, ".topbar")).toMatch(/min-height:\s*var\(--topbar-height\)/);
    expect(ruleFor(shellCss, ".topbar-inner")).toMatch(/min-height:\s*var\(--topbar-height\)/);
  });
});
