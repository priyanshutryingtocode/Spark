import { useMemo, useState } from "react";

import { api } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { ErrorNote, InfoNote, NOTE_TITLES } from "../components/SystemNote";
import { PageIntro } from "../components/PageIntro";
import { ResultList } from "../components/ResultList";
import { Icon } from "../components/Icon";
import { formatCount } from "../components/resultShared";
import type { CardVariant } from "../components/resultShared";
import { WarningBanner } from "../components/WarningBanner";
import { useResource } from "../hooks/useResource";
import { formatDate } from "../format";
import type { Comparison, CorpusKind, RunDetail, RunListItem, RunListResponse } from "../types";
import { PANELS, useCorpus } from "../panels";
import type { Panel } from "../panels";

export function ComparePage() {
  const kind = useCorpus();
  const panel = PANELS[kind];
  const [runA, setRunA] = useState("");
  const [runB, setRunB] = useState("");
  // Compact by default: the same row appears in both columns, so the full card
  // is the same information twice, and the reader is here to see the
  // difference. One control, above both columns, rather than a disclosure on
  // every row.
  const [view, setView] = useState<CardVariant>("compact");

  const list = useResource<RunListResponse>(
    (signal) => api.listRuns(kind, undefined, { signal }),
    // Reloads on a panel switch. Without this the Creators panel could compare
    // two runs and the Companies panel would show the same pair, which reads as
    // a cache bug rather than as the two corpora never having been separated.
    [kind],
    {
      fallbackError: "Could not load saved runs.",
      onLoad: (response) => {
        setRunA(response.items[0]?.run_id ?? "");
        setRunB(response.items[1]?.run_id ?? "");
      },
    },
  );
  const runs = list.data?.items ?? [];

  // Two errors, not one. The list fetch and the compare fetch shared an `error`
  // slot, so a failed comparison could render the "could not load saved runs"
  // panel, and a failed list could blank the toolbar with a comparison message.
  const ready = Boolean(runA && runB && runA !== runB);
  const compare = useResource<{ comparison: Comparison; details: Details }>(
    async (signal) => {
      const [comparison, detailA, detailB] = await Promise.all([
        api.compareRuns(runA, runB, { signal }),
        api.getRun(runA, { signal }),
        api.getRun(runB, { signal }),
      ]);
      return { comparison, details: { a: detailA, b: detailB } };
    },
    [runA, runB],
    { enabled: ready, fallbackError: "Could not compare those runs." },
  );
  // Derived rather than reset: an unselectable pair reads as "no comparison"
  // without an effect clearing state the render has already decided is stale.
  const emptyDetails: Details = { a: null, b: null };
  const comparison = ready ? compare.data?.comparison ?? null : null;
  const details = ready ? compare.data?.details ?? emptyDetails : emptyDetails;
  const isComparing = compare.loading;

  const sharedKeys = useMemo(
    () => new Set(comparison?.shared.map((candidate) => candidate.creator_key) ?? []),
    [comparison],
  );

  function swapRuns() {
    setRunA(runB);
    setRunB(runA);
  }

  if (list.loading) return <div className="loading-panel page-section">Loading saved runs...</div>;
  // A failed list is not an empty list. Rendering the "save two shortlists"
  // state underneath the error told the user to go and do something they had
  // already done, and offered no way back.
  if (list.error && !runs.length) {
    return (
      <section className="page-section">
        <ErrorNote
          title={NOTE_TITLES.archive}
          action={<button className="btn btn-ghost" type="button" onClick={list.retry}>Retry</button>}
        >
          {list.error}
        </ErrorNote>
      </section>
    );
  }
  if (runs.length < 2) {
    return (
      <div className="page-section">
        <EmptyState
          icon="compare"
          index="COMPARE"
          title="Two runs make a comparison."
          body="Save at least two shortlists to see overlap, quality changes, and rank movement."
        />
      </div>
    );
  }

  return (
    <section className="page-section compare-page">
      <PageIntro
        variant="compact"
        eyebrow="Compare / Analysis"
        title="Two shortlists, side by side."
        description="What stayed, what changed, and where the quality moved."
      />
      {compare.error && (
        <ErrorNote
          title={NOTE_TITLES.comparison}
          action={<button className="btn btn-ghost" type="button" onClick={compare.retry}>Retry</button>}
        >
          {compare.error}
        </ErrorNote>
      )}

      {/* Exactly three children for the three grid columns. There were four --
         Run A, a decorative icon, the swap button and Run B -- so Run B wrapped
         onto a second row and the swap button sat alone in the middle of an
         empty column. */}
      <div className="compare-toolbar">
        <RunSelect id="compare-run-a" label="Run A" value={runA} runs={runs} onChange={setRunA} />
        <button
          className="swap-button"
          type="button"
          onClick={swapRuns}
          aria-label="Swap runs"
          title="Swap runs"
        >
          <Icon name="swap" size={14} />
        </button>
        <RunSelect id="compare-run-b" label="Run B" value={runB} runs={runs} onChange={setRunB} />
      </div>

      {runA === runB && <InfoNote title="Choose two different runs">The comparison will appear here.</InfoNote>}
      {isComparing && <div className="compare-loading" aria-live="polite"><span className="loading-bar" />Updating comparison...</div>}

      {comparison && !isComparing && (
        <>
          <ComparisonOverview comparison={comparison} panel={panel} />
          <OverlapList comparison={comparison} details={details} panel={panel} />
          <div className="compare-columns-bar">
            <span className="section-count">
              {view === "compact" ? "Summary rows" : "Full rows"}
            </span>
            <div className="panel-switch compare-view-switch" data-active={view} role="group" aria-label="Row detail">
              <button
                className={`panel-toggle ${view === "compact" ? "active" : ""}`}
                type="button"
                aria-pressed={view === "compact"}
                onClick={() => setView("compact")}
              >
                Compact
              </button>
              <button
                className={`panel-toggle ${view === "full" ? "active" : ""}`}
                type="button"
                aria-pressed={view === "full"}
                onClick={() => setView("full")}
              >
                Full
              </button>
            </div>
          </div>
          <div className="compare-columns">
            <CompareColumn title="Run A" detail={details.a} sharedKeys={sharedKeys} kind={kind} variant={view} />
            <CompareColumn title="Run B" detail={details.b} sharedKeys={sharedKeys} kind={kind} variant={view} />
          </div>
        </>
      )}
    </section>
  );
}

