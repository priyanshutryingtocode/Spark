import { supabase } from "../lib/supabase";
import type {
  Brief,
  Comparison,
  MatchJob,
  MatchFeedback,
  MatchRating,
  LookalikeResponse,
  MatchParams,
  Meta,
  RunDetail,
  RunListResponse,
  SavedMatch,
  SavedMatchListResponse,
  CorpusKind,
  DatasetMode,
} from "../types";

const baseUrl = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const isLocalHost = typeof window !== "undefined" && /^(localhost|127\.0\.0\.1)$/.test(window.location.hostname);
export const isApiConfigured = Boolean(baseUrl) || (import.meta.env.DEV && isLocalHost);
/** Cold-start budget for waking a sleeping free-tier service. */
const backendWakeTimeoutMs = 120_000;
const localWakeTimeoutMs = 10_000;
const defaultRequestTimeoutMs = 30_000;
const slowRequestTimeoutMs = 90_000;

function wakeTimeoutMs(): number {
  return import.meta.env.DEV ? localWakeTimeoutMs : backendWakeTimeoutMs;
}

function apiTargetLabel(): string {
  return baseUrl || "the Vite dev proxy";
}


export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function authenticatedHeaders(init?: RequestInit) {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  if (supabase) {
    const { data } = await supabase.auth.getSession();
    if (data.session?.access_token) headers.set("Authorization", `Bearer ${data.session.access_token}`);
  }
  return headers;
}

interface RequestOptions {
  timeoutMs?: number;
  signal?: AbortSignal;
}

function timeoutMessage(timeoutMs: number): string {
  return `The backend at ${apiTargetLabel()} did not respond within ${Math.round(timeoutMs / 1000)}s. `
    + "It may have gone to sleep -- the status pill in the top bar wakes it.";
}

async function fetchGuarded(
  path: string,
  init?: RequestInit,
  options: RequestOptions = {},
): Promise<Response> {
  const headers = await authenticatedHeaders(init);
  const timeoutMs = options.timeoutMs ?? defaultRequestTimeoutMs;
  const controller = new AbortController();
  const onCallerAbort = () => controller.abort();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  // Checked before subscribing: awaiting the auth headers above is async, so a
  // caller can have aborted during it, and subscribing to an already-aborted
  // signal never fires -- the request would then run to the full timeout.
  if (options.signal?.aborted) {
    clearTimeout(timer);
    throw new DOMException("Aborted", "AbortError");
  }
  options.signal?.addEventListener("abort", onCallerAbort);

  try {
    return await fetch(`${baseUrl}${path}`, { ...init, headers, signal: controller.signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      if (options.signal?.aborted) throw error;
      throw new ApiError(timeoutMessage(timeoutMs), 408, null);
    }
    throw new ApiError(`The backend at ${apiTargetLabel()} could not be reached. Is it running?`, 0, null);
  } finally {
    clearTimeout(timer);
    options.signal?.removeEventListener("abort", onCallerAbort);
  }
}

/** JSON if the body parses, raw text if not, null when empty. */
async function readPayload(response: Response): Promise<unknown> {
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function request<T>(path: string, init?: RequestInit, options: RequestOptions = {}): Promise<T> {
  const response = await fetchGuarded(path, init, options);
  const payload = await readPayload(response);
  if (!response.ok) {
    throw new ApiError(errorMessage(payload), response.status, payload);
  }
  return payload as T;
}

async function probeBackend(timeoutMs = wakeTimeoutMs()): Promise<void> {
  const target = apiTargetLabel();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(`${baseUrl}/health/live`, { signal: controller.signal });
    if (!response.ok) throw new ApiError(`The backend at ${target} responded with an error.`, response.status, null);
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(
        `The backend at ${target} did not respond within ${Math.round(timeoutMs / 1000)}s. Is it running?`,
        408,
        null,
      );
    }
    throw new ApiError(`The backend at ${target} could not be reached. Is it running?`, 0, null);
  } finally {
    clearTimeout(timer);
  }
}

