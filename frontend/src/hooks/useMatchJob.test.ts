import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useMatchJob } from "./useMatchJob";
import type { MatchJob } from "../types";

const apiMocks = vi.hoisted(() => ({
  createMatchJob: vi.fn(),
  getMatchJob: vi.fn(),
}));

vi.mock("../api/client", () => ({
  api: apiMocks,
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status = 500) {
      super(message);
      this.status = status;
    }
  },
}));

function makeJob(overrides: Partial<MatchJob> = {}): MatchJob {
  return {
    job_id: "job-1",
    status: "queued",
    stage: "queued",
    run_id: null,
    outcome: null,
    error: null,
    ...overrides,
  };
}

const brief = { goal: "yoga for beginners", platform: "Any", audience: "", vibe: "" };

/** waitFor's 1s default is shorter than the 1.2s poll interval, so every
 *  assertion about a polled state needs a longer budget. */
const POLL_BUDGET = { timeout: 5_000 };

/** `start` runs the whole poll loop, so it does not resolve until the job is
 *  terminal. Tests therefore start it without awaiting and assert on state. */
async function launch(result: { current: ReturnType<typeof useMatchJob> }, params = { top_k: 10, top_n: 5 }) {
  await act(async () => {
    void result.current.start(brief, params, "creator");
  });
}

