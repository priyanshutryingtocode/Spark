import { PANELS, useCorpus } from "../panels";
import { useState } from "react";
import type { FormEvent } from "react";

import { api, ApiError } from "../api/client";
import { EmptyState } from "../components/EmptyState";
import { EmptyWorkspace } from "../components/EmptyWorkspace";
import { ErrorNote, NOTE_TITLES } from "../components/SystemNote";
import { PageIntro } from "../components/PageIntro";
import { RangeControl } from "../components/RangeControl";
import { ResultList } from "../components/ResultList";
import { MatchDetailsDialog } from "../components/MatchDetailsDialog";
import { TargetFields } from "../components/TargetFields";
import { RunContext } from "../components/RunContext";
import { RunStatus } from "../components/RunStatus";
import { SummaryMetrics } from "../components/RunSummary";
import { WarningBanner } from "../components/WarningBanner";
import { useMatchJob } from "../hooks/useMatchJob";
import { Skeleton } from "../components/Skeleton";
import { useResource } from "../hooks/useResource";
import type { Brief, CorpusKind, DatasetMode, MatchRating, Meta, ProductContext, RunDetail, SavedMatchListResponse, SuggestedFilters } from "../types";

const emptyBrief: Brief = {
  goal: "",
  platform: "Any",
  audience: "",
  vibe: "",
};

/** Starter briefs per panel. Separate lists rather than one shared with the
 *  noun swapped: a creator brief names an audience and a vibe, a sales brief
 *  names a sector and a scale, and the examples only help if they are shaped
 *  like the thing the field is asking for. */
const goalSuggestions: Record<CorpusKind, string[]> = {
  creator: [
    "a thrifted-vintage clothing label for Gen Z who care about slow fashion",
    "budget-friendly travel planning for solo backpackers",
    "skincare routines for sensitive skin, taught inclusively",
    "data-driven investing basics for first-time buyers",
  ],
  prospect: [
    "warehouse robotics and fleet routing software for mid-size logistics firms",
    "payroll automation for logistics companies with 200 to 2000 staff",
    "compliance tooling for fintech companies expanding into new markets",
    "field service scheduling software for industrial manufacturers",
  ],
};


const FALLBACK_LIMITS: Meta["limits"] = {
  goal_min_length: 20,
  goal_max_length: 1000,
  audience_max_length: 300,
  vibe_max_length: 500,
  top_k_min: 1,
  top_k_max: 50,
  top_n_min: 1,
  top_n_max: 10,
};

function resolveLimits(meta: Meta | null): Meta["limits"] {
  if (!meta?.limits) return FALLBACK_LIMITS;
  return { ...FALLBACK_LIMITS, ...meta.limits };
}

