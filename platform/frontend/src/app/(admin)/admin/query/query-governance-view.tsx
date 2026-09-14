"use client";

/**
 * Filtering and prioritization governance.
 *
 * Two audiences share this surface, and the backend decides which parts each one
 * may use:
 *
 * - A **platform administrator** reads the field-dictionary registry, the
 *   prioritization-method registry and the platform safety limits, and manages
 *   platform-scoped presets.
 * - An **organization administrator** manages organization-scoped presets, always
 *   inside the platform limits shown here.
 *
 * The registries are read-only in this release: fields and methods are declared
 * by the platform, and a field or method the platform did not publish cannot be
 * invented from a screen. Availability, limits and preset lifecycle are the
 * governance controls that do exist.
 */

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, DefinitionList } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useToasts } from "@/components/ui/toast";
import { useApiResource } from "@/hooks/use-api-resource";
import { ApiClient, ApiError } from "@/lib/api-client";
import type { QueryConfigurationKind } from "@/lib/query-types";
import queryStyles from "@/components/query/query.module.css";
import styles from "../administration.module.css";

const GOVERNED_SCOPES = new Set(["platform", "organization"]);

export function QueryGovernanceView() {
  const client = useMemo(() => new ApiClient(), []);
  const fields = useApiResource(() => client.adminFilterFields(), [client]);
  const methods = useApiResource(() => client.adminRankingMethods(), [client]);
  const limits = useApiResource(() => client.adminQueryLimits(), [client]);

  return (
    <div className={queryStyles.builder}>
      <Card
        title="Safety limits"
        description="Configuration-driven bounds every filter and query is checked against. They protect the analytical layer from pathological queries; they are not scientific parameters."
      >
        {limits.status === "loading" ? (
          <LoadingState label="Loading limits" />
        ) : limits.status === "error" ? (
          <ErrorState
            title="The limits could not be read"
            description={limits.error ?? ""}
            correlationId={limits.correlationId ?? undefined}
            action={
              <Button type="button" variant="secondary" onClick={limits.reload}>
                Retry
              </Button>
            }
          />
        ) : limits.data ? (
          <DefinitionList
            items={[
              { term: "Field dictionary", value: limits.data.field_dictionary_version },
              { term: "Software version", value: limits.data.software_version },
              { term: "Maximum conditions", value: limits.data.max_conditions },
              { term: "Maximum nesting depth", value: limits.data.max_depth },
              {
                term: "Maximum values per condition",
                value: limits.data.max_values_per_condition,
              },
              { term: "Maximum value length", value: limits.data.max_value_length },
              {
                term: "Maximum expression size (bytes)",
                value: limits.data.max_expression_bytes,
              },
              {
                term: "Maximum text-match conditions",
                value: limits.data.max_text_match_conditions,
              },
              { term: "Maximum page size", value: limits.data.max_page_size },
            ]}
          />
        ) : null}
      </Card>

      <Card
        title="Filter field registry"
        description="Every field a filter may name, with its data type, operators, missing-value semantics and availability. Filtering consumes these recorded fields and derives none of them."
      >
        {fields.status === "loading" ? (
          <LoadingState label="Loading the field registry" />
        ) : fields.status === "error" ? (
          <ErrorState
            title="The field registry could not be read"
            description={fields.error ?? ""}
            correlationId={fields.correlationId ?? undefined}
            action={
              <Button type="button" variant="secondary" onClick={fields.reload}>
                Retry
              </Button>
            }
          />
        ) : (
          <div className={styles.scroll}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Field</th>
                  <th scope="col">Type</th>
                  <th scope="col">Category</th>
                  <th scope="col">Origin</th>
                  <th scope="col">Operators</th>
                  <th scope="col">Missing semantics</th>
                  <th scope="col">High cardinality</th>
                  <th scope="col">Available</th>
                </tr>
              </thead>
              <tbody>
                {(fields.data?.fields ?? []).map((field) => (
                  <tr key={field.id}>
                    <td>
                      {field.label}
                      <p className={queryStyles.hint}>{field.id}</p>
                    </td>
                    <td>{field.data_type}</td>
                    <td>{field.category}</td>
                    <td>{field.origin}</td>
                    <td>{field.supported_operators.length}</td>
                    <td>{field.missing_semantics.join(", ")}</td>
                    <td>{field.high_cardinality ? "searchable, bounded" : "no"}</td>
                    <td>{field.available ? "yes" : "no"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card
        title="Prioritization method registry"
        description="Methods available for prioritization. Every shipped method is deterministic and transparent, and none is a validated clinical measure."
      >
        {methods.status === "loading" ? (
          <LoadingState label="Loading the method registry" />
        ) : methods.status === "error" ? (
          <ErrorState
            title="The method registry could not be read"
            description={methods.error ?? ""}
            correlationId={methods.correlationId ?? undefined}
            action={
              <Button type="button" variant="secondary" onClick={methods.reload}>
                Retry
              </Button>
            }
          />
        ) : (
          <div className={styles.scroll}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th scope="col">Method</th>
                  <th scope="col">Version</th>
                  <th scope="col">Implementation</th>
                  <th scope="col">Components</th>
                  <th scope="col">Deterministic</th>
                  <th scope="col">Scientifically validated</th>
                  <th scope="col">Available</th>
                </tr>
              </thead>
              <tbody>
                {(methods.data?.items ?? []).map((method) => (
                  <tr key={method.id}>
                    <td>
                      {method.name}
                      <p className={queryStyles.hint}>{method.description}</p>
                    </td>
                    <td>{method.version}</td>
                    <td>{method.implementation_id}</td>
                    <td>
                      {method.min_components}–{method.max_components}
                    </td>
                    <td>{method.deterministic ? "yes" : "no"}</td>
                    <td>{method.scientifically_validated ? "yes" : "no"}</td>
                    <td>{method.available ? "yes" : "no"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <PresetGovernance kind="filter-presets" title="Filter presets" />
      <PresetGovernance kind="ranking-presets" title="Prioritization presets" />
    </div>
  );
}

/**
 * Lifecycle governance for shared presets.
 *
 * Only platform- and organization-scoped records appear: this is the governance
 * surface, not a personal library. Each action is enabled from the capabilities
 * the server returned for that record and re-authorized on the request.
 */
function PresetGovernance({
  kind,
  title,
}: {
  readonly kind: QueryConfigurationKind;
  readonly title: string;
}) {
  const client = useMemo(() => new ApiClient(), []);
  const { publish } = useToasts();
  const resource = useApiResource(
    () => client.queryConfigurations(kind, { size: 100 }),
    [client, kind],
  );
  const [busy, setBusy] = useState<string | null>(null);

  const governed = (resource.data?.items ?? []).filter((item) =>
    GOVERNED_SCOPES.has(item.scope),
  );

  async function transition(
    id: string,
    version: number,
    action: "publish" | "archive" | "restore",
  ) {
    setBusy(id);
    try {
      await client.transitionQueryConfiguration(kind, id, action, {
        expected_version: version,
      });
      publish({ tone: "success", title: `Preset ${action}ed` });
      resource.reload();
    } catch (cause) {
      const error = cause instanceof ApiError ? cause : null;
      publish({
        tone: "danger",
        title: `The preset was not ${action}ed`,
        description: error?.message,
        correlationId: error?.correlationId,
      });
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card
      title={title}
      description="Platform- and organization-scoped presets. A published version is immutable: publishing a new version never changes what an earlier execution resolved."
    >
      {resource.status === "loading" ? (
        <LoadingState label={`Loading ${title.toLowerCase()}`} />
      ) : resource.status === "error" ? (
        <ErrorState
          title={`${title} could not be read`}
          description={resource.error ?? ""}
          correlationId={resource.correlationId ?? undefined}
          action={
            <Button type="button" variant="secondary" onClick={resource.reload}>
              Retry
            </Button>
          }
        />
      ) : governed.length === 0 ? (
        <EmptyState
          title="No shared presets"
          description="Platform and organization presets appear here once they are created."
        />
      ) : (
        <div className={styles.scroll}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Scope</th>
                <th scope="col">State</th>
                <th scope="col">Version</th>
                <th scope="col">Referenced</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {governed.map((preset) => (
                <tr key={preset.id}>
                  <td>{preset.name}</td>
                  <td>{preset.scope}</td>
                  <td>{preset.state}</td>
                  <td>{preset.latest_version_number}</td>
                  <td>{preset.is_referenced ? "yes" : "no"}</td>
                  <td>
                    <div className={queryStyles.rowActions}>
                      {preset.capabilities.includes("manage") ? (
                        <>
                          {preset.state === "draft" ? (
                            <Button
                              type="button"
                              variant="secondary"
                              disabled={busy === preset.id}
                              onClick={() =>
                                void transition(preset.id, preset.version, "publish")
                              }
                            >
                              Publish
                            </Button>
                          ) : null}
                          {preset.state === "published" ? (
                            <Button
                              type="button"
                              variant="secondary"
                              disabled={busy === preset.id}
                              onClick={() =>
                                void transition(preset.id, preset.version, "archive")
                              }
                            >
                              Deactivate
                            </Button>
                          ) : null}
                          {preset.state === "archived" ? (
                            <Button
                              type="button"
                              variant="secondary"
                              disabled={busy === preset.id}
                              onClick={() =>
                                void transition(preset.id, preset.version, "restore")
                              }
                            >
                              Reactivate
                            </Button>
                          ) : null}
                        </>
                      ) : (
                        <span className={queryStyles.hint}>Read only</span>
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
  );
}
