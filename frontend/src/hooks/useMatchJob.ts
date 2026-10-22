import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "../api/client";
import type { Brief, CorpusKind, JobStatus, MatchJob, MatchParams } from "../types";

/* Annotated with the union it mirrors, so a status the backend adds becomes a
 * compile error here rather than a status that silently never matches. */
const terminalStatuses: ReadonlySet<JobStatus> = new Set<JobStatus>(["succeeded", "failed", "cancelled"]);
const pollIntervalMs = 1_200;
const maxPollDurationMs = 15 * 60 * 1000;
/** The API can drop a connection while a free-tier instance sleeps or
 *  restarts, which is not the same as the match failing. A few consecutive
 *  poll errors are tolerated so a transient blip does not throw away a run
 *  the server already finished. */
const maxPollErrors = 3;
// Two entries: the third failure throws, so the largest index reached is 1.
const pollErrorBackoffMs = [1_000, 2_000];

export function useMatchJob() {
  const [job, setJob] = useState<MatchJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sequenceRef = useRef(0);
  /* Cancellation, not a boolean. A mounted flag only stopped the loop from
   * writing state; the in-flight fetch and the pending sleep between polls both
   * carried on, so unmounting mid-run left the loop running until its next
   * wake-up. The controller lets the request and the wait end immediately. */
  const runRef = useRef<{ controller: AbortController; timer: number | null } | null>(null);

  useEffect(() => () => {
    const active = runRef.current;
    if (active) {
      active.controller.abort();
      if (active.timer !== null) window.clearTimeout(active.timer);
    }
  }, []);

  /** Sleep that can be cut short. Resolves false when the run was cancelled, so
   *  the caller returns instead of waiting out a poll interval it will discard. */
  const wait = useCallback((milliseconds: number, signal: AbortSignal) => new Promise<boolean>((resolve) => {
    if (signal.aborted) {
      resolve(false);
      return;
    }
    const timer = window.setTimeout(() => {
      if (runRef.current?.timer === timer) runRef.current.timer = null;
      resolve(true);
    }, milliseconds);
    if (runRef.current) runRef.current.timer = timer;
  }), []);

  /** `kind` is required, not defaulted: a job that omitted it would silently
   *  search creators, so a caller that forgot to pass it would get a plausible
   *  creator result on the Companies panel rather than an error. */
  const start = useCallback(async (brief: Brief, params: MatchParams, kind: CorpusKind) => {
    const sequence = ++sequenceRef.current;
    const controller = new AbortController();
    runRef.current = { controller, timer: null };
    setError(null);
    setJob(null);
    const startedAt = Date.now();
    try {
      let current = await api.createMatchJob(brief, params, kind, { signal: controller.signal });
      setJob(current);
      let pollErrors = 0;
      while (!terminalStatuses.has(current.status)) {
        if (Date.now() - startedAt > maxPollDurationMs) {
          throw new Error("The match is taking too long. Please try again shortly.");
        }
        if (!await wait(pollIntervalMs, controller.signal)) return;
        try {
          current = await api.getMatchJob(current.job_id, { signal: controller.signal });
          pollErrors = 0;
        } catch (caught) {
          if (controller.signal.aborted) return;
          pollErrors += 1;
          if (pollErrors >= maxPollErrors) throw caught;
          if (!await wait(pollErrorBackoffMs[pollErrors - 1], controller.signal)) return;
        }
        if (controller.signal.aborted || sequence !== sequenceRef.current) return;
        setJob(current);
      }
      if (current.status === "failed") {
        setError(current.error ?? "The match failed.");
      }
    } catch (caught) {
      if (controller.signal.aborted || sequence !== sequenceRef.current) return;
      setJob(null);
      setError(caught instanceof ApiError ? caught.message : "The match request failed.");
    } finally {
      if (runRef.current?.controller === controller) runRef.current = null;
    }
  }, [wait]);

  return {
    job,
    error,
    isRunning: job !== null && !terminalStatuses.has(job.status),
    start,
  };
}
