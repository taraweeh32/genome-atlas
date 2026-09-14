"use client";

/**
 * Saved filters, filter presets, saved prioritizations and prioritization
 * presets, with their version history and lifecycle.
 *
 * Three rules are visible in this surface:
 *
 * - **Editing never rewrites history.** Renaming changes metadata; changing the
 *   content issues a new version. A version an execution referenced is marked as
 *   referenced and cannot change.
 * - **Every control is server-authorized.** Buttons are enabled from the
 *   `capabilities` the server returned for that record, and the server re-checks
 *   the permission on the request. The UI is not the authority.
 * - **Concurrent edits are not silently merged.** Each mutation carries the
 *   version the caller saw; a stale write is refused and reported.
 */

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useToasts } from "@/components/ui/toast";
import { useApiResource } from "@/hooks/use-api-resource";
import { ApiClient, ApiError } from "@/lib/api-client";
import type {
  QueryConfigurationKind,
  QueryConfigurationResponse,
  QueryConfigurationVersionResponse,
} from "@/lib/query-types";
import queryStyles from "@/components/query/query.module.css";
import styles from "../results/results.module.css";

const SECTIONS: readonly {
  kind: QueryConfigurationKind;
  title: string;
  description: string;
}[] = [
  {
    kind: "filters",
    title: "Saved filters",
    description:
      "Filter expressions you or your project saved. Editing the expression creates a new version; earlier versions stay readable.",
  },
  {
    kind: "filter-presets",
    title: "Filter presets",
    description:
      "Shared filters published at platform, organization, project or personal scope. A published version is immutable.",
  },
  {
    kind: "rankings",
    title: "Saved prioritizations",
    description:
      "Prioritization configurations: method, fields, weights, direction and tie-breakers. A prioritization score is an ordering aid, not a clinical assessment.",
  },
  {
    kind: "ranking-presets",
    title: "Prioritization presets",
    description:
      "Shared prioritization configurations, versioned and scoped exactly like filter presets.",
  },
];

export function QueryLibraryView() {
  return (
    <div className={queryStyles.builder}>
      {SECTIONS.map((section) => (
        <ConfigurationSection key={section.kind} {...section} />
      ))}
    </div>
  );
}

