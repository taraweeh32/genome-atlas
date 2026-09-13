"use client";

/**
 * Loads the authoritative workspace list into the workspace context.
 *
 * The list is whatever `GET /workspaces` returns: the caller's personal
 * workspace plus the organization workspaces their memberships actually reach.
 * The frontend never assembles or filters this list itself.
 */

import { useEffect, useRef } from "react";
import { useSession } from "@/context/session-context";
import { useWorkspace } from "@/context/workspace-context";
import { ApiClient, ApiError } from "@/lib/api-client";
import type { WorkspaceRef } from "@/lib/types";

export function useWorkspaceSync(client?: ApiClient): void {
  const { status } = useSession();
  const { resolution, applyResolved, markLoading, markError } = useWorkspace();
  const clientRef = useRef<ApiClient | null>(client ?? null);

  useEffect(() => {
    if (status !== "authenticated" || resolution !== "unresolved") {
      return;
    }
    let cancelled = false;
    const api = clientRef.current ?? (clientRef.current = new ApiClient());
    markLoading();
    void (async () => {
      try {
        const collection = await api.workspaces();
        if (cancelled) return;
        const workspaces: WorkspaceRef[] = collection.items.map((item) => ({
          id: item.id,
          kind: item.kind,
          name: item.name,
          organizationId: item.organization_id ?? undefined,
        }));
        applyResolved(workspaces);
      } catch (cause) {
        if (cancelled) return;
        markError(
          cause instanceof ApiError
            ? cause.message
            : "Workspaces could not be loaded from the platform.",
        );
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [status, resolution, applyResolved, markLoading, markError]);
}