type Details = { a: RunDetail | null; b: RunDetail | null };

function RunSelect({ id, label, value, runs, onChange }: { id: string; label: string; value: string; runs: RunListItem[]; onChange: (value: string) => void }) {
  const selected = runs.find((run) => run.run_id === value);
  // The meta line is a sibling of the select, not part of the label. Inside the
  // label it would join the select's accessible name, and a screen reader
  // would announce "Run A, 1 results, 1 strong, combo box" -- the counts are
  // context, not the name of the control.
  return (
    <div className="compare-select">
      <label className="compare-select-label" htmlFor={id}>{label}</label>
      <select id={id} value={value} onChange={(event) => onChange(event.target.value)}>
        {runs.map((run) => <option value={run.run_id} key={run.run_id}>{labelFor(run)}</option>)}
      </select>
      {/* What each run is worth before it is compared: how much came back and
          how much of it was a strong fit. The dropdown shows the goal; this
          shows whether the pair is worth comparing at all. */}
      {selected && (
        <span className="compare-select-meta">
          {selected.n_results} results · {selected.n_strong} strong
          {selected.has_warnings && (
            <span className="compare-select-warning" title="This run reported warnings">
              <Icon name="alert" size={11} />
              <span className="visually-hidden">This run reported warnings.</span>
            </span>
          )}
        </span>
      )}
    </div>
  );
}

