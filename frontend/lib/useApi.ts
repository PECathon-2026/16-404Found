"use client";
import { useCallback, useEffect, useState } from "react";
import { ApiError } from "./api";

/**
 * Fetch + optional polling. Contract: `deps` lists every value `fn` closes over (compared by value), so the effect re-runs
 * exactly when the request would differ. `reload()` re-fetches without flashing the loading state.
 */
export function useApi<T>(fn: () => Promise<T>, deps: unknown[] = [], pollMs?: number) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  const key = JSON.stringify(deps);
  useEffect(() => {
    let live = true;
    const run = () => fn().then((d) => { if (live) { setData(d); setError(null); } }).catch((e) => { if (live) setError(e as ApiError); }).finally(() => { if (live) setLoading(false); });
    void run();
    const t = pollMs ? setInterval(() => void run(), pollMs) : null;
    return () => { live = false; if (t) clearInterval(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `fn` is covered by `key` (see the contract above)
  }, [key, pollMs, nonce]);
  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, reload };
}
