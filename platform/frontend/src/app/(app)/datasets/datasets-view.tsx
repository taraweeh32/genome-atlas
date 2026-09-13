"use client";

/**
 * Dataset list for the active workspace.
 *
 * Creation is attempted against the backend and refused there when the caller
 * may not create a dataset in that scope: the form is never a permission
 * decision. `capabilities` from the server decides which controls are rendered,
 * and archiving is still re-authorized server-side when requested.
 */

import Link from "next/link";
import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useToasts } from "@/components/ui/toast";
import { Field, authStyles as formStyles } from "@/components/auth/field";
import { useApiResource } from "@/hooks/use-api-resource";
import { useWorkspace } from "@/context/workspace-context";
import { ApiClient, ApiError } from "@/lib/api-client";
import styles from "./datasets.module.css";

/** Dataset kinds the backend accepts. Values mirror the API contract exactly. */
const DATASET_KINDS: readonly { value: string; label: string }[] = [
  { value: "variant_calls", label: "Variant calls" },
  { value: "annotation_table", label: "Annotation table" },
  { value: "phenotype_table", label: "Phenotype table" },
  { value: "sample_manifest", label: "Sample manifest" },
  { value: "coverage_summary", label: "Coverage summary" },
  { value: "other", label: "Other" },
];

const REFERENCE_BUILDS: readonly { value: string; label: string }[] = [
  { value: "grch38", label: "GRCh38" },
  { value: "grch37", label: "GRCh37" },
  { value: "t2t_chm13", label: "T2T-CHM13" },
  { value: "unspecified", label: "Not declared" },
];

export function label(value: string): string {
  return value.replace(/_/g, " ");
}

export function DatasetsView() {
  const client = useMemo(() => new ApiClient(), []);
  const { activeWorkspace, resolution } = useWorkspace();
  const { publish } = useToasts();
  const workspaceId = activeWorkspace?.id ?? null;

  const datasets = useApiResource(
    () =>
      workspaceId
        ? client.datasets({ workspace_id: workspaceId })
        : Promise.resolve({ items: [], page: { number: 1, size: 0, total: 0 } }),
    [client, workspaceId],
  );

  const [name, setName] = useState("");
  const [kind, setKind] = useState<string>("variant_calls");
  const [build, setBuild] = useState<string>("grch38");
  const [isBusy, setBusy] = useState(false);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!workspaceId) return;
    setBusy(true);
    try {
      await client.createDataset({
        workspace_id: workspaceId,
        name,
        kind,
        reference_build_declared: build,
      });
      publish({ tone: "success", title: "Dataset created" });
      setName("");
      datasets.reload();
    } catch (cause) {
      const error = cause instanceof ApiError ? cause : null;
      publish({
        tone: "danger",
        title: "The dataset was not created",
        description: error?.message ?? "The platform API could not be reached.",
        correlationId: error?.correlationId,
      });
    } finally {
      setBusy(false);
    }
  }

  if (resolution !== "resolved" || !activeWorkspace) {
    return (
      <Card title="Workspace context">
        {resolution === "error" ? (
          <ErrorState description="Workspaces could not be loaded, so no dataset list can be shown." />
        ) : (
          <LoadingState label="Resolving your workspace" />
        )}
      </Card>
    );
  }

  return (
    <>
      <Card
        title={`Datasets in ${activeWorkspace.name}`}
        description={
          activeWorkspace.kind === "personal"
            ? "Personal workspace. These inputs are private by default."
            : "Organization workspace. Access follows explicit membership and permissions."
        }
        actions={<Button onClick={datasets.reload}>Refresh</Button>}
      >
        {datasets.status === "loading" ? (
          <LoadingState label="Loading datasets" />
        ) : datasets.status === "error" ? (
          <ErrorState
            description={datasets.error ?? undefined}
            correlationId={datasets.correlationId ?? undefined}
            action={
              datasets.isForbidden ? undefined : <Button onClick={datasets.reload}>Try again</Button>
            }
          />
        ) : datasets.data && datasets.data.items.length > 0 ? (
          <ul className={styles.list}>
            {datasets.data.items.map((dataset) => (
              <li key={dataset.id} className={styles.row}>
                <div className={styles.rowMain}>
                  <span className={styles.rowTitle}>{dataset.name}</span>
                  <span className={styles.rowMeta}>
                    {label(dataset.kind)} · declared build{" "}
                    {label(dataset.reference_build_declared)} · {dataset.version_count}{" "}
                    {dataset.version_count === 1 ? "version" : "versions"}
                  </span>
                  <span className={styles.badges}>
                    <span className={styles.badge}>{label(dataset.state)}</span>
                    {dataset.current_version_id ? (
                      <span className={styles.badge}>has current input</span>
                    ) : (
                      <span className={styles.badge}>no accepted version</span>
                    )}
                  </span>
                </div>
                <div className={styles.rowActions}>
                  <Link href={`/datasets/${dataset.id}`}>Open</Link>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            title="No datasets in this workspace"
            description="Nothing is hidden here: this workspace contains no dataset you may read."
          />
        )}
      </Card>

      <Card
        title="Create a dataset"
        description="Creating a dataset only declares a container. Files are uploaded into a version, verified, and accepted separately."
      >
        <form className={formStyles.form} onSubmit={create} noValidate>
          <Field
            id="dataset-name"
            label="Name"
            value={name}
            minLength={2}
            maxLength={200}
            required
            onChange={(event) => setName(event.target.value)}
          />
          <div className={formStyles.field}>
            <label className={formStyles.label} htmlFor="dataset-kind">
              Kind
            </label>
            <select
              id="dataset-kind"
              className={styles.select}
              value={kind}
              onChange={(event) => setKind(event.target.value)}
            >
              {DATASET_KINDS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
          <div className={formStyles.field}>
            <label className={formStyles.label} htmlFor="dataset-build">
              Declared reference build
            </label>
            <select
              id="dataset-build"
              className={styles.select}
              value={build}
              onChange={(event) => setBuild(event.target.value)}
            >
              {REFERENCE_BUILDS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <p className={formStyles.hint}>
              A declaration by the submitter. The platform records it and never treats it as a
              verified fact.
            </p>
          </div>
          <Button type="submit" variant="primary" isBusy={isBusy}>
            Create dataset
          </Button>
        </form>
      </Card>
    </>
  );
}
