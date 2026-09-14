"use client";

/**
 * Annotation status and provenance for one result surface.
 *
 * This panel is metadata only. Annotation values themselves live in the
 * analytical layer and are read through filtering and the variant surfaces —
 * millions of annotation rows are never delivered to a screen. Nothing here
 * computes or interprets an annotation: the backend records what an external
 * scientific tool declared, and this panel shows it, including when a value or a
 * provenance entry is missing.
 */

import { useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useApiResource } from "@/hooks/use-api-resource";
import { ApiClient } from "@/lib/api-client";
import type {
  AnnotationResultResponse,
  AnnotationRunResponse,
} from "@/lib/annotation-types";
import styles from "../results.module.css";

function label(value: string): string {
  return value.replace(/_/g, " ");
}

function provenanceItems(
  result: AnnotationResultResponse,
): readonly { term: string; value: string | number | null }[] {
  return [
    { term: "Annotation run", value: result.annotation_run_id },
    { term: "Resource", value: `${result.resource_key} ${result.resource_version}` },
    { term: "Profile version", value: result.profile_version_id },
    { term: "Scientific execution", value: result.scientific_execution_id },
    { term: "Engine version", value: result.engine_version },
    { term: "Environment version", value: result.environment_version },
    { term: "Container image digest", value: result.container_image_digest },
    { term: "Compute node", value: result.node_identity },
    { term: "Reference assembly", value: result.genome_assembly },
    { term: "Configuration digest", value: result.parameters_digest },
    { term: "Contract version", value: result.contract_version },
    { term: "Stored values", value: result.stored_record_count },
    { term: "Rejected values", value: result.rejected_record_count },
    { term: "Analytical location", value: result.analytical_location },
  ];
}

export function AnnotationPanel({ resultSetId }: { resultSetId: string }) {
  const client = useMemo(() => new ApiClient(), []);
  const runs = useApiResource(
    () => client.annotationRuns({ result_set_id: resultSetId, size: 10 }),
    [client, resultSetId],
  );
  const results = useApiResource(
    () => client.annotationResults(resultSetId, { size: 10 }),
    [client, resultSetId],
  );

  const loading = runs.status === "loading" || results.status === "loading";
  const failed = runs.status === "error" || results.status === "error";

  return (
    <Card
      title="Annotation"
      description="Which annotation resource versions were applied to this surface, and what each run is attributable to. Annotation values are read through filtering, never listed here."
      actions={
        <Button
          onClick={() => {
            runs.reload();
            results.reload();
          }}
        >
          Refresh
        </Button>
      }
    >
      {loading ? <LoadingState label="Loading annotation status" /> : null}
      {failed ? (
        <ErrorState
          title="The annotation status could not be read"
          description={runs.error ?? results.error ?? undefined}
          correlationId={runs.correlationId ?? results.correlationId ?? undefined}
        />
      ) : null}
      {!loading && !failed ? (
        <AnnotationBody
          runs={runs.data?.items ?? []}
          results={results.data?.items ?? []}
        />
      ) : null}
    </Card>
  );
}

function AnnotationBody({
  runs,
  results,
}: {
  runs: readonly AnnotationRunResponse[];
  results: readonly AnnotationResultResponse[];
}) {
  if (runs.length === 0 && results.length === 0) {
    return (
      <EmptyState
        title="This surface has not been annotated"
        description="No annotation run has been requested for it."
      />
    );
  }

  return (
    <>
      {runs.length > 0 ? (
        <div className={styles.scroll}>
          <table className={styles.table}>
            <caption className="visually-hidden">Annotation runs of this surface</caption>
            <thead>
              <tr>
                <th scope="col">Run</th>
                <th scope="col">State</th>
                <th scope="col">Capability</th>
                <th scope="col">Profile version</th>
                <th scope="col">Requested</th>
                <th scope="col">Findings</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.id}>
                  <td>{run.id}</td>
                  <td>
                    <span className={styles.badge}>{label(run.state)}</span>
                    {run.failure_code ? (
                      <span className={styles.muted}> {run.failure_code}</span>
                    ) : null}
                  </td>
                  <td>{run.capability_id}</td>
                  <td>{run.profile_version_number}</td>
                  <td>{new Date(run.requested_at).toLocaleString()}</td>
                  <td>{run.findings.length}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {results.map((result) => (
        <section key={result.id}>
          <h3>
            {result.resource_key} {result.resource_version} — version{" "}
            {result.version_number}
          </h3>
          <div className={styles.actions}>
            <span className={styles.badge}>{label(result.state)}</span>
            <span className={styles.badge}>{label(result.completeness)}</span>
            {result.is_development_payload ? (
              <span className={styles.development}>development stub payload</span>
            ) : null}
            {result.superseded_by_id ? (
              <span className={styles.muted}>
                superseded by {result.superseded_by_id}; kept as recorded history
              </span>
            ) : null}
          </div>
          <dl className={styles.provenance}>
            {provenanceItems(result).map((item) => (
              <div key={item.term}>
                <dt>{item.term}</dt>
                <dd>
                  {item.value === null || item.value === "" ? (
                    <span className={styles.muted}>not recorded</span>
                  ) : (
                    String(item.value)
                  )}
                </dd>
              </div>
            ))}
          </dl>
          <p className={styles.muted}>
            Fields: {result.field_keys.length > 0 ? result.field_keys.join(", ") : "none"}
          </p>
        </section>
      ))}
    </>
  );
}
