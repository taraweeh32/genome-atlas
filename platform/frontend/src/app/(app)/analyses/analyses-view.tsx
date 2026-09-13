"use client";

/**
 * Analysis list for the active workspace, plus definition creation.
 *
 * The list is exactly what the backend returns for the caller: an analysis the
 * caller may not read is absent, not hidden client-side. `capabilities` and
 * `is_executable` are server answers that decide which controls render; every
 * control is still re-authorized on the server when used.
 *
 * Creating a definition only records intent. It selects no compute node, queues
 * no work and performs no scientific computation.
 */

import Link from "next/link";
import { useMemo, useState } from "react";
import { Field, authStyles as formStyles } from "@/components/auth/field";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useToasts } from "@/components/ui/toast";
import { useWorkspace } from "@/context/workspace-context";
import { useApiResource } from "@/hooks/use-api-resource";
import { ApiClient, ApiError } from "@/lib/api-client";
import styles from "./analyses.module.css";

/** Analysis kinds the backend accepts. Values mirror the API contract exactly. */
const ANALYSIS_KINDS: readonly { value: string; label: string }[] = [
  { value: "variant_prioritization", label: "Variant prioritization" },
  { value: "annotation", label: "Annotation" },
  { value: "filtering", label: "Filtering" },
  { value: "ranking", label: "Ranking" },
  { value: "interpretation", label: "Interpretation" },
  { value: "quality_control", label: "Quality control" },
  { value: "genomic_analysis", label: "Genomic analysis" },
  { value: "annotated_data_analysis", label: "Annotated data analysis" },
  { value: "custom", label: "Custom" },
];

export function label(value: string): string {
  return value.replace(/_/g, " ");
}

export function AnalysesView() {
  const client = useMemo(() => new ApiClient(), []);
  const { activeWorkspace, resolution } = useWorkspace();
  const { publish } = useToasts();
  const workspaceId = activeWorkspace?.id ?? null;

  const analyses = useApiResource(
    () =>
      workspaceId
        ? client.analyses({ workspace_id: workspaceId })
        : Promise.resolve({ items: [], page: { number: 1, size: 0, total: 0 } }),
    [client, workspaceId],
  );

  const projects = useApiResource(
    () =>
      workspaceId
        ? client.projects({ workspace_id: workspaceId })
        : Promise.resolve({ items: [], page: { number: 1, size: 0, total: 0 } }),
    [client, workspaceId],
  );

  const [name, setName] = useState("");
  const [kind, setKind] = useState("variant_prioritization");
  const [projectId, setProjectId] = useState("");
  const [capabilityKey, setCapabilityKey] = useState("");
  const [isBusy, setBusy] = useState(false);

  const projectOptions = projects.data?.items ?? [];
  const selectedProject = projectId || projectOptions[0]?.id || "";

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!selectedProject) return;
    setBusy(true);
    try {
      await client.createAnalysis({
        project_id: selectedProject,
        name,
        kind,
        capability_key: capabilityKey.trim() === "" ? null : capabilityKey.trim(),
      });
      publish({ tone: "success", title: "Analysis definition created" });
      setName("");
      setCapabilityKey("");
      analyses.reload();
    } catch (cause) {
      const error = cause instanceof ApiError ? cause : null;
      publish({
        tone: "danger",
        title: "The analysis was not created",
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
          <ErrorState description="Workspaces could not be loaded, so no analysis list can be shown." />
        ) : (
          <LoadingState label="Resolving your workspace" />
        )}
      </Card>
    );
  }

  return (
    <>
      <Card
        title={`Analyses in ${activeWorkspace.name}`}
        description="An analysis definition is reusable. Its configuration versions and its executions are separate records, so a past run keeps the exact context it ran with."
        actions={<Button onClick={analyses.reload}>Refresh</Button>}
      >
        {analyses.status === "loading" ? (
          <LoadingState label="Loading analyses" />
        ) : analyses.status === "error" ? (
          <ErrorState
            description={analyses.error ?? undefined}
            correlationId={analyses.correlationId ?? undefined}
            action={
              analyses.isForbidden ? undefined : <Button onClick={analyses.reload}>Try again</Button>
            }
          />
        ) : analyses.data && analyses.data.items.length > 0 ? (
          <div className={styles.scroll}>
            <table className={styles.table}>
              <caption className="visually-hidden">
                Analyses readable by you in this workspace
              </caption>
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Kind</th>
                  <th scope="col">State</th>
                  <th scope="col">Executable</th>
                  <th scope="col" className={styles.numeric}>
                    Versions
                  </th>
                  <th scope="col" className={styles.numeric}>
                    Active runs
                  </th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {analyses.data.items.map((analysis) => (
                  <tr key={analysis.id}>
                    <td className={styles.wide}>{analysis.name}</td>
                    <td>{label(analysis.kind)}</td>
                    <td>
                      <span className={styles.badge}>{label(analysis.state)}</span>
                    </td>
                    <td>
                      {analysis.is_executable ? (
                        <span className={styles.badge}>ready to run</span>
                      ) : (
                        <span className={styles.muted}>not runnable yet</span>
                      )}
                    </td>
                    <td className={styles.numeric}>{analysis.configuration_count}</td>
                    <td className={styles.numeric}>{analysis.active_execution_count}</td>
                    <td>
                      <Link href={`/analyses/${analysis.id}`}>Open</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="No analyses in this workspace"
            description="Nothing is hidden here: this workspace contains no analysis you may read."
          />
        )}
      </Card>

      <Card
        title="Define an analysis"
        description="This records a definition inside one project. Inputs, parameters and scientific resources are declared afterwards, as a configuration version."
      >
        {projectOptions.length === 0 ? (
          <EmptyState
            title="No project available"
            description="An analysis belongs to exactly one project. Create a project you may write to first."
          />
        ) : (
          <form className={formStyles.form} onSubmit={create} noValidate>
            <Field
              id="analysis-name"
              label="Name"
              value={name}
              minLength={2}
              maxLength={200}
              required
              onChange={(event) => setName(event.target.value)}
            />
            <div className={formStyles.field}>
              <label className={formStyles.label} htmlFor="analysis-project">
                Project
              </label>
              <select
                id="analysis-project"
                className={formStyles.input}
                value={selectedProject}
                onChange={(event) => setProjectId(event.target.value)}
              >
                {projectOptions.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </div>
            <div className={formStyles.field}>
              <label className={formStyles.label} htmlFor="analysis-kind">
                Kind
              </label>
              <select
                id="analysis-kind"
                className={formStyles.input}
                value={kind}
                onChange={(event) => setKind(event.target.value)}
              >
                {ANALYSIS_KINDS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
            <Field
              id="analysis-capability"
              label="Requested scientific capability (optional)"
              value={capabilityKey}
              maxLength={128}
              onChange={(event) => setCapabilityKey(event.target.value)}
              hint="A capability declared by the scientific subsystem. The platform forwards the request and never performs the computation itself."
            />
            <Button type="submit" variant="primary" isBusy={isBusy}>
              Create definition
            </Button>
          </form>
        )}
      </Card>
    </>
  );
}
