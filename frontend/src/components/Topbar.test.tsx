import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { Layout } from "./Layout";

/* The layout reads BackendStatus and AccountMenu, both of which fetch or read
 * auth. Stubbed so these tests exercise the bar itself. */
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


/* Vitest runs from the package root, so the stylesheet sits where it is
 * imported from. */
const shellCss = readFileSync(resolve(process.cwd(), "src/styles/shell.css"), "utf-8");

/** The declarations of one rule, by selector. A selector that is only a prefix
 *  of another (".account-trigger" of ".account-trigger-name") is skipped rather
 *  than matched. */
function ruleFor(css: string, selector: string): string {
  let from = 0;
  for (;;) {
    const at = css.indexOf(selector, from);
    if (at === -1) throw new Error(`${selector} is not in shell.css`);
    if (css.slice(at + selector.length).trimStart().startsWith("{")) {
      const open = css.indexOf("{", at);
      const close = css.indexOf("}", open);
      return css.slice(open + 1, close);
    }
    from = at + selector.length;
  }
}

describe("the topbar", () => {
  it("spans the same measure as the page below it", () => {
    /* The gutter is subtracted once, by the topbar's own padding. The inner
     * subtracted it a second time, which made the bar's content narrower than
     * the page's and pushed it to the right of the page's left edge: 800px of
     * content in a 1360px page at 1920px, and 160px at 2560px. The bar read as
     * a strip of chips floating in a wide band.
     *
     * jsdom does no layout, so this is checked where the bug lives -- in the
     * declaration itself. */
    const width = ruleFor(shellCss, ".topbar-inner");
    expect(width).toMatch(/width:/);
    expect(width).not.toContain("--page-gutter");
    // And it is the content width, capped by the space it actually has.
    expect(width).toContain("--content-width");
    expect(width).toContain("100%");
  });

  it("carries one framed control, so the bar has a hierarchy", () => {
    /* Five bordered elements -- the panel switch, the nav, the active nav
     * link inside it, the status and the account -- all the same shape, with
     * one nested inside another. The panel switch is the mode control and the
     * only one that earns a visible frame; the rest are bare surfaces.
     *
     * The status and the account keep a transparent border rather than no
     * border: it reserves the space so the layout does not shift the moment
     * the backend goes down and the status grows an edge. */
    const css = shellCss;
    expect(ruleFor(css, ".main-nav")).toMatch(/border:\s*0/);
    expect(ruleFor(css, ".nav-link")).toMatch(/border:\s*0/);
    expect(ruleFor(css, ".backend-status")).toMatch(/border:\s*1px solid transparent/);
    expect(ruleFor(css, ".account-trigger")).toMatch(/border:\s*1px solid transparent/);
    // The panel switch keeps a visible edge, which is what makes it the one
    // framed object the eye reads as a control.
    expect(ruleFor(css, ".panel-switch")).toMatch(/border:\s*1px solid var\(--rule-strong\)/);
  });

  it("shows the backend status in plain language", () => {
    /* It was uppercase mono with a signal-blue action, which made the bar's
     * most expendable element compete with the panel switch for the accent. */
    renderAt("/creators/search");
    const status = screen.getByRole("button", { name: /Backend online/ });
    expect(status.textContent).toContain("Backend online");
    expect(status.textContent).toContain("Recheck");
  });

  it("marks the active page in the nav and the active panel in the switch", () => {
    renderAt("/companies/compare");
    const nav = screen.getByRole("link", { name: "Compare" });
    expect(nav.className).toContain("active");
    expect(screen.getByRole("link", { name: "Search" }).className).not.toContain("active");
    // The panel is a mode, not a page: it takes the accent rather than the
    // nav's neutral active treatment.
    expect(screen.getByRole("link", { name: "Companies" }).className).toContain("active");
  });
});

