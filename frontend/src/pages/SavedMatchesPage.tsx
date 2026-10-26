import { useState } from "react";
import { Link } from "react-router-dom";

import { api, ApiError } from "../api/client";
import { CandidateAvatar } from "../components/resultShared";
import { EmptyState } from "../components/EmptyState";
import { ErrorNote, NOTE_TITLES } from "../components/SystemNote";
import { Icon } from "../components/Icon";
import { MatchDetailsPanel } from "../components/MatchDetailsPanel";
import { PageIntro } from "../components/PageIntro";
import { Skeleton } from "../components/Skeleton";
import { useResource } from "../hooks/useResource";
import { PANELS, panelPath, useCorpus } from "../panels";
import { formatDay } from "../format";
import type { CorpusKind, CreatorSnapshot, ProspectSnapshot, SavedMatch, SavedMatchListResponse, SavedMatchStatus } from "../types";

const statusLabels: Record<SavedMatchStatus, string> = {
  to_review: "To review",
  contacted: "Contacted",
  in_conversation: "In conversation",
  partnered: "Partnered",
  passed: "Passed",
};

export function SavedMatchesPage() {
  const kind = useCorpus();
  const panel = PANELS[kind];
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [loadedKind, setLoadedKind] = useState<CorpusKind | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [workflowError, setWorkflowError] = useState<string | null>(null);
  const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({});
  const [updatingSavedId, setUpdatingSavedId] = useState<string | null>(null);
  const saved = useResource<SavedMatchListResponse>(
    (signal) => api.listSavedMatches(kind, { signal }),
    [kind],
    {
      fallbackError: "Could not load your saved matches.",
      onLoad: () => setLoadedKind(kind),
    },
  );

  const items = loadedKind === kind ? (saved.data?.items ?? []).filter((item) => item.kind === kind) : [];
  const loading = saved.loading || loadedKind !== kind;
  const selected = items.find((item) => item.saved_id === selectedId) ?? items[0];

  async function remove(savedId: string) {
    if (deletingId) return;
    setDeletingId(savedId);
    setDeleteError(null);
    try {
      await api.deleteSavedMatch(savedId);
      saved.setData({ items: items.filter((item) => item.saved_id !== savedId) });
      if (selectedId === savedId) setSelectedId(null);
    } catch (caught) {
      setDeleteError(caught instanceof ApiError ? caught.message : "Could not remove the saved match.");
    } finally {
      setDeletingId(null);
    }
  }

  async function updateSavedMatch(item: SavedMatch, update: { status?: SavedMatchStatus; note?: string }) {
    if (updatingSavedId) return;
    setUpdatingSavedId(item.saved_id);
    setWorkflowError(null);
    try {
      const updated = await api.updateSavedMatch(item.saved_id, update);
      saved.setData({
        items: (saved.data?.items ?? []).map((current) => current.saved_id === updated.saved_id ? updated : current),
      });
      setNoteDrafts((current) => ({ ...current, [updated.saved_id]: updated.note }));
    } catch (caught) {
      setWorkflowError(caught instanceof ApiError ? caught.message : "Could not update this saved match.");
    } finally {
      setUpdatingSavedId(null);
    }
  }

  return (
    <section className="page-section">
      <PageIntro
        eyebrow="Workspace / Saved"
        title="Saved matches"
        description={`The ${panel.plural} you chose to keep, collected across matching runs.`}
        meta={(
          <button className="btn btn-secondary" type="button" disabled={saved.loading} onClick={saved.retry}>
            {saved.loading ? "Refreshing..." : "Refresh"}
          </button>
        )}
      />

      {(saved.error || deleteError) && (
        <ErrorNote
          title={NOTE_TITLES.archive}
          action={saved.error
            ? <button className="btn btn-ghost" type="button" onClick={saved.retry}>Retry</button>
            : undefined}
        >
          {deleteError ?? saved.error}
        </ErrorNote>
      )}
      {loading && <Skeleton variant="ledger" label="Loading saved matches" />}

      {!loading && !saved.error && items.length === 0 && (
        <EmptyState
          icon="bookmark"
          index="SHORTLIST"
          title="Keep a match for later."
          body="Save a creator or company from its match profile and it will be available here."
          steps={[`Browse ${panel.plural}`, "Review profile evidence", "Save matches"]}
        />
      )}

      {items.length > 0 && (
        <div className="saved-matches-layout">
          <section className="saved-match-list" aria-label="Your saved matches">
            <div className="ledger-heading"><span>{panel.plural}</span><span>{items.length}</span></div>
            {items.map((item) => {
              const name = item.kind === "creator"
                ? (item.candidate as CreatorSnapshot).name || (item.candidate as CreatorSnapshot).handle
                : (item.candidate as ProspectSnapshot).name;
              const active = selected?.saved_id === item.saved_id;
              return (
                <article className={`saved-match-row ${active ? "saved-match-row-active" : ""}`} key={item.saved_id}>
                  <button
                    className="saved-match-open"
                    type="button"
                    aria-pressed={active}
                    onClick={() => setSelectedId(item.saved_id)}
                  >
                    <CandidateAvatar name={name} kind={item.kind} />
                    <span className="saved-match-copy">
                      <strong>{name}</strong>
                      <span>{item.brief.goal}</span>
                      <small>{statusLabels[item.status]}</small>
                      <small>Rank #{String(item.ranked.rank).padStart(2, "0")} · Saved {formatDay(item.created_at)}</small>
                    </span>
                  </button>
                  <button
                    className="btn btn-ghost btn-danger-ghost saved-match-remove"
                    type="button"
                    disabled={Boolean(deletingId)}
                    aria-busy={deletingId === item.saved_id}
                    aria-label={`Remove ${name} from saved matches`}
                    onClick={() => void remove(item.saved_id)}
                  >
                    <Icon name="trash" size={13} />
                  </button>
                </article>
              );
            })}
          </section>
          {selected && (
            <div className="saved-detail-column">
              <MatchDetailsPanel
                kind={selected.kind}
                dataset={selected.dataset ?? "synthetic"}
                candidate={selected.candidate}
                entry={selected.ranked}
              />
              <section className="saved-workflow" aria-labelledby="saved-workflow-title">
                <div className="saved-workflow-heading">
                  <h2 id="saved-workflow-title">Shortlist progress</h2>
                  <span>{statusLabels[selected.status]}</span>
                </div>
                <label className="brief-field" htmlFor="saved-match-status">
                  <span>Status</span>
                  <select
                    id="saved-match-status"
                    value={selected.status}
                    disabled={updatingSavedId === selected.saved_id}
                    onChange={(event) => void updateSavedMatch(selected, { status: event.target.value as SavedMatchStatus })}
                  >
                    {Object.entries(statusLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                  </select>
                </label>
                <label className="brief-field" htmlFor="saved-match-note">
                  <span>Notes</span>
                  <textarea
                    id="saved-match-note"
                    rows={3}
                    maxLength={2000}
                    value={noteDrafts[selected.saved_id] ?? selected.note}
                    placeholder="Add context for your next step."
                    onChange={(event) => setNoteDrafts((current) => ({ ...current, [selected.saved_id]: event.target.value }))}
                  />
                </label>
                <button
                  className="btn btn-secondary"
                  type="button"
                  disabled={updatingSavedId === selected.saved_id || (noteDrafts[selected.saved_id] ?? selected.note) === selected.note}
                  onClick={() => void updateSavedMatch(selected, { note: noteDrafts[selected.saved_id] ?? selected.note })}
                >
                  {updatingSavedId === selected.saved_id ? "Saving..." : "Save note"}
                </button>
                {workflowError && <p className="saved-workflow-error" role="alert">{workflowError}</p>}
              </section>
            </div>
          )}
        </div>
      )}
      <div className="saved-match-footer">
        <Link to={panelPath(kind)}>Find more {panel.plural} <Icon name="arrow-right" size={13} /></Link>
      </div>
    </section>
  );
}
