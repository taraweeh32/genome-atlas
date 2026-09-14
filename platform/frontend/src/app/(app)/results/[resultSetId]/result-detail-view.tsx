"use client";

/**
 * One result set: provenance, artifacts and a bounded window of its content.
 *
 * Rules this surface obeys:
 *
 * - Knowing an identifier grants nothing. The backend authorizes the read and
 *   returns 404-shaped refusals for surfaces outside the caller's scope.
 * - Content is fetched in server-bounded windows. There is no "load everything",
 *   and no value on screen is computed here — cells are shown exactly as stored.
 * - Missing provenance is shown as missing. A blank engine version is never
 *   replaced with a plausible one.
 * - A download is a short-lived grant issued by the server; bytes go straight
 *   from object storage to the browser.
 */

import { useCallback, useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useToasts } from "@/components/ui/toast";
import { useApiResource } from "@/hooks/use-api-resource";
import { ApiClient, ApiError } from "@/lib/api-client";
import type { ResultProvenanceResponse } from "@/lib/result-types";
import { AnnotationPanel } from "./annotation-panel";
import styles from "../results.module.css";

const WINDOW_SIZE = 100;

function label(value: string): string {
  return value.replace(/_/g, " ");
}

/** Renders a stored cell without interpreting it. `null` stays "not reported". */
function cell(value: unknown): React.ReactNode {
  if (value === null || value === undefined) {
    return <span className={styles.muted}>not reported</span>;
  }
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function provenanceItems(
  provenance: ResultProvenanceResponse,
): readonly { term: string; value: string | null }[] {
  return [
    { term: "Analysis execution", value: provenance.analysis_execution_id },
    { term: "Scientific execution", value: provenance.scientific_execution_id },
    { term: "Configuration version", value: provenance.analysis_configuration_id },
    { term: "Engine resource", value: provenance.engine_resource_id },
    { term: "Engine version", value: provenance.engine_version },
    { term: "Environment version", value: provenance.environment_version },
    { term: "Container image digest", value: provenance.container_image_digest },
    { term: "Compute node", value: provenance.node_identity },
    { term: "Reference genome", value: provenance.reference_genome_resource_id },
    { term: "Parameters digest", value: provenance.parameters_digest },
  ];
}

export function ResultDetailView({ resultSetId }: { resultSetId: string }) {
  const client = useMemo(() => new ApiClient(), []);
  const { publish } = useToasts();
  const [offset, setOffset] = useState(0);
  const [busyArtifact, setBusyArtifact] = useState<string | null>(null);

  const resultSet = useApiResource(
    () => client.resultSet(resultSetId),
    [client, resultSetId],
  );

  const isReadable = resultSet.data?.is_readable ?? false;
  const content = useApiResource(
    () =>
      isReadable
        ? client.resultContent(resultSetId, { offset, limit: WINDOW_SIZE })
        : Promise.resolve(null),
    [client, resultSetId, isReadable, offset],
  );

  const download = useCallback(
    async (artifactId: string) => {
      setBusyArtifact(artifactId);
      try {
        const grant = await client.requestResultArtifactDownload(resultSetId, artifactId);
        publish({
          tone: "success",
          title: "Download authorized",
          description: `The grant expires in ${grant.expires_in_seconds} seconds.`,
        });
        window.open(grant.url, "_blank", "noopener,noreferrer");
      } catch (cause) {
        const error = cause instanceof ApiError ? cause : null;
        publish({
          tone: "danger",
          title: "The download was refused",
          description: error?.message ?? "The platform API could not be reached.",
          correlationId: error?.correlationId,
        });
      } finally {
        setBusyArtifact(null);
      }
    },
    [client, publish, resultSetId],
  );

  if (resultSet.status === "loading") {
    return (
      <Card title="Result set">
        <LoadingState label="Loading result set" />
      </Card>
    );
  }

  if (resultSet.status === "error" || !resultSet.data) {
    return (
      <Card title="Result set">
        <ErrorState
          description={resultSet.error ?? undefined}
          correlationId={resultSet.correlationId ?? undefined}
          action={
            resultSet.isForbidden ? undefined : (
              <Button onClick={resultSet.reload}>Try again</Button>
            )
          }
        />
      </Card>
    );
  }

  const record = resultSet.data;
  const page = content.data;

  return (
    <>
      <Card
        title={record.result_key}
        description="State, completeness and lifecycle are separate from content. A withdrawn or superseded surface keeps every value it recorded."
        actions={<Button onClick={resultSet.reload}>Refresh</Button>}
      >
        <div className={styles.actions}>
          <span className={styles.badge}>{label(record.state)}</span>
          <span className={styles.badge}>{label(record.completeness)}</span>
          <span className={styles.badge}>{label(record.origin)}</span>
          {record.is_development_payload ? (
            <span className={styles.development}>development stub payload</span>
          ) : null}
          {record.is_readable ? null : (
            <span className={styles.muted}>content is not readable in this state</span>
          )}
        </div>
        {record.invalidation_reason ? (
          <p className={styles.muted}>Withdrawn: {record.invalidation_reason}</p>
        ) : null}
        {record.superseded_by_result_set_id ? (
          <p className={styles.muted}>
            Superseded by {record.superseded_by_result_set_id}. This surface remains as
            recorded history.
          </p>
        ) : null}
        {record.failure_code ? (
          <p className={styles.muted}>
            Failure {record.failure_code}: {record.failure_message ?? "no message given"}
          </p>
        ) : null}
      </Card>

      <Card
        title="Provenance"
        description="What this surface is attributable to. Missing entries are shown as missing and are never inferred."
      >
        {record.provenance.is_attributable ? null : (
          <p className={styles.muted}>
            The backend reports this surface as not fully attributable.
          </p>
        )}
        <dl className={styles.provenance}>
          {provenanceItems(record.provenance).map((item) => (
            <div key={item.term}>
              <dt>{item.term}</dt>
              <dd>{item.value ?? <span className={styles.muted}>not recorded</span>}</dd>
            </div>
          ))}
        </dl>
      </Card>

      <AnnotationPanel resultSetId={resultSetId} />

      <Card
        title="Artifacts"
        description="Files produced alongside the surface. Downloading requires a server-issued grant; the platform re-authorizes every request."
      >
        {record.artifacts.length === 0 ? (
          <EmptyState
            title="No artifacts recorded"
            description="This execution declared no downloadable artifact."
          />
        ) : (
          <div className={styles.scroll}>
            <table className={styles.table}>
              <caption className="visually-hidden">Artifacts of this result set</caption>
              <thead>
                <tr>
                  <th scope="col">Key</th>
                  <th scope="col">Kind</th>
                  <th scope="col">Format</th>
                  <th scope="col">State</th>
                  <th scope="col" className={styles.numeric}>
                    Size
                  </th>
                  <th scope="col">Checksum</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {record.artifacts.map((artifact) => (
                  <tr key={artifact.id}>
                    <td className={styles.wide}>{artifact.artifact_key}</td>
                    <td>{label(artifact.kind)}</td>
                    <td>{label(artifact.artifact_format)}</td>
                    <td>
                      <span className={styles.badge}>{label(artifact.state)}</span>
                      {artifact.failure_code ? (
                        <span className={styles.muted}> {artifact.failure_code}</span>
                      ) : null}
                    </td>
                    <td className={styles.numeric}>{cell(artifact.size_bytes)}</td>
                    <td>{cell(artifact.checksum_algorithm)}</td>
                    <td>
                      <Button
                        onClick={() => void download(artifact.id)}
                        isBusy={busyArtifact === artifact.id}
                      >
                        Download
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title="Content"
        description="A bounded window of the stored surface. The server decides the window size and re-authorizes each read."
        actions={
          <div className={styles.actions}>
            <Button
              onClick={() => setOffset((value) => Math.max(0, value - WINDOW_SIZE))}
              disabled={offset === 0}
            >
              Previous
            </Button>
            <Button
              onClick={() => setOffset((value) => value + WINDOW_SIZE)}
              disabled={
                !page || page.offset + page.rows.length >= page.total_rows
              }
            >
              Next
            </Button>
          </div>
        }
      >
        {!record.is_readable ? (
          <EmptyState
            title="Content is not readable"
            description="The backend does not expose content for a surface in this state. Nothing is rendered in its place."
          />
        ) : content.status === "loading" ? (
          <LoadingState label="Reading result content" />
        ) : content.status === "error" ? (
          <ErrorState
            description={content.error ?? undefined}
            correlationId={content.correlationId ?? undefined}
            action={
              content.isForbidden ? undefined : (
                <Button onClick={content.reload}>Try again</Button>
              )
            }
          />
        ) : page && page.rows.length > 0 ? (
          <>
            {page.is_development_payload ? (
              <p className={styles.development}>
                development stub content — not a scientific result
              </p>
            ) : null}
            <p className={styles.muted}>
              Rows {page.offset + 1}–{page.offset + page.rows.length} of {page.total_rows}
            </p>
            <div className={styles.scroll}>
              <table className={`${styles.table} ${styles.dense}`}>
                <caption className="visually-hidden">
                  A bounded window of the stored result surface
                </caption>
                <thead>
                  <tr>
                    {page.columns.map((column) => (
                      <th scope="col" key={column}>
                        {column}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {page.rows.map((row, rowIndex) => (
                    <tr key={page.offset + rowIndex}>
                      {row.map((value, columnIndex) => (
                        <td key={page.columns[columnIndex] ?? columnIndex}>
                          {cell(value)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        ) : (
          <EmptyState
            title="No rows in this window"
            description="The surface reported no rows at this offset. Nothing is substituted."
          />
        )}
      </Card>
    </>
  );
}