describe("the segmented control's segments", () => {
  const css = readFileSync(resolve(process.cwd(), "src/styles/shell.css"), "utf-8");
  const compareCss = readFileSync(resolve(process.cwd(), "src/styles/compare.css"), "utf-8");

  it("splits the track into two equal halves, with no floor to make them differ", () => {
    /* `1fr` floors each track at its content's min-content size, so the track
     * holding the longer word got more room and the two segments came out
     * different widths. The indicator is exactly half the track, and half is
     * only one segment when the segments are equal. */
    const rule = ruleFor(css, ".panel-switch");
    expect(rule).toMatch(/grid-template-columns:\s*repeat\(2,\s*minmax\(0,\s*1fr\)\)/);
    // Not the floored form.
    expect(rule).not.toMatch(/grid-template-columns:\s*1fr 1fr/);
    expect(rule).not.toMatch(/grid-template-columns:[^;]*minmax\(auto/);
  });

  it("has a definite width, so the halves are real halves", () => {
    const rule = ruleFor(css, ".panel-switch");
    expect(rule).toMatch(/width:\s*max-content/);
    // The floor is what guarantees the longer word has room in its half.
    expect(rule).toMatch(/min-width:/);
  });

  it("measures the indicator as exactly one segment", () => {
    /* The indicator is an absolutely positioned child, so its percentage is
     * measured against the track's padding box -- which is 6px wider than the
     * content box the segments live in, because of the switch's own 3px
     * padding either side. Half the padding box is therefore 3px more than
     * half the content box, so `50% - 3px` is one segment exactly. */
    const rule = ruleFor(css, ".panel-switch::after");
    expect(rule).toMatch(/width:\s*calc\(50% - 3px\)/);
    // And it starts on the content box's left edge, which is the first
    // segment's left edge.
    expect(rule).toMatch(/left:\s*3px/);
  });

  it("gives the shorter control its own floor", () => {
    /* The Compare page's Compact/Full switch uses the same classes, and its
     * labels are much shorter -- half of the topbar's floor would leave
     * "Compact" with no room. */
    expect(ruleFor(compareCss, ".compare-view-switch")).toMatch(/min-width:/);
  });

  it("gives pseudo-elements the same box model as elements", () => {
    /* The universal selector does not match pseudo-elements, so `*` alone left
     * them on the initial `content-box` -- and that is not academic.
     *
     * The panel switch's sliding indicator is a ::after with a width and a 1px
     * border. On content-box its border-box was 2px wider than the segment it
     * was meant to fill, and `translateX(100%)` moves an element by its
     * border-box, so it also landed 2px past where it belonged: the pill ran
     * into the switch's edge with no gap on the right of "Companies", and had
     * a gap on the left of "Creators". The summary chevron and the account
     * caret were off by their borders too.
     *
     * This is the one failure in this file that a stylesheet assertion can
     * catch and a DOM test cannot, because it only shows up in layout. */
    const base = readFileSync(resolve(process.cwd(), "src/styles/base.css"), "utf-8");
    expect(base).toMatch(/\*,\s*\*::before,\s*\*::after\s*\{[^}]*box-sizing:\s*border-box/);
  });

  it("gives the segment buttons no background of their own", () => {
    /* The Compare page's Compact/Full control uses <button>s, and a button's
     * default background is the browser's grey button face, which rendered as
     * a white block behind the segment. The topbar's toggles are links, which
     * have no background of their own, so the reset is invisible there. */
    expect(ruleFor(css, ".panel-toggle")).toMatch(/background:\s*none/);
  });

  it("gives the bar room to breathe on a narrow screen", () => {
    /* The four tracks -- brand, panel switch, nav, account -- need about
     * 970px between them, and only the nav's column can give ground because
     * its links are nowrap. Below that the bar overflowed the viewport by up
     * to 60px. The status's words are the expendable part: the dot still
     * carries the state, and the button's name and title still carry the
     * sentence. */
    const responsive = readFileSync(resolve(process.cwd(), "src/styles/responsive.css"), "utf-8");
    expect(responsive).toMatch(/@media \(max-width: 980px\)/);
    expect(responsive).toMatch(/\.backend-status-label, \.backend-status-action \{ display: none; \}/);
  });
});
