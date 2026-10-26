import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { ErrorNote, NOTE_TITLES } from "../components/SystemNote";
import { MatchDetailsPanel } from "../components/MatchDetailsPanel";
import { PageIntro } from "../components/PageIntro";
import { Skeleton } from "../components/Skeleton";
import { useResource } from "../hooks/useResource";
import { formatDay } from "../format";
import type { CorpusKind, CreatorSnapshot, ProspectSnapshot, SavedMatch, SavedMatchListResponse } from "../types";
import { PANELS, panelPath, useCorpus } from "../panels";

export function ComparePage() {
  const kind = useCorpus();
  const panel = PANELS[kind];
  const [loadedKind, setLoadedKind] = useState<CorpusKind | null>(null);
  const [matchAId, setMatchAId] = useState("");
  const [matchBId, setMatchBId] = useState("");

  const saved = useResource<SavedMatchListResponse>(
    (signal) => api.listSavedMatches(kind, { signal }),
    [kind],
    {
      fallbackError: "Could not load saved matches.",
      onLoad: (response) => {
        const items = response.items.filter((item) => item.kind === kind);
        setLoadedKind(kind);
        setMatchAId(items[0]?.saved_id ?? "");
        setMatchBId(items[1]?.saved_id ?? "");
      },
    },
  );

  const items = loadedKind === kind
    ? (saved.data?.items ?? []).filter((item) => item.kind === kind)
    : [];
  const loading = saved.loading || (loadedKind !== kind && !saved.error);
  const matchA = items.find((item) => item.saved_id === matchAId);
  const matchB = items.find((item) => item.saved_id === matchBId);

  function chooseMatch(side: "a" | "b", savedId: string) {
    if (side === "a") {
      setMatchAId(savedId);
      if (savedId === matchBId) setMatchBId(items.find((item) => item.saved_id !== savedId)?.saved_id ?? "");
    } else {
      setMatchBId(savedId);
      if (savedId === matchAId) setMatchAId(items.find((item) => item.saved_id !== savedId)?.saved_id ?? "");
    }
  }

  if (loading) return <Skeleton variant="ledger" label="Loading saved matches to compare" />;

  if (saved.error) {
    return (
      <section className="page-section">
        <ErrorNote
          title={NOTE_TITLES.archive}
          action={<button className="btn btn-ghost" type="button" onClick={saved.retry}>Retry</button>}
        >
          {saved.error}
        </ErrorNote>
      </section>
    );
  }

  if (items.length < 2) {
    return (
      <section className="page-section">
        <PageIntro
          variant="compact"
          eyebrow="Workspace / Compare"
          title="Compare saved matches"
          description={`Review saved ${panel.plural} side by side.`}
        />
        <EmptyState
          icon="compare"
          index="SAVED MATCHES"
          title={items.length === 0 ? "Save matches to compare." : "Save one more match to compare."}
          body={`Save at least two ${panel.plural} from their profile views. They will appear here for a side-by-side review.`}
        />
        <Link className="btn btn-secondary" to={panelPath(kind)}>Find {panel.plural}</Link>
      </section>
    );
  }

  return (
    <section className="page-section compare-page">
      <PageIntro
        variant="compact"
        eyebrow="Workspace / Compare"
        title="Compare saved matches"
        description={`Review two saved ${panel.plural} side by side, with profile evidence and the brief each was saved from.`}
      />

      <div className="compare-toolbar">
        <SavedMatchSelect
          id="compare-saved-a"
          label="Saved match A"
          value={matchAId}
          items={items}
          disabledId={matchBId}
          onChange={(id) => chooseMatch("a", id)}
        />
        <button
          className="swap-button"
          type="button"
          aria-label="Swap saved matches"
          onClick={() => {
            setMatchAId(matchBId);
            setMatchBId(matchAId);
          }}
        >
          Swap
        </button>
        <SavedMatchSelect
          id="compare-saved-b"
          label="Saved match B"
          value={matchBId}
          items={items}
          disabledId={matchAId}
          onChange={(id) => chooseMatch("b", id)}
        />
      </div>

      {matchA && matchB && (
        <div className="compare-columns">
          <SavedMatchColumn label="Saved match A" item={matchA} titleId="compare-match-a-title" />
          <SavedMatchColumn label="Saved match B" item={matchB} titleId="compare-match-b-title" />
        </div>
      )}
    </section>
  );
}

function SavedMatchSelect({
  id, label, value, items, disabledId, onChange,
}: {
  id: string;
  label: string;
  value: string;
  items: SavedMatch[];
  disabledId: string;
  onChange: (savedId: string) => void;
}) {
  return (
    <div className="compare-select">
      <label className="compare-select-label" htmlFor={id}>{label}</label>
      <select id={id} value={value} onChange={(event) => onChange(event.target.value)}>
        {items.map((item) => (
          <option key={item.saved_id} value={item.saved_id} disabled={item.saved_id === disabledId}>
            {candidateName(item)} · Saved {formatDay(item.created_at)}
          </option>
        ))}
      </select>
    </div>
  );
}

function SavedMatchColumn({ label, item, titleId }: { label: string; item: SavedMatch; titleId: string }) {
  return (
    <section className="compare-column" aria-label={label}>
      <div className="compare-column-heading">
        <span className="eyebrow">{label}</span>
        <span>Rank #{String(item.ranked.rank).padStart(2, "0")} · Saved {formatDay(item.created_at)}</span>
      </div>
      <p className="compare-brief">{item.brief.goal}</p>
      {item.brief.product_context && (
        <p className="compare-brief">
          Product context: {item.brief.product_context.category}
          {item.brief.product_context.target_audience && ` · ${item.brief.product_context.target_audience}`}
        </p>
      )}
      <MatchDetailsPanel
        kind={item.kind}
        dataset={item.dataset ?? "synthetic"}
        candidate={item.candidate}
        entry={item.ranked}
        titleId={titleId}
      />
    </section>
  );
}

function candidateName(item: SavedMatch): string {
  return item.kind === "creator"
    ? (item.candidate as CreatorSnapshot).name || (item.candidate as CreatorSnapshot).handle
    : (item.candidate as ProspectSnapshot).name;
}
