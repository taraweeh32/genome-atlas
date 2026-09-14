"use client";

/**
 * Automated ACMG-style classification suggestions recorded for one variant.
 *
 * Three things this panel deliberately does *not* do: it does not evaluate any
 * criterion, it does not combine criteria into a classification, and it does not
 * present its content as a clinical conclusion. Every value shown was returned by
 * the versioned rules engine behind the scientific boundary.
 *
 * The decision role is shown on every row. An automated suggestion is not a
 * reviewer decision and not a final interpretation. Superseded suggestions stay
 * listed so a change in the automated answer remains visible and the interpretation
 * that cited an earlier one stays reproducible.
 */

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, DefinitionList } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useApiResource } from "@/hooks/use-api-resource";
import { ApiClient } from "@/lib/api-client";
import styles from "../results/results.module.css";

function label(value: string): string {
  return value.replace(/_/g, " ");
}

function moment(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "not recorded";
}

export function ClassificationPanel({ variantId }: { variantId: string }) {
  const client = useMemo(() => new ApiClient(), []);
  const history = useApiResource(
    () => client.classificationHistory(variantId),
    [client, variantId],
  );
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const items = history.data?.items ?? [];
  const expanded = items.find((item) => item.id === expandedId) ?? null;

  const detail = useApiResource(
    () =>
      expanded
        ? client.classificationEvaluation(expanded.evaluation_id)
        : Promise.resolve(null),
    [client, expanded?.evaluation_id],
  );

  return (
    <Card
      title="Automated classification"
      description="What the versioned rules engine suggested for this variant, under which ruleset version, and from which criterion evaluations. A suggestion is not a reviewer decision and not a final interpretation."
      actions={<Button onClick={history.reload}>Refresh</Button>}
    >
      {history.status === "loading" ? (
        <LoadingState label="Loading classifications" />
      ) : history.status === "error" ? (
        <ErrorState
          title="The classifications could not be read"
          description={history.error ?? ""}
          correlationId={history.correlationId ?? undefined}
          action={
            <Button type="button" variant="secondary" onClick={history.reload}>
              Retry
            </Button>
          }
        />
      ) : items.length === 0 ? (
        <EmptyState
          title="No automated classification is recorded for this variant"
          description="A suggestion appears here once an evaluation against an active ruleset version completes."
        />
      ) : (
        <>
          <div className={styles.scroll}>
            <table className={styles.table}>
              <caption className="visually-hidden">
                Automated classification suggestions for this variant
              </caption>
              <thead>
                <tr>
                  <th scope="col">Suggestion</th>
                  <th scope="col">Decision role</th>
                  <th scope="col">Ruleset</th>
                  <th scope="col">Version</th>
                  <th scope="col">Applied criteria</th>
                  <th scope="col">Engine</th>
                  <th scope="col">Produced</th>
                  <th scope="col">Current</th>
                </tr>
              </thead>
              <tbody>
                {items.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <button
                        type="button"
                        className={styles.linkButton}
                        onClick={() =>
                          setExpandedId(expandedId === item.id ? null : item.id)
                        }
                      >
                        {label(item.classification)}
                      </button>
                      {item.is_development_payload ? (
                        <div className={styles.muted}>
                          development payload - not scientifically valid
                        </div>
                      ) : null}
                    </td>
                    <td>{label(item.decision_role)}</td>
                    <td>
                      {item.ruleset_key}
                      <div className={styles.muted}>{item.ruleset_version}</div>
                    </td>
                    <td>{item.version_number}</td>
                    <td>
                      {item.applied_criterion_keys.join(", ") || "none applied"}
                    </td>
                    <td>{item.engine_version ?? "not recorded"}</td>
                    <td>{moment(item.produced_at)}</td>
                    <td>
                      {item.is_current ? "yes" : "superseded"}
                      {item.superseded_by_id ? (
                        <div className={styles.muted}>a newer suggestion exists</div>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {expanded ? (
            <>
              <DefinitionList
                items={[
                  { term: "Ruleset version", value: expanded.ruleset_version },
                  {
                    term: "Combination rule",
                    value: expanded.combination_rule_key ?? "not recorded",
                  },
                  { term: "Rationale", value: expanded.rationale ?? "not recorded" },
                  { term: "Evidence cited", value: expanded.evidence_ids.length },
                  { term: "Engine", value: expanded.engine_version ?? "not recorded" },
                  {
                    term: "Environment",
                    value: expanded.environment_version ?? "not recorded",
                  },
                  { term: "Node", value: expanded.node_identity ?? "not recorded" },
                  {
                    term: "Scientific execution",
                    value: expanded.scientific_execution_id ?? "not recorded",
                  },
                  { term: "Input digest", value: expanded.input_digest ?? "not recorded" },
                  {
                    term: "Configuration digest",
                    value: expanded.configuration_digest ?? "not recorded",
                  },
                ]}
              />
              {detail.status === "loading" ? (
                <LoadingState label="Loading criterion evaluations" />
              ) : detail.status === "error" ? (
                <ErrorState
                  title="The criterion evaluations could not be read"
                  description={detail.error ?? ""}
                  correlationId={detail.correlationId ?? undefined}
                />
              ) : (
                <div className={styles.scroll}>
                  <table className={styles.table}>
                    <caption className="visually-hidden">
                      Criterion evaluations behind this suggestion
                    </caption>
                    <thead>
                      <tr>
                        <th scope="col">Criterion</th>
                        <th scope="col">Applied</th>
                        <th scope="col">Strength</th>
                        <th scope="col">Direction</th>
                        <th scope="col">Origin</th>
                        <th scope="col">Evidence</th>
                        <th scope="col">Rationale</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(detail.data?.criteria ?? []).map((criterion) => (
                        <tr key={criterion.id}>
                          <td>{criterion.criterion_key}</td>
                          <td>{criterion.applied ? "yes" : "no"}</td>
                          <td>{label(criterion.strength)}</td>
                          <td>{label(criterion.direction)}</td>
                          <td>
                            {label(criterion.origin)}
                            {criterion.is_override ? (
                              <div className={styles.muted}>overrides the engine</div>
                            ) : null}
                          </td>
                          <td>{criterion.evidence_ids.length}</td>
                          <td>{criterion.rationale ?? "not recorded"}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          ) : null}
          <p className={styles.muted}>
            These are automated suggestions produced by a specific ruleset version. They
            are recorded for review and never treated as the final scientific or clinical
            decision.
          </p>
        </>
      )}
    </Card>
  );
}