export function SearchPage() {
  const kind = useCorpus();
  const panel = PANELS[kind];
  const [brief, setBrief] = useState<Brief>(emptyBrief);
  const [productText, setProductText] = useState("");
  const [contextLoading, setContextLoading] = useState(false);
  const [contextError, setContextError] = useState<string | null>(null);
  const [contextNotice, setContextNotice] = useState<string | null>(null);
  const [suggestedFilters, setSuggestedFilters] = useState<SuggestedFilters>({});
  const [dataset, setDataset] = useState<DatasetMode | null>(null);
  const [topK, setTopK] = useState(10);
  const [topN, setTopN] = useState(5);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [selectedMatchId, setSelectedMatchId] = useState<number | null>(null);
  const [savingMatch, setSavingMatch] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [feedbackByMatch, setFeedbackByMatch] = useState<Record<string, MatchRating>>({});
  const [feedbackSaving, setFeedbackSaving] = useState(false);
  const [feedbackError, setFeedbackError] = useState<string | null>(null);
  const { job, error, isRunning, start, cancel } = useMatchJob();
  const [hasStarted, setHasStarted] = useState(false);

  const meta = useResource<Meta>(
    (signal) => api.getMeta(kind, { signal }, dataset ?? undefined),
    // Reloads on a panel switch: the two corpora have different index counts and
    // different facets, and `kind` in the deps is what stops the Companies panel
    // rendering the Creators panel's "2,000 creators indexed" pill.
    [kind, dataset],
    {
      fallbackError: "Could not load API metadata.",
      onLoad: (value) => {
        if (value.dataset) setDataset((current) => current ?? value.dataset!);
        // Preserve what the user typed in every field. Meta reloads on a panel
        // switch, and goal was preserved while audience and vibe were replaced,
        // so toggling panels silently rewrote two thirds of a written brief.
        setBrief((current) => ({
          ...current,
          goal: current.goal || value.defaults?.goal || "",
          // No platform facet means the server sends an empty list; "Any" is
          // then ignored rather than treated as a filter.
          platform: value.platforms.length === 0
            ? "Any"
            : value.platforms.includes(current.platform)
              ? current.platform
              : value.platforms[0] || "Any",
          audience: current.audience || value.defaults?.audience || "",
          vibe: current.vibe || value.defaults?.vibe || "",
        }));
      },
    },
  );

  const savedMatches = useResource<SavedMatchListResponse>(
    (signal) => api.listSavedMatches(kind, { signal }),
    [kind],
    { fallbackError: "Could not load your saved shortlist." },
  );

  const run = useResource<RunDetail>(
    (signal) => api.getRun(job!.run_id!, { signal }),
    [job?.run_id],
    {
      // The job reports success before the shortlist is readable. 
      enabled: job?.status === "succeeded" && Boolean(job.run_id) && job.outcome !== "no_results",
      fallbackError: "Could not load the completed run.",
    },
  );

  function updateBrief(field: keyof Brief, value: string) {
    setBrief((current) => ({ ...current, [field]: value }));
  }

  /** The structured fields, which are lists and bands rather than strings. */
  function updateTarget(field: string, value: unknown) {
    setBrief((current) => ({ ...current, [field]: value }));
  }

  async function extractContext() {
    if (contextLoading || productText.trim().length < 20) return;
    setContextLoading(true);
    setContextError(null);
    setContextNotice(null);
    try {
      const result = await api.extractProductContext(productText.trim(), kind);
      if (!result.relevant) {
        setBrief((current) => ({ ...current, product_context: null }));
        setSuggestedFilters({});
        setContextNotice(result.message || "This text did not include usable product or audience details.");
        return;
      }
      setBrief((current) => ({ ...current, product_context: result.context }));
      setSuggestedFilters(result.suggested_filters);
    } catch (caught) {
      setContextError(caught instanceof ApiError ? caught.message : "Could not extract product context.");
    } finally {
      setContextLoading(false);
    }
  }

  function updateContext(field: keyof ProductContext, value: string | string[]) {
    setBrief((current) => ({
      ...current,
      product_context: { ...current.product_context!, [field]: value },
    }));
  }

  function changeProductText(value: string) {
    setProductText(value);
    setBrief((current) => ({ ...current, product_context: null }));
    setSuggestedFilters({});
    setContextError(null);
    setContextNotice(null);
  }

  function clearProductContext() {
    setProductText("");
    setBrief((current) => ({ ...current, product_context: null }));
    setSuggestedFilters({});
    setContextError(null);
    setContextNotice(null);
  }

  function acceptFilterSuggestion(field: string) {
    const value = suggestedFilters[field as keyof SuggestedFilters];
    if (value === undefined || value === null || value === "" || (Array.isArray(value) && value.length === 0)) return;
    updateTarget(field, field === "target_size" && Array.isArray(value) && value.length === 2 ? value : value);
    setSuggestedFilters((current) => ({ ...current, [field]: undefined }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setHasStarted(true);
    setSelectedMatchId(null);
    setSaveError(null);
    run.setData(null);
    run.setError(null);
    await start(brief, { top_k: topK, top_n: topN }, kind, dataset ?? meta.data?.dataset ?? "synthetic");
  }

  function switchDataset(next: DatasetMode) {
    if (!dataset || next === dataset) return;
    cancel();
    setDataset(next);
    setHasStarted(false);
    run.setData(null);
    run.setError(null);
    setSelectedMatchId(null);
    setSaveError(null);
    setFeedbackError(null);
  }

  async function saveSelectedMatch() {
    if (!runDetail || !selectedCandidate || savingMatch) return;
    setSavingMatch(true);
    setSaveError(null);
    try {
      const saved = await api.saveMatch(runDetail.run_id, selectedCandidate.id);
      savedMatches.setData({
        items: [saved, ...(savedMatches.data?.items ?? []).filter((item) => item.saved_id !== saved.saved_id)],
      });
    } catch (caught) {
      setSaveError(caught instanceof ApiError ? caught.message : "Could not save this match.");
    } finally {
      setSavingMatch(false);
    }
  }

  async function submitMatchFeedback(rating: MatchRating) {
    if (!runDetail || !selectedCandidate || feedbackSaving) return;
    const runId = runDetail.run_id;
    const candidateId = selectedCandidate.id;
    const key = `${runId}:${candidateId}`;
    setFeedbackSaving(true);
    setFeedbackError(null);
    try {
      const feedback = await api.submitMatchFeedback(runId, candidateId, rating);
      setFeedbackByMatch((current) => ({ ...current, [key]: feedback.rating }));
    } catch (caught) {
      setFeedbackError(caught instanceof ApiError ? caught.message : "Could not record your feedback.");
    } finally {
      setFeedbackSaving(false);
    }
  }

  const metaValue = meta.data;
  const runDetail = run.data;
  const needsReindex = metaValue?.index.status === "reindex_required";
  const disabled = metaValue ? metaValue.index.status !== "ready" : false;
  const limits = resolveLimits(metaValue);
  const goal = brief.goal;
  const goalLength = goal.trim().length;
  const goalTooShort = goalLength > 0 && goalLength < limits.goal_min_length;
  const optionalFieldCount = Object.entries(brief).filter(([field, value]) => {
    if (field === "goal" || field === "platform" || value == null) return false;
    if (typeof value === "string") return value.trim().length > 0;
    if (Array.isArray(value)) return value.length > 0;
    if (typeof value === "number") return value > 0;
    return Boolean(value);
  }).length;
  const awaitingRun = job?.status === "succeeded"
    && !runDetail
    && (run.loading || !run.error)
    && job.outcome !== "no_results";
  const selectedEntry = runDetail?.ranked.find((entry) => entry.id === selectedMatchId);
  const selectedCandidate = selectedEntry
    ? runDetail?.candidates.find((candidate) => candidate.id === selectedEntry.id)
    : undefined;

  return (
    <section className="page-section">
      <PageIntro
        eyebrow="New match"
        title="Search"
        description={panel.describe}
        meta={metaValue && (
          <div className="search-meta-tools">
            <div className="dataset-switch" role="group" aria-label="Search data source">
              <button type="button" aria-pressed={dataset === "synthetic"} onClick={() => switchDataset("synthetic")}>Synthetic</button>
              <button type="button" aria-pressed={dataset === "real"} onClick={() => switchDataset("real")}>Real</button>
            </div>
            <span className={`readiness ${disabled ? "readiness-off" : "readiness-on"}`}>
              <span className="readiness-dot" />
              {needsReindex
                ? "Index needs re-embedding"
                : disabled
                  ? "Index unavailable"
                  : `${metaValue.index.count.toLocaleString()} ${panel.plural} indexed`}
            </span>
          </div>
        )}
      />

      {meta.error && (
        <ErrorNote
          title={NOTE_TITLES.connection}
          action={<button className="btn btn-ghost" type="button" onClick={meta.retry}>Retry</button>}
        >
          {meta.error}
        </ErrorNote>
      )}
      {!metaValue && !meta.error && <Skeleton variant="form" />}

      {metaValue && (
        <div className="match-workspace">
          <aside className="brief-rail">
            <div className="rail-heading"><span>Brief</span></div>
            <form className="brief-form" onSubmit={submit}>
              <div className="brief-fields">
                <label className="brief-field" htmlFor="goal">
                  <span id="goal-label">What are you promoting?</span>
                  <textarea
                    id="goal"
                    value={goal}
                    maxLength={limits.goal_max_length}
                    placeholder="Describe the product or campaign in your own words."
                    onChange={(event) => updateBrief("goal", event.target.value)}
                    rows={5}
                    aria-labelledby="goal-label"
                    aria-describedby="goal-count"
                  />
                  <span className="field-count" id="goal-count">{goalLength}/{limits.goal_max_length}</span>
                </label>
                {!goal.trim() && (
                  <div className="suggestion-chips" role="group" aria-label="Example briefs">
                    {goalSuggestions[kind].map((suggestion) => (
                      <button key={suggestion} className="chip" type="button" onClick={() => updateBrief("goal", suggestion)}>
                        {suggestion}
                      </button>
                    ))}
                  </div>
                )}
                {/* Hidden, not disabled: a company is not on TikTok and the server
                  * does not filter prospects by platform, so an empty select
                  * would offer a choice that silently does nothing. */}
                {metaValue && metaValue.platforms.length > 0 && (
                  <label className="brief-field" htmlFor="platform">
                    <span>Platform</span>
                    <select id="platform" value={brief.platform} onChange={(event) => updateBrief("platform", event.target.value)}>
                      {metaValue.platforms.map((platform) => <option key={platform}>{platform}</option>)}
                    </select>
                  </label>
                )}
              </div>
              <details className="optional-fields-disclosure">
                <summary>
                  <span className="optional-fields-title">Refine your match</span>
                  <span className="optional-fields-status">
                    {optionalFieldCount > 0 ? `${optionalFieldCount} added` : "Optional"}
                  </span>
                </summary>
                <div className="optional-fields-content">
                  <div className="brief-fields">
                    <label className="brief-field" htmlFor="audience">
                      <span>Target audience <em>optional</em></span>
                      <input id="audience" value={brief.audience} maxLength={limits.audience_max_length} placeholder="e.g. Gen Z, first-time buyers" onChange={(event) => updateBrief("audience", event.target.value)} />
                    </label>
                    <label className="brief-field" htmlFor="vibe">
                      <span>Vibe or tone <em>optional</em></span>
                      <textarea id="vibe" value={brief.vibe} maxLength={limits.vibe_max_length} placeholder="e.g. warm, practical" onChange={(event) => updateBrief("vibe", event.target.value)} rows={2} />
                    </label>
                  </div>
                  <div className="rail-divider" />
                  {/* These requirements filter or rerank candidates. The prose
                      brief above still drives semantic retrieval. */}
                  <div className="brief-section">
                    <div className="control-heading">
                      <span>{kind === "creator" ? "Target audience" : "Target accounts"}</span>
                      <span className="control-value">optional</span>
                    </div>
                    <TargetFields kind={kind} values={brief} onChange={updateTarget} />
                  </div>
                </div>
              </details>
              <details className="product-context-disclosure">
                <summary>
                  <span>Product context</span>
                  <span className="optional-fields-status">{brief.product_context ? "Review context" : "Optional"}</span>
                </summary>
                <div className="product-context-content">
                  <label className="brief-field" htmlFor="product-context-source">
                    <span>Paste product or service details</span>
                    <textarea
                      id="product-context-source"
                      value={productText}
                      maxLength={12000}
                      disabled={contextLoading}
                      placeholder="Add product details, positioning, and intended customers."
                      rows={5}
                      onChange={(event) => changeProductText(event.target.value)}
                    />
                  </label>
                  <p className="target-help">Text is sent to Gemini. On Google’s unpaid API tier, it may be used to improve Google products. Avoid confidential or personal information. The reviewed summary and excerpts are saved with each run; the original text is not stored.</p>
                  <button className="btn btn-secondary" type="button" onClick={() => void extractContext()} disabled={contextLoading || productText.trim().length < 20}>
                    {contextLoading ? "Extracting…" : "Extract details"}
                  </button>
                  {contextError && <p className="form-help" role="alert">{contextError}</p>}
                  {contextNotice && <p className="target-help" role="status">{contextNotice}</p>}
                  {brief.product_context && (
                    <div className="product-context-review">
                      <p className="context-review-label">Review extracted context before searching</p>
                      <button className="btn btn-ghost" type="button" onClick={clearProductContext}>Remove context</button>
                      <label className="brief-field">
                        <span>Category</span>
                        <input value={brief.product_context.category} onChange={(event) => updateContext("category", event.target.value)} />
                      </label>
                      <label className="brief-field">
                        <span>Target audience</span>
                        <textarea rows={2} value={brief.product_context.target_audience} onChange={(event) => updateContext("target_audience", event.target.value)} />
                      </label>
                      {(["use_cases", "differentiators", "exclusions"] as const).map((field) => (
                        <label className="brief-field" key={field}>
                          <span>{field === "use_cases" ? "Use cases" : field === "differentiators" ? "Differentiators" : "Exclusions"}</span>
                          <textarea rows={2} value={brief.product_context![field].join("\n")} onChange={(event) => updateContext(field, event.target.value.split("\n").map((item) => item.trim()).filter(Boolean))} />
                        </label>
                      ))}
                      {brief.product_context.source_quotes.length > 0 && (
                        <details className="context-quotes">
                          <summary>Source excerpts</summary>
                          {brief.product_context.source_quotes.map((quote) => <blockquote key={quote}>{quote}</blockquote>)}
                        </details>
                      )}
                    </div>
                  )}
                  {Object.entries(suggestedFilters).filter(([, value]) => value !== undefined && value !== null && value !== "" && (!Array.isArray(value) || value.length > 0)).map(([field, value]) => (
                    <div className="context-filter-suggestion" key={field}>
                      <span>{filterSuggestionLabel(field)}: {field === "min_reach_ratio" ? `${Math.round(Number(value) * 100)}%` : Array.isArray(value) ? value.join("–") : String(value)}</span>
                      <button className="btn btn-ghost" type="button" onClick={() => acceptFilterSuggestion(field)}>Apply</button>
                    </div>
                  ))}
                </div>
              </details>
              <div className="rail-divider" />
              <div className="retrieval-controls">
                <div className="control-heading"><span>Search depth</span><span className="control-value">{topK} → {topN}</span></div>
                <RangeControl id="top-k" noun={panel.plural} label="Candidates retrieved" value={topK} min={limits.top_k_min} max={limits.top_k_max} onChange={(next) => { setTopK(next); if (topN > next) setTopN(next); }} />
                {/* The shortlist cannot exceed what was retrieved, and the API
                  * also publishes its own ceiling. This used to read the
                  * backend's top_n_max nowhere. */}
                <RangeControl id="top-n" noun={panel.plural} label="Final shortlist" value={topN} min={limits.top_n_min} max={Math.min(topK, limits.top_n_max)} onChange={setTopN} />
              </div>
              <div className="brief-footer">
                <button className="btn btn-primary btn-block" type="submit" disabled={disabled || isRunning || goalTooShort}>
                  {isRunning ? "Working..." : "Run match"}
                </button>
                {goalTooShort
                  ? <span className="form-help">Add a little more detail so there is something to match against.</span>
                  : needsReindex
                    ? <span className="form-help">The index was built with a different embedding model. Re-embed it with the backend CLI.</span>
                    : disabled && <span className="form-help">Index {panel.plural} from the backend CLI first.</span>}
              </div>
            </form>
          </aside>

          <div className="run-workspace">
            {job && <RunStatus job={job} isRunning={isRunning} />}
            {(error || run.error) && (
              <ErrorNote
                title={NOTE_TITLES.request}
                action={run.error
                  ? <button className="btn btn-ghost" type="button" onClick={run.retry}>Retry</button>
                  : undefined}
              >
                {error ?? run.error}
              </ErrorNote>
            )}
            {exportError && (
              <ErrorNote title={NOTE_TITLES.export}>
                {exportError}
              </ErrorNote>
            )}
            {/* `hasStarted` records that a submit happened, which survives the
              * hook clearing `job` on failure. The `!job` clause covers a job
              * restored without a local submit. */}
            {!hasStarted && !job && !runDetail && <EmptyWorkspace />}
            {job?.outcome === "no_results" && (
              <EmptyState
                icon="search"
                index="NO MATCH"
                title="Try a wider platform."
                body={kind === "creator"
                  ? "No creators came back for this filter. Switch to Any or adjust the brief."
                  : "No companies came back for this brief. Widen the description or adjust the depth."}
              />
            )}
            {awaitingRun && <Skeleton variant="results" label="Loading your shortlist" />}
            {runDetail && (
              <div className="run-results">
                <RunContext
                  run={runDetail}
                  label="Shortlist"
                  exporting={exporting}
                  onExport={() => {
                    if (exporting) return;
                    setExporting(true);
                    setExportError(null);
                    void api.downloadRun(runDetail.run_id)
                      .catch((caught) => setExportError(caught instanceof ApiError ? caught.message : "Could not export the run."))
                      .finally(() => setExporting(false));
                  }}
                />
                <WarningBanner warnings={runDetail.warnings} />
                <SummaryMetrics summary={runDetail.summary} />
                <ResultList
                  kind={runDetail.kind}
                  run={runDetail}
                  selectedId={selectedEntry?.id}
                  onSelect={(id) => {
                    setSelectedMatchId(id);
                    setSaveError(null);
                    setFeedbackError(null);
                  }}
                />
                {selectedEntry && selectedCandidate && (
                  <MatchDetailsDialog
                    kind={runDetail.kind}
                    dataset={runDetail.dataset ?? "synthetic"}
                    candidate={selectedCandidate}
                    entry={selectedEntry}
                    saved={savedMatches.data?.items.some((item) =>
                      item.run_id === runDetail.run_id && item.ranked.id === selectedEntry.id,
                    ) ?? false}
                    saving={savingMatch}
                    saveError={saveError}
                    onSave={() => void saveSelectedMatch()}
                    feedbackRating={feedbackByMatch[`${runDetail.run_id}:${selectedEntry.id}`] ?? null}
                    feedbackSaving={feedbackSaving}
                    feedbackError={feedbackError}
                    onFeedback={(rating) => void submitMatchFeedback(rating)}
                    onClose={() => setSelectedMatchId(null)}
                  />
                )}
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function filterSuggestionLabel(field: string): string {
  const labels: Record<string, string> = {
    audience_age: "Audience age",
    audience_gender: "Audience gender",
    audience_countries: "Audience countries",
    languages: "Languages",
    min_reach_ratio: "Minimum reach ratio",
    target_industries: "Industries",
    target_size: "Company size",
    target_countries: "Company countries",
    budget_band: "Budget",
    buyer_roles: "Buyer roles",
  };
  return labels[field] ?? field;
}