async function downloadFile(path: string, filename: string) {
  const response = await fetchGuarded(path, undefined, { timeoutMs: slowRequestTimeoutMs });
  if (!response.ok) {
    const payload = await readPayload(response);
    throw new ApiError(errorMessage(payload), response.status, payload);
  }
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

/** Every call that can be scoped to a panel takes `kind` explicitly.
 *
 *  Not optional and not defaulted: a call that silently omitted it would return
 *  every corpus's runs and render them all in whichever panel happened to be
 *  open, which is the failure the split exists to prevent. The one place a kind
 *  is inferred is a caller that has a run in hand, which carries its own. */
export const api = {
  probeBackend: () => probeBackend(),
  getMeta: (kind: CorpusKind, options?: RequestOptions, dataset?: DatasetMode) => {
    const query = new URLSearchParams({ kind });
    if (dataset) query.set("dataset", dataset);
    return request<Meta>(`/api/v1/meta?${query.toString()}`, undefined, options);
  },
  createMatchJob: (brief: Brief, params: MatchParams, kind: CorpusKind, options?: RequestOptions, dataset: DatasetMode = "synthetic") =>
    request<MatchJob>("/api/v1/match-jobs", {
      method: "POST",
      body: JSON.stringify({ brief, params, kind, dataset }),
    }, options),
  getMatchJob: (jobId: string, options?: RequestOptions) =>
    request<MatchJob>(`/api/v1/match-jobs/${jobId}`, undefined, options),
  listRuns: (kind: CorpusKind, cursor?: string, options?: RequestOptions) => {
    const query = new URLSearchParams({ limit: "100", kind });
    if (cursor) query.set("cursor", cursor);
    return request<RunListResponse>(`/api/v1/runs?${query.toString()}`, undefined, options);
  },
  getRun: (runId: string, options?: RequestOptions) =>
    request<RunDetail>(`/api/v1/runs/${runId}`, undefined, { timeoutMs: slowRequestTimeoutMs, ...options }),
  deleteRun: (runId: string, options?: RequestOptions) =>
    request<void>(`/api/v1/runs/${runId}`, { method: "DELETE" }, options),
  listSavedMatches: (kind: CorpusKind, options?: RequestOptions) =>
    request<SavedMatchListResponse>(`/api/v1/saved-matches?kind=${kind}`, undefined, options),
  saveMatch: (runId: string, candidateId: number, options?: RequestOptions) =>
    request<SavedMatch>("/api/v1/saved-matches", {
      method: "POST",
      body: JSON.stringify({ run_id: runId, candidate_id: candidateId }),
    }, options),
  deleteSavedMatch: (savedId: string, options?: RequestOptions) =>
    request<void>(`/api/v1/saved-matches/${savedId}`, { method: "DELETE" }, options),
  updateSavedMatch: (savedId: string, update: Partial<Pick<SavedMatch, "status" | "note">>, options?: RequestOptions) =>
    request<SavedMatch>(`/api/v1/saved-matches/${savedId}`, {
      method: "PATCH",
      body: JSON.stringify(update),
    }, options),
  submitMatchFeedback: (
    runId: string,
    candidateId: number,
    rating: MatchRating,
    reason = "",
    options?: RequestOptions,
  ) => request<MatchFeedback>("/api/v1/match-feedback", {
    method: "POST",
    body: JSON.stringify({ run_id: runId, candidate_id: candidateId, rating, reason }),
  }, options),
  findLookalikes: (kind: CorpusKind, candidateId: number, dataset: DatasetMode = "synthetic", options?: RequestOptions) =>
    request<LookalikeResponse>("/api/v1/lookalikes", {
      method: "POST",
      body: JSON.stringify({ kind, dataset, candidate_id: candidateId, top_k: 5 }),
    }, options),
  compareRuns: (runIdA: string, runIdB: string, options?: RequestOptions) =>
    request<Comparison>("/api/v1/comparisons", {
      method: "POST",
      body: JSON.stringify({ run_id_a: runIdA, run_id_b: runIdB }),
    }, options),
  /** One download path for both corpora: the server picks the column set from
   *  the run's own `kind`, so the client does not have to know what is in the
   *  sheet it is saving. */
  downloadRun: (runId: string) => downloadFile(`/api/v1/runs/${runId}/export.csv`, `shortlist-${runId}.csv`),
};

function errorMessage(payload: unknown): string {
  if (typeof payload === "string") return payload;
  if (payload && typeof payload === "object" && "detail" in payload) {
    const detail = payload.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0];
      if (first && typeof first === "object" && "msg" in first && typeof first.msg === "string") {
        return first.msg;
      }
    }
    if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") {
      return detail.message;
    }
  }
  return "The request could not be completed.";
}
