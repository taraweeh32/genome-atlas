"use client";

/**
 * Live platform status from the backend readiness endpoint.
 *
 * This is real data from `/api/v1/ready` — never a hardcoded dashboard. All four
 * states are explicit: loading, error, degraded and ready.
 */

import { useCallback, useEffect, useState } from "react";
import { ApiClient, ApiError } from "@/lib/api-client";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { DegradedState, ErrorState, LoadingState } from "@/components/ui/states";
import type { ReadinessResponse } from "@/lib/types";
import styles from "./dashboard.module.css";

type Status = "loading" | "loaded" | "failed";

export function PlatformStatusPanel() {
  const [status, setStatus] = useState<Status>("loading");
  const [report, setReport] = useState<ReadinessResponse | null>(null);
  const [failure, setFailure] = useState<ApiError | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setStatus("loading");
    try {
      const response = await new ApiClient().readiness({ signal });
      setReport(response);
      setFailure(null);
      setStatus("loaded");
    } catch (caught) {
      if (signal?.aborted) return;
      setFailure(
        caught instanceof ApiError
          ? caught
          : new ApiError(0, "unexpected_error", "Platform status could not be read."),
      );
      setStatus("failed");
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  return (
    <Card
      title="Platform status"
      description="Reported by the backend readiness endpoint."
      actions={
        <Button variant="secondary" onClick={() => void load()} disabled={status === "loading"}>
          Refresh
        </Button>
      }
    >
      {status === "loading" ? <LoadingState label="Checking platform status" /> : null}

      {status === "failed" && failure ? (
        <ErrorState
          title="Platform status unavailable"
          description={failure.message}
          correlationId={failure.correlationId}
        />
      ) : null}

      {status === "loaded" && report ? (
        <>
          {report.ready ? null : (
            <DegradedState description="At least one required dependency is unavailable, so some capabilities cannot be served." />
          )}
          <table className={styles.table}>
            <caption className="visually-hidden">Backend dependency status</caption>
            <thead>
              <tr>
                <th scope="col">Dependency</th>
                <th scope="col">Status</th>
                <th scope="col">Required</th>
                <th scope="col">Latency</th>
              </tr>
            </thead>
            <tbody>
              {report.dependencies.map((dependency) => (
                <tr key={dependency.name}>
                  <th scope="row">{dependency.name}</th>
                  <td>{dependency.status}</td>
                  <td>{dependency.required ? "Yes" : "No"}</td>
                  <td>
                    {typeof dependency.latency_ms === "number"
                      ? `${dependency.latency_ms} ms`
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className={styles.timestamp}>Checked at {report.checked_at}</p>
        </>
      ) : null}
    </Card>
  );
}
