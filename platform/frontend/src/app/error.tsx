"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/states";
import { ApiError } from "@/lib/api-client";

/**
 * Global error boundary.
 *
 * Renders a non-sensitive message. Backend messages are already safe by
 * construction; unknown client failures are reported generically.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Diagnostics stay in the browser console; genomic content is never logged.
    console.error("unhandled UI error", error.digest ?? error.name);
  }, [error]);

  const isApiError = error instanceof ApiError;

  return (
    <div style={{ padding: "var(--space-6)" }}>
      <ErrorState
        title={isApiError ? "The platform could not complete that request" : "Something went wrong"}
        description={
          isApiError
            ? error.message
            : "The page failed to render. Try again; if this persists, contact your administrator."
        }
        correlationId={isApiError ? error.correlationId : error.digest}
        action={
          <Button variant="primary" onClick={reset}>
            Try again
          </Button>
        }
      />
    </div>
  );
}
