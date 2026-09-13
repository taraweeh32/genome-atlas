"use client";

/**
 * Minimal request-state hook.
 *
 * Every data surface must render an explicit loading, empty, error or degraded
 * state, so the request state is modelled explicitly rather than inferred from a
 * missing value. It fetches nothing on its own: the caller supplies the API call.
 */

import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api-client";

export type ResourceStatus = "loading" | "ready" | "error";

export interface ResourceState<T> {
  readonly status: ResourceStatus;
  readonly data: T | null;
  readonly error: string | null;
  readonly correlationId: string | null;
  readonly isForbidden: boolean;
}

export interface Resource<T> extends ResourceState<T> {
  reload(): void;
}

export function useApiResource<T>(
  load: () => Promise<T>,
  dependencies: readonly unknown[] = [],
): Resource<T> {
  const [state, setState] = useState<ResourceState<T>>({
    status: "loading",
    data: null,
    error: null,
    correlationId: null,
    isForbidden: false,
  });
  const [nonce, setNonce] = useState(0);

  const reload = useCallback(() => setNonce((value) => value + 1), []);

  useEffect(() => {
    let cancelled = false;
    setState((current) => ({ ...current, status: "loading", error: null }));
    void (async () => {
      try {
        const data = await load();
        if (!cancelled) {
          setState({
            status: "ready",
            data,
            error: null,
            correlationId: null,
            isForbidden: false,
          });
        }
      } catch (cause) {
        if (cancelled) return;
        const apiError = cause instanceof ApiError ? cause : null;
        setState({
          status: "error",
          data: null,
          error: apiError?.message ?? "The platform API could not be reached.",
          correlationId: apiError?.correlationId ?? null,
          // 403 and 404 are both refusals the UI must state plainly rather than
          // retry in a loop.
          isForbidden: apiError?.status === 403 || apiError?.status === 404,
        });
      }
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nonce, ...dependencies]);

  return { ...state, reload };
}
