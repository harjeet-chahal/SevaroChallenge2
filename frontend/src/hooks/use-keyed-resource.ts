"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { describeError } from "@/lib/api/errors";

interface Result<T> {
  key: string;
  data: T | null;
  error: string | null;
}

export interface KeyedResource<T> {
  /** Latest data. Kept while a refetch for a new key is in flight (no flicker). */
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

/**
 * Fetch whenever ``key`` changes (e.g. dataset version + simulation time). ``null`` key
 * means "nothing to fetch" and clears the data.
 */
export function useKeyedResource<T>(
  key: string | null,
  fetcher: (signal: AbortSignal) => Promise<T>,
): KeyedResource<T> {
  const [result, setResult] = useState<Result<T> | null>(null);
  const [nonce, setNonce] = useState(0);
  const fetcherRef = useRef(fetcher);

  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  const requestKey = key === null ? null : `${key}#${nonce}`;

  useEffect(() => {
    if (requestKey === null) return;
    const controller = new AbortController();
    fetcherRef.current(controller.signal).then(
      (data) => {
        if (!controller.signal.aborted) setResult({ key: requestKey, data, error: null });
      },
      (error: unknown) => {
        if (!controller.signal.aborted) {
          setResult({ key: requestKey, data: null, error: describeError(error) });
        }
      },
    );
    return () => controller.abort();
  }, [requestKey]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  if (requestKey === null) return { data: null, error: null, loading: false, reload };
  const fresh = result?.key === requestKey;
  return {
    data: result?.data ?? null,
    error: fresh ? (result?.error ?? null) : null,
    loading: !fresh,
    reload,
  };
}
