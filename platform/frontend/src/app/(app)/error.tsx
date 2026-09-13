"use client";

import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/states";
import { ApiError } from "@/lib/api-client";

/** Error foundation for authenticated application routes. */
export default function ApplicationError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const isApiError = error instanceof ApiError;
  return (
    <ErrorState
      title="This page could not be loaded"
      description={
        isApiError
          ? error.message
          : "The page failed to load. No changes were made to your data."
      }
      correlationId={isApiError ? error.correlationId : error.digest}
      action={
        <Button variant="primary" onClick={reset}>
          Try again
        </Button>
      }
    />
  );
}