/** How a metric reads on its own, and how a change between two of them reads.
 *  Both are needed because the units differ: a difference of two percentages is
 *  percentage points, and a difference of two follower counts is not a
 *  percentage at all. The old single `suffix` produced "+5.7%" for engagement
 *  and "+13873" for reach, which were both the wrong unit for a delta. */
interface MetricFormat {
  value: (n: number) => string;
  delta: (difference: number) => string;
}

/** Three-way, because every delta below is rendered from an unsigned magnitude:
 *  a sign helper that only ever added "+" turned a 14K reach decline into "14K",
 *  which reads as a gain. */
function sign(value: number): string {
  return value > 0 ? "+" : value < 0 ? "-" : "";
}

const INTEGER: MetricFormat = {
  value: (n) => String(n),
  delta: (difference) => `${sign(difference)}${Math.abs(difference)}`,
};

const PERCENT: MetricFormat = {
  value: (n) => `${n.toFixed(1)}%`,
  delta: (difference) => `${sign(difference)}${Math.abs(difference).toFixed(1)}pp`,
};

const FOLLOWERS: MetricFormat = {
  value: formatCount,
  // formatCount drops the sign, so the magnitude has to be unsigned here and
  // the sign reapplied outside it.
  delta: (difference) => `${sign(difference)}${formatCount(Math.abs(difference))}`,
};

function ComparisonOverview({ comparison, panel }: { comparison: Comparison; panel: Panel }) {
  const a = comparison.summary_a;
  const b = comparison.summary_b;
  return (
    <div className="compare-overview">
      <div className="overview-primary">
        <span>Shared {panel.plural}</span>
        <strong>{comparison.shared.length}</strong>
        <small>appear in both shortlists</small>
      </div>
      {/* Every metric either column used to print as an absolute value in its
       * own SummaryMetrics strip. That put 14 cells on the page to carry 7
       * numbers, and put each delta in a different row from the two values it
       * is the difference of. One surface now, showing both ends of the change. */}
      <Delta label="Strong fits" valueA={a.n_strong} valueB={b.n_strong} format={INTEGER} />
      <Delta label="Avg similarity" valueA={a.avg_match_pct} valueB={b.avg_match_pct} format={PERCENT} />
      {/* Shown only when both runs carry the value. A prospect summary has no
       * engagement rate at all, and rendering one as 0.0 would claim a company
       * was measured at zero engagement rather than never measured. */}
      {a.avg_engagement_pct != null && b.avg_engagement_pct != null && (
        <Delta label="Avg engagement" valueA={a.avg_engagement_pct} valueB={b.avg_engagement_pct} format={PERCENT} />
      )}
      {a.median_followers != null && b.median_followers != null && (
        <Delta label="Median reach" valueA={a.median_followers} valueB={b.median_followers} format={FOLLOWERS} />
      )}
      {a.median_headcount != null && b.median_headcount != null && (
        <Delta label="Median headcount" valueA={a.median_headcount} valueB={b.median_headcount} format={FOLLOWERS} />
      )}
      {/* A cell reading 0 -> 0 carries no information: it is a metric that
       * never fired on either side, and it occupied a sixth of the strip to
       * say so. It appears only once one of the runs actually has something
       * to review. */}
      {(a.n_weak > 0 || b.n_weak > 0) && (
        <Delta label="Needs review" valueA={a.n_weak} valueB={b.n_weak} format={INTEGER} />
      )}
    </div>
  );
}

function Delta({ label, valueA, valueB, format }: { label: string; valueA: number; valueB: number; format: MetricFormat }) {
  const difference = valueB - valueA;
  const direction = difference > 0 ? "delta-up" : difference < 0 ? "delta-down" : "";
  return (
    <div className="overview-delta">
      <span>{label}</span>
      <strong className={direction}>{format.delta(difference)}</strong>
      {/* Replaces a "B vs A" caption that named the direction without giving
       * the reader either number, so a delta could not be interpreted. */}
      <small>{format.value(valueA)} → {format.value(valueB)}</small>
    </div>
  );
}

