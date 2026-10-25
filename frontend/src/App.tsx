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
import { SavedMatchesPage } from "./pages/SavedMatchesPage";
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
                  {/* Panel pages have shareable URLs; bare panel paths redirect to Search. */}
                  {Object.values(PANELS).map((panel) => (
                    <Route key={panel.slug} path={panel.slug}>
                      <Route index element={<Navigate to={panelPath(panel.kind)} replace />} />
                      {PAGES.map((page) => (
                        <Route key={page.slug} path={page.slug} element={<PageFor slug={page.slug} />} />
                      ))}
                    </Route>
                  ))}

                  {/* Preserve legacy URLs; pre-panel runs belong to Creators. */}
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
  if (slug === "saved") return <SavedMatchesPage />;
  if (slug === "history") return <HistoryPage />;
  if (slug === "compare") return <ComparePage />;
  return <SearchPage />;
}
