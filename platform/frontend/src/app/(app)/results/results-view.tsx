"use client";

/**
 * Result sets readable by the caller in the active workspace.
 *
 * The list is exactly what the backend returned. A result set the caller may not
 * read is absent, not filtered out here. `is_readable` is the server's answer to
 * whether content may be opened at all, and it is displayed rather than derived.
 *
 * `is_development_payload` is always shown: a surface produced by a development
 * stub of the scientific subsystem must never look like a validated result.
 */

import Link from "next/link";
import { useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useWorkspace } from "@/context/workspace-context";
import { useApiResource } from "@/hooks/use-api-resource";
import { ApiClient } from "@/lib/api-client";
import styles from "./results.module.css";

export function label(value: string): string {
  return value.replace(/_/g, " ");
}

export function ResultsView() {
  const client = useMemo(() => new ApiClient(), []);
  const { activeWorkspace, resolution } = useWorkspace();
  const workspaceId = activeWorkspace?.id ?? null;

  const resultSets = useApiResource(
    () =>
      workspaceId
        ? client.resultSets({ workspace_id: workspaceId })
        : Promise.resolve({ items: [], page: { number: 1, size: 0, total: 0 } }),
    [client, workspaceId],
  );

  if (resolution !== "resolved" || !activeWorkspace) {
    return (
      <Card title="Workspace context">
        {resolution === "error" ? (
          <ErrorState description="Workspaces could not be loaded, so no result list can be shown." />
        ) : (
          <LoadingState label="Resolving your workspace" />
        )}
      </Card>
    );
  }

  return (
    <Card
      title={`Result sets in ${activeWorkspace.name}`}
      description="Each surface belongs to one execution and keeps that execution's provenance. Superseded and withdrawn surfaces stay listed, because their history is part of the record."
      actions={<Button onClick={resultSets.reload}>Refresh</Button>}
    >
      {resultSets.status === "loading" ? (
        <LoadingState label="Loading result sets" />
      ) : resultSets.status === "error" ? (
        <ErrorState
          description={resultSets.error ?? undefined}
          correlationId={resultSets.correlationId ?? undefined}
          action={
            resultSets.isForbidden ? undefined : (
              <Button onClick={resultSets.reload}>Try again</Button>
            )
          }
        />
      ) : resultSets.data && resultSets.data.items.length > 0 ? (
        <div className={styles.scroll}>
          <table className={styles.table}>
            <caption className="visually-hidden">
              Result sets readable by you in this workspace
            </caption>
            <thead>
              <tr>
                <th scope="col">Result key</th>
                <th scope="col">State</th>
                <th scope="col">Completeness</th>
                <th scope="col">Origin</th>
                <th scope="col" className={styles.numeric}>
                  Rows
                </th>
                <th scope="col">Readable</th>
                <th scope="col">Payload</th>
                <th scope="col">
                  <span className="visually-hidden">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {resultSets.data.items.map((resultSet) => (
                <tr key={resultSet.id}>
                  <td className={styles.wide}>{resultSet.result_key}</td>
                  <td>
                    <span className={styles.badge}>{label(resultSet.state)}</span>
                  </td>
                  <td>{label(resultSet.completeness)}</td>
                  <td>{label(resultSet.origin)}</td>
                  <td className={styles.numeric}>
                    {resultSet.row_count === null ? (
                      <span className={styles.muted}>not reported</span>
                    ) : (
                      resultSet.row_count
                    )}
                  </td>
                  <td>
                    {resultSet.is_readable ? (
                      <span className={styles.badge}>readable</span>
                    ) : (
                      <span className={styles.muted}>not readable</span>
                    )}
                  </td>
                  <td>
                    {resultSet.is_development_payload ? (
                      <span className={styles.development}>development stub</span>
                    ) : (
                      <span className={styles.muted}>scientific</span>
                    )}
                  </td>
                  <td>
                    <Link href={`/results/${resultSet.id}`}>Open</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState
          title="No result sets in this workspace"
          description="Nothing is hidden here: this workspace contains no result surface you may read. Results appear once an execution has delivered and the platform has verified them."
        />
      )}
    </Card>
  );
}