function OverlapList({ comparison, details, panel }: { comparison: Comparison; details: { a: RunDetail | null; b: RunDetail | null }; panel: Panel }) {
  const shared = comparison.shared;
  // No overlap is a result, not a system condition, so it reads as muted body
  // text rather than as a note. The heading pair is dropped with it: the
  // overview strip directly above already carries the count, so a heading
  // saying "Creators in both runs" above a sentence saying there are none was
  // the same fact twice, and the empty section took a third of the screen.
  if (shared.length === 0) {
    return <p className="overlap-empty">These two runs do not share a ranked {panel.singular}.</p>;
  }
  return (
    <div className="overlap-list">
      <div className="section-heading compact"><div><p className="eyebrow">Overlap</p><h2>{panel.label} in both runs</h2></div><span className="section-count">{shared.length} shared</span></div>
      <div className="overlap-items">
        {shared.map((candidate) => (
          <div className="overlap-item" key={candidate.creator_key}>
            {/* `label`, not `handle`: the server already picked the display
             * name for this corpus, so the Companies panel does not have to
             * know that a company has no handle. */}
            <strong>{candidate.label}</strong>
            <RankShift detailA={details.a} detailB={details.b} candidateId={candidate.id} />
          </div>
        ))}
      </div>
    </div>
  );
}

/** Rank in A against rank in B, with the movement spelled out. The chips used to
 *  print "#3 / #7", which left the reader to work out that the creator dropped
 *  four places -- the single most useful fact on the page, left as arithmetic. */
function RankShift({ detailA, detailB, candidateId }: { detailA: RunDetail | null; detailB: RunDetail | null; candidateId: number }) {
  const rankA = rankFor(detailA, candidateId);
  const rankB = rankFor(detailB, candidateId);
  if (rankA === "—" || rankB === "—") {
    return <span>#{rankA} <i>/</i> #{rankB}</span>;
  }
  // Rank 1 is best, so a lower number in B is an improvement: a - b is positive
  // when B climbed.
  const climb = rankA - rankB;
  return (
    <span>
      #{rankA} <i>→</i> #{rankB}
      {climb !== 0 && (
        <>{" "}<b className={climb > 0 ? "delta-up" : "delta-down"}>{climb > 0 ? "▲" : "▼"}{Math.abs(climb)}</b></>
      )}
    </span>
  );
}

function CompareColumn({
  title, detail, sharedKeys, kind, variant,
}: {
  title: string;
  detail: RunDetail | null;
  sharedKeys: Set<string>;
  kind: CorpusKind;
  variant: CardVariant;
}) {
  return (
    <div className="compare-column">
      {/* The count and the label, not the goal: the goal is already on screen
       * twice in the selects directly above, and it was a third and fourth
       * time here, in full, one per column. The date is in the select too. */}
      <div className="compare-column-heading">
        <span className="eyebrow">{title}</span>
        {detail && <span>{detail.ranked.length} results</span>}
      </div>
      {/* These columns were the only place in the app showing a run's quality
       * without its warnings, so a quota fallback on one side of the
       * comparison looked identical to a clean run. */}
      {detail && <WarningBanner warnings={detail.warnings} />}
      {detail
        ? <ResultList kind={kind} run={detail} highlightKeys={sharedKeys} className="compare-result-list" variant={variant} />
        : <div className="empty-ledger">No run details loaded.</div>}
    </div>
  );
}

function rankFor(detail: RunDetail | null, candidateId: number) {
  return detail?.ranked.find((entry) => entry.id === candidateId)?.rank ?? "—";
}

function labelFor(run: RunListItem): string {
  return `${formatDate(run.created_at)} · ${run.brief.goal}`;
}
