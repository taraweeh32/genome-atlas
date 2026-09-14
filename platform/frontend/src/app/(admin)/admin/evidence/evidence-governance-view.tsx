"use client";

/**
 * Evidence source governance.
 *
 * A platform administrator reads the registry of evidence source versions, moves
 * a version through its lifecycle, and inspects how deliveries from those sources
 * validated. Nothing scientific happens here: a source version is an identity
 * plus release and retrieval provenance, and the evidence itself is whatever the
 * source stated.
 *
 * The registry is deliberately not editable in place. A corrected release is a new
 * version, so evidence naming an earlier release stays reproducible.
 */

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, DefinitionList } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useToasts } from "@/components/ui/toast";
import { useApiResource } from "@/hooks/use-api-resource";
import { ApiClient, ApiError } from "@/lib/api-client";
import type { EvidenceSourceResponse } from "@/lib/evidence-types";
import queryStyles from "@/components/query/query.module.css";
import styles from "../administration.module.css";

const LIFECYCLE_STATES = ["active", "deprecated", "retired", "invalidated"] as const;

function label(value: string): string {
  return value.replace(/_/g, " ");
}

function moment(value: string | null): string {
  return value ? new Date(value).toLocaleString() : "not recorded";
}

export function EvidenceGovernanceView() {
  const client = useMemo(() => new ApiClient(), []);
  const { publish } = useToasts();
  const sources = useApiResource(() => client.evidenceSources({ size: 25 }), [client]);
  const deliveries = useApiResource(() => client.evidenceDeliveries({ size: 10 }), [client]);
  const [busy, setBusy] = useState<string | null>(null);

  const transition = async (source: EvidenceSourceResponse, state: string) => {
    setBusy(`${source.id}:${state}`);
    try {
      await client.adminTransitionEvidenceSource(source.id, { state });
      publish({
        tone: "success",
        title: "Source state changed",
        description: `${source.source_key} ${source.version} is now ${label(state)}.`,
      });
      sources.reload();
    } catch (cause) {
      const error = cause instanceof ApiError ? cause : null;
      publish({
        tone: "danger",
        title: "The change was refused",
        description: error?.message ?? "The platform API could not be reached.",
        correlationId: error?.correlationId,
      });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className={queryStyles.builder}>
      <Card
        title="Evidence source versions"
        description="Each row is one registered release of one source. A release is never edited in place; a correction is registered as a new version so evidence citing the earlier release stays reproducible."
        actions={<Button onClick={sources.reload}>Refresh</Button>}
      >
        {sources.status === "loading" ? (
          <LoadingState label="Loading evidence sources" />
        ) : sources.status === "error" ? (
          <ErrorState
            title="The registry could not be read"
            description={sources.error ?? ""}
            correlationId={sources.correlationId ?? undefined}
            action={
              <Button type="button" variant="secondary" onClick={sources.reload}>
                Retry
              </Button>
            }
          />
        ) : (sources.data?.items.length ?? 0) === 0 ? (
          <EmptyState
            title="No evidence source is registered"
            description="Register and activate a source version before evidence from it can be ingested."
          />
        ) : (
          <div className={styles.scroll}>
            <table className={styles.table}>
              <caption className="visually-hidden">
                Registered evidence source versions
              </caption>
              <thead>
                <tr>
                  <th scope="col">Source</th>
                  <th scope="col">Version</th>
                  <th scope="col">Category</th>
                  <th scope="col">Release</th>
                  <th scope="col">Supplies</th>
                  <th scope="col">States strength</th>
                  <th scope="col">State</th>
                  <th scope="col">Lifecycle</th>
                </tr>
              </thead>
              <tbody>
                {sources.data?.items.map((source) => (
                  <tr key={source.id}>
                    <td>
                      {source.display_name}
                      <div className={styles.muted}>{source.source_key}</div>
                    </td>
                    <td>{source.version}</td>
                    <td>{label(source.category)}</td>
                    <td>
                      {source.release_label ?? (
                        <span className={styles.muted}>not declared</span>
                      )}
                      <div className={styles.muted}>
                        released {moment(source.released_at)}
                      </div>
                      <div className={styles.muted}>
                        retrieved {moment(source.retrieved_at)}
                      </div>
                    </td>
                    <td>{source.supplies.map(label).join(", ") || "nothing declared"}</td>
                    <td>{source.supplies_strength ? "yes" : "no"}</td>
                    <td>
                      <span className={styles.badge}>{label(source.state)}</span>
                      {source.usable ? null : (
                        <div className={styles.muted}>cannot supply evidence</div>
                      )}
                    </td>
                    <td>
                      <div className={styles.actions}>
                        {LIFECYCLE_STATES.filter((state) => state !== source.state).map(
                          (state) => (
                            <Button
                              key={state}
                              type="button"
                              variant="secondary"
                              disabled={busy !== null}
                              onClick={() => transition(source, state)}
                            >
                              {busy === `${source.id}:${state}` ? "Working" : label(state)}
                            </Button>
                          ),
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title="Recent evidence deliveries"
        description="What each delivery claimed and what was actually stored. Rejected records are counted, never repaired, and a redelivery of the same payload stores nothing twice."
        actions={<Button onClick={deliveries.reload}>Refresh</Button>}
      >
        {deliveries.status === "loading" ? (
          <LoadingState label="Loading deliveries" />
        ) : deliveries.status === "error" ? (
          <ErrorState
            title="The deliveries could not be read"
            description={deliveries.error ?? ""}
            correlationId={deliveries.correlationId ?? undefined}
          />
        ) : (deliveries.data?.items.length ?? 0) === 0 ? (
          <EmptyState
            title="No evidence delivery has been recorded"
            description="Deliveries appear here once a source supplies evidence."
          />
        ) : (
          deliveries.data?.items.map((batch) => (
            <DefinitionList
              key={batch.id}
              items={[
                { term: "Source", value: `${batch.source_key} ${batch.source_version}` },
                { term: "Outcome", value: label(batch.state) },
                { term: "Origin", value: label(batch.origin) },
                { term: "Claimed", value: batch.claimed_record_count },
                { term: "Stored", value: batch.stored_record_count },
                { term: "Superseded", value: batch.superseded_record_count },
                { term: "Duplicate", value: batch.duplicate_record_count },
                { term: "Rejected", value: batch.rejected_record_count },
                { term: "Retrieved", value: moment(batch.retrieved_at) },
                {
                  term: "Correlation",
                  value: batch.correlation_id ?? "not recorded",
                },
                {
                  term: "Development payload",
                  value:
                    batch.provenance["is_development_payload"] === true
                      ? "yes - not scientifically valid"
                      : "no",
                },
              ]}
            />
          ))
        )}
      </Card>
    </div>
  );
}
