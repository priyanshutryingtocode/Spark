import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AuthProvider } from "./auth/AuthProvider";
import { ProtectedRoute } from "./auth/ProtectedRoute";
import { BackendProvider } from "./backend/BackendProvider";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { Layout } from "./components/Layout";
import { ComparePage } from "./pages/ComparePage";
import { HistoryPage } from "./pages/HistoryPage";
import { LoginPage } from "./pages/LoginPage";
import { LandingPage } from "./pages/LandingPage";
import { SearchPage } from "./pages/SearchPage";
import { PAGES, PANELS, panelPath } from "./panels";
import "./styles.css";

export function App() {
  return (
    <AuthProvider>
      <BackendProvider>
        <BrowserRouter>
          <ErrorBoundary>
            <Routes>
              <Route path="/" element={<LandingPage />} />
              <Route path="/login" element={<LoginPage />} />
              <Route path="/signup" element={<LoginPage initialMode="signup" />} />
              <Route element={<ProtectedRoute />}>
                <Route element={<Layout />}>
                  {/* One route per sub-page per panel, so a Companies page is a
                    * shareable link and the back button means what it says.
                    * The `index` child redirects a bare /creators, which
                    * otherwise matched this route and rendered an empty shell. */}
                  {Object.values(PANELS).map((panel) => (
                    <Route key={panel.slug} path={panel.slug}>
                      <Route index element={<Navigate to={panelPath(panel.kind)} replace />} />
                      {PAGES.map((page) => (
                        <Route key={page.slug} path={page.slug} element={<PageFor slug={page.slug} />} />
                      ))}
                    </Route>
                  ))}

                  {/* Pre-split URLs, kept working. Every run stored before the
                    * panels existed is a creator run, and the six in the table
                    * are reachable from these links, in bookmarks and in any
                    * shared URL. A silent 404 would be a data-loss bug that
                    * looks like a broken app. */}
                  <Route path="search" element={<Navigate to={panelPath("creator", "search")} replace />} />
                  <Route path="history" element={<Navigate to={panelPath("creator", "history")} replace />} />
                  <Route path="compare" element={<Navigate to={panelPath("creator", "compare")} replace />} />

                  <Route path="*" element={<Navigate to={panelPath("creator")} replace />} />
                </Route>
              </Route>
            </Routes>
          </ErrorBoundary>
        </BrowserRouter>
      </BackendProvider>
    </AuthProvider>
  );
}

function PageFor({ slug }: { slug: (typeof PAGES)[number]["slug"] }) {
  if (slug === "history") return <HistoryPage />;
  if (slug === "compare") return <ComparePage />;
  return <SearchPage />;
}
