import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "../api/client";
import type { CorpusKind, RunListItem } from "../types";

/** Keep history scoped to the active corpus; both lists are otherwise valid. */
export function useRuns(kind: CorpusKind) {
  const [items, setItems] = useState<RunListItem[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [itemsKind, setItemsKind] = useState(kind);
  const itemsKindRef = useRef(kind);
  const requestId = useRef(0);
  const activeRequest = useRef<AbortController | null>(null);

  const load = useCallback(async (cursor?: string, append = false) => {
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    const id = ++requestId.current;
    if (append) setIsLoadingMore(true);
    else setIsLoading(true);
    setError(null);
    try {
      const response = await api.listRuns(kind, cursor, { signal: controller.signal });
      if (controller.signal.aborted || requestId.current !== id) return;
      setItems((current) => (append && itemsKindRef.current === kind ? [...current, ...response.items] : response.items));
      itemsKindRef.current = kind;
      setItemsKind(kind);
      setNextCursor(response.next_cursor);
    } catch (caught) {
      if (!controller.signal.aborted && requestId.current === id) {
        setError(caught instanceof ApiError ? caught.message : "Could not load run history.");
      }
    } finally {
      if (requestId.current === id) {
        activeRequest.current = null;
        setIsLoading(false);
        setIsLoadingMore(false);
      }
    }
  }, [kind]);

  const cancelLoad = useCallback(() => {
    ++requestId.current;
    activeRequest.current?.abort();
    activeRequest.current = null;
  }, []);

  useEffect(() => {
    void load();
    return cancelLoad;
  }, [cancelLoad, load]);

  const remove = useCallback(async (runId: string) => {
    try {
      await api.deleteRun(runId);
      setItems((current) => current.filter((item) => item.run_id !== runId));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not delete the run.");
      throw caught;
    }
  }, []);

  return {
    items: itemsKind === kind ? items : [],
    isLoading: isLoading || itemsKind !== kind,
    isLoadingMore: itemsKind === kind && isLoadingMore,
    hasMore: itemsKind === kind && nextCursor !== null,
    error,
    refresh: () => load(),
    loadMore: () => (itemsKind === kind && nextCursor ? load(nextCursor, true) : Promise.resolve()),
    remove,
  };
}
