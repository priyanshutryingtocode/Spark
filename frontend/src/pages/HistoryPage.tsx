import { useState } from "react";
import { Link } from "react-router-dom";

import { api, ApiError } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { ErrorNote, NOTE_TITLES } from "../components/SystemNote";
import { PageIntro } from "../components/PageIntro";
import { ResultList } from "../components/ResultList";
import { Icon } from "../components/Icon";
import { Skeleton } from "../components/Skeleton";
import { RunContext } from "../components/RunContext";
import { SummaryMetrics } from "../components/RunSummary";
import { WarningBanner } from "../components/WarningBanner";
import { useResource } from "../hooks/useResource";
import { useEffect } from "react";

import { PANELS, panelPath, useCorpus } from "../panels";
import { useRuns } from "../hooks/useRuns";
import { formatDay } from "../format";
import type { RunDetail } from "../types";

export function HistoryPage() {
  const kind = useCorpus();
  const panel = PANELS[kind];
  const { items, isLoading, isLoadingMore, hasMore, error, loadMore, remove, refresh } = useRuns(kind);
  // Which run is open, not the run itself. Keying the fetch off an id means a
  // second click supersedes the first -- the old `setSelected(await getRun(a))`
  // had no such guard, so opening A then B quickly could land A's slower
  // response on top of B.
  const [openRunId, setOpenRunId] = useState<string | null>(null);

  const detail = useResource<RunDetail>(
    (signal) => api.getRun(openRunId!, { signal }),
    [openRunId, kind],
    { enabled: openRunId !== null, fallbackError: "Could not load the run." },
  );
  // Only render a run that belongs to the panel on screen. React Router
  // preserves this component's state across a route change, so on the render
  // where `kind` flips the previous panel's snapshot is still loaded -- and
  // clearing the id from an effect is too late, because that render already
  // handed a creator to the company card and threw. Guarding here fixes the
  // render itself; the id is cleared below once React is past it.
  const loaded = detail.data;
  const selected = loaded?.kind === kind ? loaded : null;
  useEffect(() => setOpenRunId(null), [kind]);

  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  // Delete had no in-flight state, so a double-click sent two DELETEs and the
  // second one raced the row out of the list it had already filtered.
  const [deletingId, setDeletingId] = useState<string | null>(null);

  async function deleteRun(runId: string) {
    if (deletingId) return;
    if (!window.confirm("Delete this match run? Saved matches from it will remain in your shortlist.")) return;
    setDeletingId(runId);
    try {
      // `remove` re-throws after recording the message in the shared error slot,
      // so the failure is already on screen; this only has to not reject.
      await remove(runId);
      if (openRunId === runId) setOpenRunId(null);
    } catch {
      return;
    } finally {
      setDeletingId(null);
    }
  }

  function exportRun() {
    if (exporting) return;
    setExporting(true);
    setExportError(null);
    void api.downloadRun(selected!.run_id)
      .catch((caught) => setExportError(caught instanceof ApiError ? caught.message : "Could not export the run."))
      .finally(() => setExporting(false));
  }

  return (
    <section className="page-section">
      <PageIntro
        eyebrow="Workspace / History"
        title="Past searches"
        description={`Review previous briefs and the ${panel.plural} returned for each match run.`}
        meta={(
          <button className="btn btn-secondary" type="button" disabled={isLoading} onClick={() => void refresh()}>
            {isLoading ? "Refreshing..." : "Refresh"}
          </button>
        )}
      />

      {(error || detail.error) && <ErrorNote title={NOTE_TITLES.archive}>{error ?? detail.error}</ErrorNote>}
      {exportError && <ErrorNote title={NOTE_TITLES.export}>{exportError}</ErrorNote>}
      {isLoading && <Skeleton variant="ledger" />}

      <div className="history-layout">
        <aside className="history-ledger">
          <div className="ledger-heading">
            <span>Match runs</span>
            {/* The count of what is loaded, with a "+" when older runs are
                still behind "Load older runs". */}
            <span>{items.length}{hasMore ? "+" : ""}</span>
          </div>
          <div className="history-list">
            {!isLoading && !items.length && <div className="empty-ledger"><p>No past searches yet.</p><Link to={panelPath(kind)}>Run a match <Icon name="arrow-right" size={13} /></Link></div>}
            {items.map((item) => (
              <article className={`history-row ${selected?.run_id === item.run_id ? "history-row-active" : ""}`} key={item.run_id}>
                <button className="history-open" type="button" aria-current={openRunId === item.run_id ? "true" : undefined} onClick={() => setOpenRunId(item.run_id)}>
                  {/* The goal first: it is what the list is scanned for. The date
                      was above it, in the largest type, and it was the least
                      important thing in the row. */}
                  <strong className="history-goal" title={item.brief.goal}>{item.brief.goal}</strong>
                  <span className="history-meta">
                    <span className="history-date">{formatDay(item.created_at)}</span>
                    <i />
                    {item.n_results} results
                    <i />
                    {item.n_strong} strong
                    {item.has_warnings && <b>Notes</b>}
                  </span>
                </button>
                <button
                  className="btn btn-ghost btn-danger-ghost delete-button"
                  type="button"
                  disabled={deletingId === item.run_id}
                  aria-busy={deletingId === item.run_id}
                  aria-label={`Delete run: ${item.brief.goal}`}
                  onClick={() => void deleteRun(item.run_id)}
                >
                  <Icon name="trash" size={13} />
                </button>
              </article>
            ))}
            {hasMore && <button className="btn btn-ghost full-width" type="button" disabled={isLoadingMore} onClick={() => void loadMore()}>{isLoadingMore ? "Loading..." : "Load older runs"}</button>}
          </div>
        </aside>

        <div className="history-detail">
          {/* aria-busy/live: this replaced the detail pane with a heading, so a
           * sighted user saw progress while a screen-reader user heard nothing
           * and focus stayed on the ledger button they had just pressed. */}
          {detail.loading && <EmptyState title="Opening shortlist" busy />}
          {!detail.loading && selected && (
            <>
              <RunContext
                run={selected}
                label="Run detail"
                exporting={exporting}
                onExport={exportRun}
              />
              <WarningBanner warnings={selected.warnings} />
              <SummaryMetrics summary={selected.summary} compact />
              <ResultList kind={kind} run={selected} />
            </>
          )}
          {!detail.loading && !selected && (
            <EmptyState
              icon="history"
              index="SELECT"
              title="Choose a saved run"
              body={`Open a shortlist to inspect its ranked ${panel.plural} and export the result.`}
            />
          )}
        </div>
      </div>
    </section>
  );
}
