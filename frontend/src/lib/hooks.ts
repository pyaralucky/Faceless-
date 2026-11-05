"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

export interface QueryState<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  /** Re-run the fetcher. `silent` keeps current data and avoids the loading flag. */
  reload: (silent?: boolean) => Promise<void>;
  setData: (updater: T | undefined | ((prev: T | undefined) => T | undefined)) => void;
}

export interface QueryOptions {
  /** Poll interval in ms; falsy disables polling. */
  interval?: number | false | null;
  /** Skip fetching entirely. */
  enabled?: boolean;
}

/**
 * Minimal data-fetching hook. `key` identifies the resource: when it changes,
 * the fetcher runs again. Stale responses from previous keys are discarded.
 */
export function useQuery<T>(key: string | null, fetcher: () => Promise<T>, opts: QueryOptions = {}): QueryState<T> {
  const { interval, enabled = true } = opts;
  const [data, setDataState] = useState<T | undefined>(undefined);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState<boolean>(Boolean(key) && enabled);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const generation = useRef(0);
  const inflight = useRef(false);
  const active = Boolean(key) && enabled;

  const run = useCallback(
    async (silent = false) => {
      if (!active) return;
      const gen = generation.current;
      if (!silent) setLoading(true);
      inflight.current = true;
      try {
        const result = await fetcherRef.current();
        if (gen !== generation.current) return;
        setDataState(result);
        setError(null);
      } catch (e) {
        if (gen !== generation.current) return;
        setError(e);
      } finally {
        if (gen === generation.current) {
          inflight.current = false;
          if (!silent) setLoading(false);
        }
      }
    },
    [active],
  );

  useEffect(() => {
    generation.current++;
    inflight.current = false;
    if (!active) {
      setLoading(false);
      return;
    }
    setDataState(undefined);
    setError(null);
    void run(false);
  }, [key, active, run]);

  useEffect(() => {
    if (!active || !interval) return;
    const id = setInterval(() => {
      if (!inflight.current && (typeof document === "undefined" || document.visibilityState !== "hidden")) void run(true);
    }, interval);
    return () => clearInterval(id);
  }, [key, active, interval, run]);

  const setData = useCallback((updater: T | undefined | ((prev: T | undefined) => T | undefined)) => {
    setDataState((prev) => (typeof updater === "function" ? (updater as (p: T | undefined) => T | undefined)(prev) : updater));
  }, []);

  return { data, error, loading, reload: run, setData };
}

export function useDebounced<T>(value: T, delay = 300): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setV(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);
  return v;
}

/** Fetch a project asset with auth headers and expose it as an object URL. */
export function useAssetBlobUrl(projectId: string | null | undefined, assetId: string | null | undefined) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!projectId || !assetId) {
      setUrl(null);
      return;
    }
    let cancelled = false;
    let objectUrl: string | null = null;
    setLoading(true);
    setError(null);
    api.assets
      .file(projectId, assetId)
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch((e) => {
        if (!cancelled) setError(e);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      setUrl(null);
    };
  }, [projectId, assetId]);

  return { url, error, loading };
}

/** Download an authenticated asset by triggering a temporary <a download>. */
export async function downloadAsset(projectId: string, assetId: string, filename: string): Promise<void> {
  const blob = await api.assets.file(projectId, assetId);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
