import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "./client";

describe("api.probeBackend", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("resolves when the liveness endpoint responds", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, status: 200 });
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.probeBackend()).resolves.toBeUndefined();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/health/live"),
      expect.objectContaining({ signal: expect.anything() }),
    );
  });

  it("rejects when the backend responds with an error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503 }));

    await expect(api.probeBackend()).rejects.toThrow(/responded with an error/);
  });

  it("rejects with a retryable message when the cold start exceeds the timeout", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init?: RequestInit) =>
          new Promise((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
          }),
      ),
    );

    const pending = api.probeBackend();
    const assertion = expect(pending).rejects.toThrow(/did not respond within \d+s/);
    // Well past both the local and production budgets, so the test holds
    // whichever one the environment resolves to.
    await vi.advanceTimersByTimeAsync(200_000);

    await assertion;
  });

  it("names the configured backend in its failure message", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_url: string, init?: RequestInit) =>
          new Promise((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
          }),
      ),
    );

    const pending = api.probeBackend();
    const assertion = expect(pending).rejects.toThrow(/The backend at .* did not respond/);
    await vi.advanceTimersByTimeAsync(200_000);
    await assertion;
  });
});

/* Only the health probe used to carry a timeout. Every other request was an
 * unbounded fetch, so a sleeping free-tier host -- which takes about a minute
 * to come back -- left the user on a spinner with nothing to retry and no way
 * to learn why. */
describe("api request timeouts", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  function hangingFetch() {
    return vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
        }),
    );
  }

  it("aborts a request that never responds and names the likely cause", async () => {
    vi.useFakeTimers();
    const fetchMock = hangingFetch();
    vi.stubGlobal("fetch", fetchMock);

    const pending = api.getMeta("creator");
    const assertion = expect(pending).rejects.toThrow(/did not respond within \d+s/);
    // Past the 30s default ceiling.
    await vi.advanceTimersByTimeAsync(60_000);

    await assertion;
    expect(fetchMock.mock.calls[0][1]?.signal).toBeDefined();
  });

  it("does not time out a request that responds", async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      text: async () => JSON.stringify({ platforms: [], defaults: {}, limits: {}, index: { status: "ready", count: 0 } }),
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(api.getMeta("creator")).resolves.toBeDefined();
  });

  it("turns a network failure into a readable ApiError rather than a raw TypeError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(api.listRuns("creator")).rejects.toThrow(/could not be reached/);
  });

  it("gives a run detail its own, longer ceiling", async () => {
    vi.useFakeTimers();
    const fetchMock = hangingFetch();
    vi.stubGlobal("fetch", fetchMock);

    const pending = api.getRun("run-1");
    // Survives past the 30s default that other requests get.
    await vi.advanceTimersByTimeAsync(45_000);
    expect(fetchMock).toHaveBeenCalledOnce();

    const assertion = expect(pending).rejects.toThrow(/did not respond within 90s/);
    await vi.advanceTimersByTimeAsync(60_000);
    await assertion;
  });

  it("propagates a caller-cancelled request as an abort, not a timeout", async () => {
    const controller = new AbortController();
    const fetchMock = hangingFetch();
    vi.stubGlobal("fetch", fetchMock);

    const pending = api.getRun("run-1", { signal: controller.signal });
    controller.abort();

    await expect(pending).rejects.toMatchObject({ name: "AbortError" });
  });
});