function ConfigurationSection({
  kind,
  title,
  description,
}: {
  readonly kind: QueryConfigurationKind;
  readonly title: string;
  readonly description: string;
}) {
  const client = useMemo(() => new ApiClient(), []);
  const { publish } = useToasts();
  const resource = useApiResource(
    () => client.queryConfigurations(kind, { size: 50 }),
    [client, kind],
  );
  const [expanded, setExpanded] = useState<string | null>(null);
  const [versions, setVersions] = useState<
    readonly QueryConfigurationVersionResponse[]
  >([]);
  const [busy, setBusy] = useState<string | null>(null);

  function report(cause: unknown, heading: string) {
    const error = cause instanceof ApiError ? cause : null;
    publish({
      tone: "danger",
      title: heading,
      description: error?.message,
      correlationId: error?.correlationId,
    });
  }

  async function showVersions(record: QueryConfigurationResponse) {
    if (expanded === record.id) {
      setExpanded(null);
      setVersions([]);
      return;
    }
    try {
      const response = await client.queryConfigurationVersions(kind, record.id);
      setVersions(response.items);
      setExpanded(record.id);
    } catch (cause) {
      report(cause, "The version history could not be read");
    }
  }

  async function rename(record: QueryConfigurationResponse) {
    const name = window.prompt("New name", record.name);
    if (!name || name === record.name) return;
    setBusy(record.id);
    try {
      await client.updateQueryConfiguration(kind, record.id, {
        expected_version: record.version,
        name,
      });
      publish({ tone: "success", title: "Renamed" });
      resource.reload();
    } catch (cause) {
      report(cause, "The name was not changed");
    } finally {
      setBusy(null);
    }
  }

  async function transition(
    record: QueryConfigurationResponse,
    action: "publish" | "archive" | "restore",
  ) {
    setBusy(record.id);
    try {
      await client.transitionQueryConfiguration(kind, record.id, action, {
        expected_version: record.version,
      });
      publish({ tone: "success", title: `Configuration ${action}ed` });
      resource.reload();
    } catch (cause) {
      report(cause, `The configuration was not ${action}ed`);
    } finally {
      setBusy(null);
    }
  }

  async function remove(record: QueryConfigurationResponse) {
    if (
      !window.confirm(
        `Delete “${record.name}”? It is retained for recovery and existing executions keep the version they used.`,
      )
    ) {
      return;
    }
    setBusy(record.id);
    try {
      await client.deleteQueryConfiguration(kind, record.id, {
        expected_version: record.version,
      });
      publish({ tone: "success", title: "Moved to deleted state" });
      resource.reload();
    } catch (cause) {
      report(cause, "The configuration was not deleted");
    } finally {
      setBusy(null);
    }
  }

  const can = (record: QueryConfigurationResponse, capability: string) =>
    record.capabilities.includes(capability);

  return (
    <Card title={title} description={description}>
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
      ) : (resource.data?.items ?? []).length === 0 ? (
        <EmptyState
          title="Nothing saved yet"
          description="Assemble a filter or a prioritization in the variant query and save it there."
        />
      ) : (
        <div className={styles.scroll}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Name</th>
                <th scope="col">Scope</th>
                <th scope="col">State</th>
                <th scope="col">Latest version</th>
                <th scope="col">Referenced</th>
                <th scope="col">Updated</th>
                <th scope="col">Actions</th>
              </tr>
            </thead>
            <tbody>
              {(resource.data?.items ?? []).map((record) => (
                <tr key={record.id}>
                  <td>
                    {record.name}
                    {record.description ? (
                      <p className={queryStyles.hint}>{record.description}</p>
                    ) : null}
                  </td>
                  <td>{record.scope}</td>
                  <td>
                    {record.state}
                    {record.deletion_state !== "active"
                      ? ` · ${record.deletion_state}`
                      : ""}
                  </td>
                  <td className={styles.numeric}>{record.latest_version_number}</td>
                  <td>{record.is_referenced ? "yes" : "no"}</td>
                  <td>{record.updated_at}</td>
                  <td>
                    <div className={queryStyles.rowActions}>
                      <Button
                        type="button"
                        variant="secondary"
                        onClick={() => void showVersions(record)}
                      >
                        {expanded === record.id ? "Hide versions" : "Versions"}
                      </Button>
                      {can(record, "manage") ? (
                        <>
                          <Button
                            type="button"
                            variant="secondary"
                            disabled={busy === record.id}
                            onClick={() => void rename(record)}
                          >
                            Rename
                          </Button>
                          {record.state === "draft" ? (
                            <Button
                              type="button"
                              variant="secondary"
                              disabled={busy === record.id}
                              onClick={() => void transition(record, "publish")}
                            >
                              Publish
                            </Button>
                          ) : null}
                          {record.state === "published" ? (
                            <Button
                              type="button"
                              variant="secondary"
                              disabled={busy === record.id}
                              onClick={() => void transition(record, "archive")}
                            >
                              Archive
                            </Button>
                          ) : null}
                          {record.state === "archived" ? (
                            <Button
                              type="button"
                              variant="secondary"
                              disabled={busy === record.id}
                              onClick={() => void transition(record, "restore")}
                            >
                              Restore
                            </Button>
                          ) : null}
                          <Button
                            type="button"
                            variant="danger"
                            disabled={busy === record.id}
                            onClick={() => void remove(record)}
                          >
                            Delete
                          </Button>
                        </>
                      ) : (
                        <span className={queryStyles.hint}>Read only</span>
                      )}
                    </div>
                    {expanded === record.id ? (
                      <ul>
                        {versions.map((version) => (
                          <li key={version.id} className={queryStyles.hint}>
                            v{version.version_number} · hash {version.canonical_hash} ·
                            dictionary {version.field_dictionary_version} ·{" "}
                            {version.is_referenced
                              ? "referenced by an execution (immutable)"
                              : "not referenced"}
                            {version.change_note ? ` · ${version.change_note}` : ""}
                          </li>
                        ))}
                      </ul>
                    ) : null}
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
