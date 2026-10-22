import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRuns } from "./useRuns";
import type { RunListItem } from "../types";

const apiMocks = vi.hoisted(() => ({
  listRuns: vi.fn(),
  deleteRun: vi.fn(),
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

function makeItem(runId: string): RunListItem {
  return {
    run_id: runId,
    created_at: "2026-01-01T00:00:00Z",
    brief: { goal: `run ${runId}`, platform: "Any", audience: "", vibe: "" },
    n_results: 5,
    n_strong: 2,
    has_warnings: false,
  } as RunListItem;
}

describe("useRuns", () => {
  beforeEach(() => {
    apiMocks.listRuns.mockReset();
    apiMocks.deleteRun.mockReset();
  });

  it("loads the first page on mount", async () => {
    apiMocks.listRuns.mockResolvedValue({ items: [makeItem("a")], next_cursor: null });
    const { result } = renderHook(() => useRuns("creator"));

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.items).toHaveLength(1);
    expect(result.current.hasMore).toBe(false);
  });

  it("appends the next page and clears hasMore at the end of the list", async () => {
    apiMocks.listRuns
      .mockResolvedValueOnce({ items: [makeItem("a")], next_cursor: "page-2" })
      .mockResolvedValueOnce({ items: [makeItem("b")], next_cursor: null });
    const { result } = renderHook(() => useRuns("creator"));
    await waitFor(() => expect(result.current.items).toHaveLength(1));

    expect(result.current.hasMore).toBe(true);
    await act(async () => { await result.current.loadMore(); });

    expect(result.current.items.map((item) => item.run_id)).toEqual(["a", "b"]);
    expect(result.current.hasMore).toBe(false);
    // The cursor is passed through, not refetched from the top.
    // kind first, then the cursor: listRuns(kind, cursor).
    expect(apiMocks.listRuns).toHaveBeenLastCalledWith("creator", "page-2");
  });

  it("does nothing when loading more with no cursor", async () => {
    apiMocks.listRuns.mockResolvedValue({ items: [makeItem("a")], next_cursor: null });
    const { result } = renderHook(() => useRuns("creator"));
    await waitFor(() => expect(result.current.hasMore).toBe(false));

    await act(async () => { await result.current.loadMore(); });
    expect(apiMocks.listRuns).toHaveBeenCalledTimes(1);
  });

  it("keeps an ApiError message and clears it on a successful refresh", async () => {
    const { ApiError } = await import("../api/client");
    apiMocks.listRuns
      .mockRejectedValueOnce(new ApiError("The backend did not respond within 30s.", 408, null))
      .mockResolvedValueOnce({ items: [makeItem("a")], next_cursor: null });
    const { result } = renderHook(() => useRuns("creator"));

    await waitFor(() => expect(result.current.error).toMatch(/did not respond within 30s/));

    // A failed load is sticky until an action succeeds, otherwise the note
    // would sit there contradicting a working list.
    await act(async () => { await result.current.refresh(); });
    expect(result.current.error).toBeNull();
  });

  it("removes a deleted run from the list without refetching", async () => {
    apiMocks.listRuns.mockResolvedValue({ items: [makeItem("a"), makeItem("b")], next_cursor: null });
    apiMocks.deleteRun.mockResolvedValue(undefined);
    const { result } = renderHook(() => useRuns("creator"));
    await waitFor(() => expect(result.current.items).toHaveLength(2));

    await act(async () => { await result.current.remove("a"); });

    expect(result.current.items.map((item) => item.run_id)).toEqual(["b"]);
    expect(apiMocks.listRuns).toHaveBeenCalledTimes(1);
  });

  /* remove rethrows after setting the error, so a caller that wants to react
   * can; HistoryPage swallows it. If that ever stops being true the error note
   * would be the only signal, and it is sticky. */
  it("rethrows a failed delete so the caller is not left with a silent failure", async () => {
    apiMocks.listRuns.mockResolvedValue({ items: [makeItem("a")], next_cursor: null });
    const { ApiError } = await import("../api/client");
    apiMocks.deleteRun.mockRejectedValue(new ApiError("Could not delete the run.", 409, null));
    const { result } = renderHook(() => useRuns("creator"));
    await waitFor(() => expect(result.current.items).toHaveLength(1));

    await act(async () => {
      await expect(result.current.remove("a")).rejects.toThrow(/could not delete/i);
    });

    expect(result.current.error).toMatch(/could not delete/i);
    expect(result.current.items).toHaveLength(1);
  });
});
