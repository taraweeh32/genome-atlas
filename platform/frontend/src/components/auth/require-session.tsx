"use client";

/**
 * Session-aware wrapper for authenticated namespaces.
 *
 * This is a *presentation* gate: it avoids rendering an authenticated shell to
 * someone with no session, and sends them to sign in with the blocked path
 * preserved. It grants nothing — every API call behind this shell is authorized
 * again by the backend, which is the only authority.
 */

import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { LoadingState } from "@/components/ui/states";
import { ErrorState } from "@/components/ui/states";
import { useSession } from "@/context/session-context";
import { useWorkspaceSync } from "@/hooks/use-workspace-sync";

export function RequireSession({ children }: { children: ReactNode }) {
  const { status, error, correlationId, refresh } = useSession();
  const router = useRouter();
  const pathname = usePathname();
  useWorkspaceSync();

  useEffect(() => {
    if (status === "anonymous") {
      const next = pathname ? `?next=${encodeURIComponent(pathname)}` : "";
      router.replace(`/login${next}`);
    }
  }, [status, pathname, router]);

  if (status === "authenticated") {
    return <>{children}</>;
  }

  if (status === "error") {
    return (
      <ErrorState
        title="The platform could not confirm your session"
        description={error ?? undefined}
        correlationId={correlationId ?? undefined}
        action={
          <button type="button" onClick={() => void refresh()}>
            Try again
          </button>
        }
      />
    );
  }

  return <LoadingState label="Confirming your session" />;
}
