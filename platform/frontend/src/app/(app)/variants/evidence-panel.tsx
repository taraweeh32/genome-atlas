"use client";

/**
 * Evidence recorded about one variant.
 *
 * Three things this panel deliberately does *not* do: it does not weigh evidence,
 * it does not resolve disagreement, and it does not display a classification. It
 * shows what each source or curator stated, which version of that statement is
 * current, and where two retained records disagree.
 *
 * Disagreement is shown first and left standing. The interpretation layer and the
 * people using it decide; the browser never does.
 */

import { useMemo } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useApiResource } from "@/hooks/use-api-resource";
import { ApiClient } from "@/lib/api-client";
import type { EvidenceRecordResponse } from "@/lib/evidence-types";
import styles from "../results/results.module.css";

function label(value: string): string {
  return value.replace(/_/g, " ");
}

function moment(value: string | null): string {
  return value ? new Date(value).toLocaleDateString() : "not recorded";
}

/** How the record came to exist: a source delivered it, or a person stated it. */
function attribution(record: EvidenceRecordResponse): string {
  if (record.source_key) {
    return `${record.source_key} ${record.source_version ?? ""}`.trim();
  }
  return `${label(record.origin)} by ${record.created_by ?? "unknown"}`;
}

export function EvidencePanel({ variantId }: { variantId: string }) {
  const client = useMemo(() => new ApiClient(), []);
  const history = useApiResource(() => client.evidenceHistory(variantId), [client, variantId]);
  const conflicts = useApiResource(
    () => client.evidenceConflicts(variantId),
    [client, variantId],
  );

  const records = history.data?.records ?? [];
  const conflicting = conflicts.data?.conflicts ?? [];

  const reload = () => {
    history.reload();
    conflicts.reload();
  };

  return (
    <Card
      title="Evidence"
      description="What each source and curator stated about this variant, every version of it, and any disagreement between them. Nothing here is a classification."
      actions={<Button onClick={reload}>Refresh</Button>}
    >
      {history.status === "loading" ? (
        <LoadingState label="Loading evidence" />
      ) : history.status === "error" ? (
        <ErrorState
          title="The evidence could not be read"
          description={history.error ?? ""}
          correlationId={history.correlationId ?? undefined}
          action={
            <Button type="button" variant="secondary" onClick={reload}>
              Retry
            </Button>
          }
        />
      ) : records.length === 0 ? (
        <EmptyState
          title="No evidence is recorded for this variant"
          description="Evidence appears here once a registered source supplies it or a curator records it."
        />
      ) : (
        <>
          {conflicting.length > 0 ? (
            <div className={styles.scroll}>
              <table className={styles.table}>
                <caption className="visually-hidden">Retained disagreement</caption>
                <thead>
                  <tr>
                    <th scope="col">Disagreement</th>
                    <th scope="col">Category</th>
                    <th scope="col">Between</th>
                    <th scope="col">Records</th>
                  </tr>
                </thead>
                <tbody>
                  {conflicting.map((conflict) => (
                    <tr key={`${conflict.group_key}:${conflict.kind}`}>
                      <td>{label(conflict.kind)}</td>
                      <td>{label(conflict.category)}</td>
                      <td>{conflict.source_keys.join(" vs ")}</td>
                      <td>{conflict.evidence_ids.length}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className={styles.muted}>
                Conflicting evidence is kept exactly as stated. Neither record was
                overwritten and neither was preferred.
              </p>
            </div>
          ) : null}

          <div className={styles.scroll}>
            <table className={styles.table}>
              <caption className="visually-hidden">Evidence recorded for this variant</caption>
              <thead>
                <tr>
                  <th scope="col">Stated by</th>
                  <th scope="col">Category</th>
                  <th scope="col">Direction</th>
                  <th scope="col">Strength</th>
                  <th scope="col">Applicability</th>
                  <th scope="col">Context</th>
                  <th scope="col">Version</th>
                  <th scope="col">State</th>
                  <th scope="col">Retrieved</th>
                </tr>
              </thead>
              <tbody>
                {records.map((record) => (
                  <tr key={record.id}>
                    <td>
                      {attribution(record)}
                      {record.source_identifier ? (
                        <div className={styles.muted}>{record.source_identifier}</div>
                      ) : null}
                    </td>
                    <td>{label(record.category)}</td>
                    <td>{label(record.direction)}</td>
                    <td>{label(record.strength)}</td>
                    <td>{label(record.applicability)}</td>
                    <td>
                      {record.context.gene_symbol ?? "—"}
                      {record.context.condition_term ? (
                        <div className={styles.muted}>{record.context.condition_term}</div>
                      ) : null}
                    </td>
                    <td>{record.version_number}</td>
                    <td>
                      {label(record.state)}
                      {record.current ? null : (
                        <div className={styles.muted}>not current</div>
                      )}
                    </td>
                    <td>{moment(record.retrieved_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className={styles.muted}>
            Superseded versions stay listed so an interpretation that cited one remains
            reproducible.
          </p>
        </>
      )}
    </Card>
  );
}
