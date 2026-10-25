import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "../api/client";
import type { Brief, CorpusKind, JobStatus, MatchJob, MatchParams } from "../types";

const terminalStatuses: ReadonlySet<JobStatus> = new Set<JobStatus>(["succeeded", "failed", "cancelled"]);
const pollIntervalMs = 1_200;
const maxPollDurationMs = 15 * 60 * 1000;
const maxPollErrors = 3;
const pollErrorBackoffMs = [1_000, 2_000];

export function useMatchJob() {
  const [job, setJob] = useState<MatchJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sequenceRef = useRef(0);
  const runRef = useRef<{ controller: AbortController; timer: number | null } | null>(null);

  useEffect(() => () => {
    const active = runRef.current;
    if (active) {
      active.controller.abort();
    }
  }, []);

  const wait = useCallback((milliseconds: number, signal: AbortSignal) => new Promise<boolean>((resolve) => {
    if (signal.aborted) {
      resolve(false);
      return;
    }
    const timer = window.setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      if (runRef.current?.timer === timer) runRef.current.timer = null;
      resolve(true);
    }, milliseconds);
    const onAbort = () => {
      window.clearTimeout(timer);
      signal.removeEventListener("abort", onAbort);
      if (runRef.current?.timer === timer) runRef.current.timer = null;
      resolve(false);
    };
    if (runRef.current) runRef.current.timer = timer;
    signal.addEventListener("abort", onAbort, { once: true });
  }), []);

  const start = useCallback(async (brief: Brief, params: MatchParams, kind: CorpusKind) => {
    const sequence = ++sequenceRef.current;
    const previous = runRef.current;
    previous?.controller.abort();
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
