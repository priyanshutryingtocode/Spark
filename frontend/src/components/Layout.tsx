import { useEffect, useRef } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useAuth } from "../auth/AuthProvider";
import { PAGES, PANELS, pageFromPath, panelPath, useCorpus } from "../panels";
import { AccountMenu } from "./AccountMenu";
import { BackendStatus } from "./BackendStatus";
import { Icon } from "./Icon";

/** The nav's three pages, each with its mark. */
const NAV_ICONS = { search: "search", history: "history", compare: "compare" } as const;

export function Layout() {
  const { user, signOut, isConfigured } = useAuth();
  const location = useLocation();
  const mainRef = useRef<HTMLElement>(null);
  const isFirstRender = useRef(true);
  const kind = useCorpus();

  useEffect(() => {
    /* Nothing announced a page change. Focusing <main> also puts the next Tab
     * back at the top of the new page. Skipped on first render. */
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    /* preventScroll, because focusing scrolls.
     *
     * The browser brings a focused element into view by aligning its start
     * edge with the top of the viewport, and <main> is the whole page body --
     * it is never fully visible, so the alignment always happens. Every tab
     * change therefore ended at exactly the topbar's height: the page was
     * always left one topbar down, with its top hidden under the sticky bar.
     *
     * The focus still does its job. It announces the new page and puts the
     * next Tab back at the top of it; it just no longer drags the viewport
     * with it. The scroll below is the one the page should actually make. */
    mainRef.current?.focus({ preventScroll: true });
    /* A tab change is a new page, and a new page starts at the top. Scrolling
     * to a position that is already the top is a no-op, so it is skipped
     * rather than issued. */
    if (window.scrollY !== 0) {
      window.scrollTo({ top: 0, left: 0, behavior: "instant" });
    }
  }, [location.pathname]);

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Skip to content</a>
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand-lockup">
            {/* Decorative: the wordmark beside it already names the product, so an
                img here would announce "Spark" twice. alt="" is what makes a
                browser treat it as decoration rather than as a missing label. */}
            <img className="brand-mark" src="/logo-mark.png" alt="" width={36} height={36} />
            <span className="brand-name">Spark</span>
          </div>
          {/* A segmented control, not two sets of nav links: the panels are
           * alternatives, and more nav items imply you can be on both. */}
          <div
            className="panel-switch"
            role="group"
            aria-label="What to match against"
            /* The indicator slides between two equal columns, so it needs to know
               which one is live. */
            data-active={kind}
          >
            {Object.values(PANELS).map((option) => {
              // The target keeps the current sub-page, so switching panel on
              // History lands on History rather than dropping to Search.
              const to = panelPath(option.kind, pageFromPath(location.pathname));
              // Selected state is computed, not NavLink's `isActive`: NavLink
              // matches on path prefix, and "/creators/history" does not start
              // with "/creators/search", so neither toggle lit up on two of the
              // three pages. `end` would not help either -- the paths are
              // siblings, not nested.
              const selected = option.kind === kind;
              return (
                <NavLink
                  key={option.kind}
                  to={to}
                  className={selected ? "panel-toggle active" : "panel-toggle"}
                  aria-current={selected ? "true" : undefined}
                >
                  {option.label}
                </NavLink>
              );
            })}
          </div>
          <nav className="main-nav" aria-label="Primary navigation">
            {PAGES.map((page) => (
              <NavLink
                key={page.slug}
                to={panelPath(kind, page.slug)}
                className={({ isActive }) => isActive ? "nav-link active" : "nav-link"}
              >
                <Icon name={NAV_ICONS[page.slug]} size={14} />
                {page.label}
              </NavLink>
            ))}
          </nav>
          <div className="account-slot">
            <BackendStatus />
            {isConfigured && user && <AccountMenu user={user} signOut={signOut} />}
          </div>
        </div>
      </header>
      {/* tabindex="-1" so the skip link can actually move focus here, not just
       * scroll to it -- several browsers ignore focus() on a non-focusable
       * element, which left the target of the skip link unreliable. */}
      <main id="main-content" className="page-content" tabIndex={-1} ref={mainRef}>
        {/* No `context`: pages read the panel from the URL via `useCorpus()`, and
         * a second copy of that fact is the copy that can disagree. */}
        <Outlet />
      </main>
    </div>
  );
}