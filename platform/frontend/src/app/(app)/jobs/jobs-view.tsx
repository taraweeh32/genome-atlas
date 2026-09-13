"use client";

/**
 * Job list for the active workspace, with attempt history.
 *
 * The browser observes; it never claims, leases, retries or executes work. State
 * names are shown exactly as the server records them, because `retry_waiting`,
 * `stale`, `cancel_requested` and `cancelled` mean different things and must not
 * be collapsed into a friendlier single label.
 */

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useWorkspace } from "@/context/workspace-context";
import { useApiResource } from "@/hooks/use-api-resource";
import { ApiClient } from "@/lib/api-client";
import styles from "../analyses/analyses.module.css";
import { label } from "../analyses/analyses-view";

const STATE_FILTERS: readonly { value: string; label: string }[] = [
  { value: "", label: "All states" },
  { value: "queued", label: "Queued" },
  { value: "running", label: "Running" },
  { value: "retry_waiting", label: "Waiting on retry backoff" },
  { value: "stale", label: "Stale (lease expired)" },
  { value: "succeeded", label: "Succeeded" },
  { value: "failed", label: "Failed" },
  { value: "cancelled", label: "Cancelled" },
  { value: "dead_letter", label: "Dead letter" },
];

function moment(value: string | null | undefined): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export function JobsView() {
  const client = useMemo(() => new ApiClient(), []);
  const { activeWorkspace, resolution } = useWorkspace();
  const workspaceId = activeWorkspace?.id ?? null;
  const [state, setState] = useState("");
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null);

  const jobs = useApiResource(
    () =>
      workspaceId
        ? client.jobs({
            workspace_id: workspaceId,
            state: state === "" ? undefined : [state],
          })
        : Promise.resolve({ items: [], page: { number: 1, size: 0, total: 0 } }),
    [client, workspaceId, state],
  );

  if (resolution !== "resolved" || !activeWorkspace) {
    return (
      <Card title="Workspace context">
        {resolution === "error" ? (
          <ErrorState description="Workspaces could not be loaded, so no job list can be shown." />
        ) : (
          <LoadingState label="Resolving your workspace" />
        )}
      </Card>
    );
  }

  return (
    <Card
      title={`Jobs in ${activeWorkspace.name}`}
      description="Only jobs in a scope you may read are listed. Platform-wide job control lives in administration and requires platform permissions."
      actions={<Button onClick={jobs.reload}>Refresh</Button>}
    >
      <div className={styles.form}>
        <div>
          <label className={styles.muted} htmlFor="job-state">
            State
          </label>
          <select id="job-state" value={state} onChange={(event) => setState(event.target.value)}>
            {STATE_FILTERS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {jobs.status === "loading" ? (
        <LoadingState label="Loading jobs" />
      ) : jobs.status === "error" ? (
        <ErrorState
          title={jobs.isForbidden ? "Not available to you" : "Something went wrong"}
          description={jobs.error ?? undefined}
          correlationId={jobs.correlationId ?? undefined}
          action={jobs.isForbidden ? undefined : <Button onClick={jobs.reload}>Try again</Button>}
        />
      ) : jobs.data && jobs.data.items.length > 0 ? (
        <div className={styles.scroll}>
          <table className={styles.table}>
            <caption className="visually-hidden">Durable jobs readable by you</caption>
            <thead>
              <tr>
                <th scope="col">Kind</th>
                <th scope="col">State</th>
                <th scope="col">Queue</th>
                <th scope="col" className={styles.numeric}>
                  Attempt
                </th>
                <th scope="col">Progress</th>
                <th scope="col">Created</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {jobs.data.items.map((job) => (
                <tr key={job.id}>
                  <td className={styles.wide}>{label(job.kind)}</td>
                  <td>
                    <span className={styles.badge}>{label(job.state)}</span>
                    {job.cancellation_requested_at ? (
                      <p className={styles.muted}>cancellation requested</p>
                    ) : null}
                    {job.failure_code ? (
                      <p className={styles.muted}>
                        {job.failure_code}
                        {job.error_class ? ` · ${label(job.error_class)}` : ""}
                      </p>
                    ) : null}
                  </td>
                  <td>
                    {job.queue} · priority {job.priority} · {label(job.node_class)}
                  </td>
                  <td className={styles.numeric}>
                    {job.attempt_number}/{job.max_attempts}
                  </td>
                  <td>
                    {job.progress_percent === null ? "not reported" : `${job.progress_percent}%`}
                  </td>
                  <td>{moment(job.created_at)}</td>
                  <td>
                    <Button
                      onClick={() => setExpandedJobId(expandedJobId === job.id ? null : job.id)}
                    >
                      {expandedJobId === job.id ? "Hide attempts" : "Attempts"}
                    </Button>
                    {expandedJobId === job.id ? (
                      <dl className={styles.provenance}>
                        {job.attempts.length === 0 ? (
                          <>
                            <dt>Attempts</dt>
                            <dd>no attempt recorded yet</dd>
                          </>
                        ) : (
                          job.attempts.map((attempt) => (
                            <div key={attempt.attempt_number}>
                              <dt>Attempt {attempt.attempt_number}</dt>
                              <dd>
                                {label(attempt.state)} · worker {attempt.worker_id ?? "unassigned"} ·
                                node {attempt.node_id ?? "unassigned"} · started{" "}
                                {moment(attempt.started_at)} · finished {moment(attempt.finished_at)}
                                {attempt.failure_message ? ` · ${attempt.failure_message}` : ""}
                              </dd>
                            </div>
                          ))
                        )}
                      </dl>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState
          title="No job recorded"
          description="No durable work exists in this workspace, or none is in the selected state."
        />
      )}
    </Card>
  );
}
