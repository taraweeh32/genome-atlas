"use client";

/**
 * Annotation resource governance.
 *
 * A platform administrator reads the registry of annotation resource versions,
 * moves a version through its lifecycle, and sees which annotation fields the
 * filtering system is currently offered. Nothing scientific happens here: a
 * resource version is an identity plus provenance, and the annotation itself is
 * produced by the external scientific subsystem.
 *
 * The registry is deliberately not editable in place. A corrected resource is a
 * new version, so historical annotation results stay reproducible.
 */

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, DefinitionList } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useToasts } from "@/components/ui/toast";
import { useApiResource } from "@/hooks/use-api-resource";
import { ApiClient, ApiError } from "@/lib/api-client";
import type { AnnotationResourceResponse } from "@/lib/annotation-types";
import queryStyles from "@/components/query/query.module.css";
import styles from "../administration.module.css";

const LIFECYCLE_STATES = ["active", "deprecated", "retired", "invalidated"] as const;

function label(value: string): string {
  return value.replace(/_/g, " ");
}

export function AnnotationGovernanceView() {
  const client = useMemo(() => new ApiClient(), []);
  const { publish } = useToasts();
  const resources = useApiResource(() => client.annotationResources({ size: 25 }), [client]);
  const profiles = useApiResource(() => client.annotationProfiles({ size: 25 }), [client]);
  const fields = useApiResource(() => client.annotationFields(), [client]);
  const [busy, setBusy] = useState<string | null>(null);

  const transition = async (resource: AnnotationResourceResponse, state: string) => {
    setBusy(`${resource.id}:${state}`);
    try {
      await client.adminTransitionAnnotationResource(resource.id, { state });
      publish({
        tone: "success",
        title: "Resource state changed",
        description: `${resource.resource_key} ${resource.version} is now ${label(state)}.`,
      });
      resources.reload();
      fields.reload();
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
        title="Annotation resource versions"
        description="Each row is one immutable resource version. A version is never edited in place; a correction is registered as a new version so earlier annotation results stay reproducible."
        actions={<Button onClick={resources.reload}>Refresh</Button>}
      >
        {resources.status === "loading" ? (
          <LoadingState label="Loading annotation resources" />
        ) : resources.status === "error" ? (
          <ErrorState
            title="The registry could not be read"
            description={resources.error ?? ""}
            correlationId={resources.correlationId ?? undefined}
            action={
              <Button type="button" variant="secondary" onClick={resources.reload}>
                Retry
              </Button>
            }
          />
        ) : (resources.data?.items.length ?? 0) === 0 ? (
          <EmptyState
            title="No annotation resource is registered"
            description="Register a resource version to make its fields available to filtering."
          />
        ) : (
          <div className={styles.scroll}>
            <table className={styles.table}>
              <caption className="visually-hidden">
                Registered annotation resource versions
              </caption>
              <thead>
                <tr>
                  <th scope="col">Resource</th>
                  <th scope="col">Version</th>
                  <th scope="col">Category</th>
                  <th scope="col">Assembly</th>
                  <th scope="col">State</th>
                  <th scope="col">Fields</th>
                  <th scope="col">Lifecycle</th>
                </tr>
              </thead>
              <tbody>
                {resources.data?.items.map((resource) => (
                  <tr key={resource.id}>
                    <td>
                      {resource.display_name}
                      <div className={styles.muted}>{resource.resource_key}</div>
                    </td>
                    <td>{resource.version}</td>
                    <td>{label(resource.category)}</td>
                    <td>
                      {resource.genome_assembly ?? (
                        <span className={styles.muted}>not declared</span>
                      )}
                    </td>
                    <td>
                      <span className={styles.badge}>{label(resource.state)}</span>
                      {resource.is_usable ? null : (
                        <div className={styles.muted}>not usable</div>
                      )}
                    </td>
                    <td>{resource.fields.length}</td>
                    <td>
                      <div className={styles.actions}>
                        {LIFECYCLE_STATES.filter((state) => state !== resource.state).map(
                          (state) => (
                            <Button
                              key={state}
                              type="button"
                              variant="secondary"
                              disabled={busy !== null}
                              onClick={() => transition(resource, state)}
                            >
                              {busy === `${resource.id}:${state}`
                                ? "Working"
                                : label(state)}
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
        title="Annotation profiles"
        description="A profile pins the exact resource versions and parameters an annotation run uses. A profile version referenced by a run can never change."
        actions={<Button onClick={profiles.reload}>Refresh</Button>}
      >
        {profiles.status === "loading" ? (
          <LoadingState label="Loading profiles" />
        ) : profiles.status === "error" ? (
          <ErrorState
            title="The profiles could not be read"
            description={profiles.error ?? ""}
            correlationId={profiles.correlationId ?? undefined}
          />
        ) : (profiles.data?.items.length ?? 0) === 0 ? (
          <EmptyState
            title="No annotation profile exists"
            description="A profile is required before annotation can be requested."
          />
        ) : (
          profiles.data?.items.map((profile) => (
            <DefinitionList
              key={profile.id}
              items={[
                { term: "Profile", value: profile.name },
                { term: "State", value: label(profile.state) },
                { term: "Latest version", value: profile.latest_version_number },
                { term: "Offered", value: profile.is_offered ? "yes" : "no" },
                { term: "Referenced by a run", value: profile.is_referenced ? "yes" : "no" },
                {
                  term: "Pinned resources",
                  value:
                    profile.versions
                      .at(-1)
                      ?.resources.map(
                        (binding) =>
                          `${binding.resource_key} ${binding.resource_version}`,
                      )
                      .join(", ") ?? "none recorded",
                },
              ]}
            />
          ))
        )}
      </Card>

      <Card
        title="Annotation fields offered to filtering"
        description="Fields declared by usable resource versions. Filtering consumes them through the field dictionary and knows nothing about how they were produced."
        actions={<Button onClick={fields.reload}>Refresh</Button>}
      >
        {fields.status === "loading" ? (
          <LoadingState label="Loading annotation fields" />
        ) : fields.status === "error" ? (
          <ErrorState
            title="The annotation fields could not be read"
            description={fields.error ?? ""}
            correlationId={fields.correlationId ?? undefined}
          />
        ) : (fields.data?.items.length ?? 0) === 0 ? (
          <EmptyState
            title="No annotation field is offered"
            description="Activate a resource version to publish its declared fields."
          />
        ) : (
          <>
            <p className={styles.muted}>
              Field dictionary version {fields.data?.registry_version}
            </p>
            <div className={styles.scroll}>
              <table className={styles.table}>
                <caption className="visually-hidden">Offered annotation fields</caption>
                <thead>
                  <tr>
                    <th scope="col">Field</th>
                    <th scope="col">Type</th>
                    <th scope="col">Source</th>
                    <th scope="col">Operators</th>
                    <th scope="col">Available</th>
                  </tr>
                </thead>
                <tbody>
                  {fields.data?.items.map((field) => (
                    <tr key={field.id}>
                      <td>
                        {field.label}
                        <div className={styles.muted}>{field.id}</div>
                      </td>
                      <td>{label(field.data_type)}</td>
                      <td>
                        {field.source_resource_key ? (
                          `${field.source_resource_key} ${field.source_resource_version ?? ""}`
                        ) : (
                          <span className={styles.muted}>not recorded</span>
                        )}
                      </td>
                      <td>{field.operators.join(", ")}</td>
                      <td>{field.available ? "yes" : "no"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