describe("useMatchJob", () => {
  beforeEach(() => {
    apiMocks.createMatchJob.mockReset();
    apiMocks.getMatchJob.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("reports the job as running once it is created", async () => {
    apiMocks.createMatchJob.mockResolvedValue(makeJob());
    apiMocks.getMatchJob.mockReturnValue(new Promise(() => {}));
    const { result } = renderHook(() => useMatchJob());

    await launch(result);

    await waitFor(() => expect(result.current.job).toBeTruthy(), POLL_BUDGET);
    expect(result.current.job?.status).toBe("queued");
    expect(result.current.isRunning).toBe(true);
  });

  it("polls until a terminal status and then stops", async () => {
    apiMocks.createMatchJob.mockResolvedValue(makeJob());
    apiMocks.getMatchJob
      .mockResolvedValueOnce(makeJob({ status: "running", stage: "ranking" }))
      .mockResolvedValue(makeJob({ status: "succeeded", stage: "complete", run_id: "run-1", outcome: "match" }));

    const { result } = renderHook(() => useMatchJob());
    await launch(result);

    await waitFor(() => expect(result.current.job?.status).toBe("succeeded"), POLL_BUDGET);
    expect(result.current.isRunning).toBe(false);
    expect(result.current.error).toBeNull();

    // Nothing is polled once the job is terminal.
    const calls = apiMocks.getMatchJob.mock.calls.length;
    await new Promise((resolve) => { setTimeout(resolve, 60); });
    expect(apiMocks.getMatchJob).toHaveBeenCalledTimes(calls);
  });

  it("surfaces a failed job's own message", async () => {
    apiMocks.createMatchJob.mockResolvedValue(makeJob());
    apiMocks.getMatchJob.mockResolvedValue(makeJob({ status: "failed", stage: "failed", error: "Index unavailable." }));

    const { result } = renderHook(() => useMatchJob());
    await launch(result);

    await waitFor(() => expect(result.current.error).toBe("Index unavailable."), POLL_BUDGET);
  });

  it("tolerates a transient poll error and keeps going", async () => {
    apiMocks.createMatchJob.mockResolvedValue(makeJob());
    apiMocks.getMatchJob
      .mockRejectedValueOnce(new Error("connection reset"))
      .mockResolvedValue(makeJob({ status: "succeeded", stage: "complete", run_id: "run-1", outcome: "match" }));

    const { result } = renderHook(() => useMatchJob());
    await launch(result);

    // A run the server already finished should not be lost to one blip.
    await waitFor(() => expect(result.current.job?.status).toBe("succeeded"), POLL_BUDGET);
    expect(result.current.error).toBeNull();
  });

  /* Three poll errors separated by 1s and 2s backoffs is ~6.6s of real waiting,
   * so this one carries an explicit budget. It is the only coverage of the
   * give-up path, which is what stops a dead backend from polling for the full
   * 15 minutes. */
  it("gives up once the error tolerance is exhausted", async () => {
    apiMocks.createMatchJob.mockResolvedValue(makeJob());
    apiMocks.getMatchJob.mockRejectedValue(new Error("still down"));

    const { result } = renderHook(() => useMatchJob());
    await launch(result);

    await waitFor(() => expect(result.current.error).toBe("The match request failed."), { timeout: 12_000 });
    expect(result.current.job).toBeNull();
    // It gave up rather than retrying forever.
    expect(apiMocks.getMatchJob.mock.calls.length).toBe(3);
  }, 15_000);

  it("prefers an ApiError message over the generic one", async () => {
    const { ApiError } = await import("../api/client");
    apiMocks.createMatchJob.mockRejectedValue(new ApiError("The backend did not respond within 30s.", 408, null));

    const { result } = renderHook(() => useMatchJob());
    await launch(result);

    await waitFor(() => expect(result.current.error).toMatch(/did not respond within 30s/), POLL_BUDGET);
  });

  /* The regression these guard.
   *
   * The loop used to be guarded by a mounted boolean, which stopped it writing
   * state but not running. Unmounting mid-run left the in-flight request and
   * the 1.2s sleep alive, so it kept polling a job the user navigated away
   * from -- spending real requests against a metered backend. */
  it("stops polling once the component unmounts", async () => {
    apiMocks.createMatchJob.mockResolvedValue(makeJob());
    apiMocks.getMatchJob.mockResolvedValue(makeJob({ status: "running", stage: "retrieval" }));

    const { result, unmount } = renderHook(() => useMatchJob());
    await launch(result);
    await waitFor(() => expect(apiMocks.getMatchJob).toHaveBeenCalled(), POLL_BUDGET);

    const callsAtUnmount = apiMocks.getMatchJob.mock.calls.length;
    unmount();

    // Must outlast a full poll interval, or a still-running loop has not had
    // the chance to poll again and the assertion passes vacuously.
    await new Promise((resolve) => { setTimeout(resolve, 1_500); });

    expect(apiMocks.getMatchJob.mock.calls.length).toBe(callsAtUnmount);
  });

  it("passes an abort signal to every request it makes", async () => {
    apiMocks.createMatchJob.mockResolvedValue(makeJob());
    apiMocks.getMatchJob.mockReturnValue(new Promise(() => {}));

    const { result } = renderHook(() => useMatchJob());
    await launch(result);
    await waitFor(() => expect(apiMocks.getMatchJob).toHaveBeenCalled(), POLL_BUDGET);

    const post = apiMocks.createMatchJob.mock.calls[0][3] as { signal?: AbortSignal } | undefined;
    const poll = apiMocks.getMatchJob.mock.calls[0][1] as { signal?: AbortSignal } | undefined;
    expect(post?.signal).toBeInstanceOf(AbortSignal);
    expect(poll?.signal).toBeInstanceOf(AbortSignal);
  });

  it("aborts the in-flight request when the component unmounts", async () => {
    apiMocks.createMatchJob.mockResolvedValue(makeJob());
    apiMocks.getMatchJob.mockReturnValue(new Promise(() => {}));

    const { result, unmount } = renderHook(() => useMatchJob());
    await launch(result);
    await waitFor(() => expect(apiMocks.getMatchJob).toHaveBeenCalled(), POLL_BUDGET);

    const signal = (apiMocks.getMatchJob.mock.calls[0][1] as { signal: AbortSignal }).signal;
    expect(signal.aborted).toBe(false);

    unmount();
    expect(signal.aborted).toBe(true);
  });
});
