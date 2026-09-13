"use client";

/**
 * Projects surface for the active workspace.
 *
 * The workspace comes from the workspace context, which is itself populated from
 * the backend. Creation is attempted against the backend and refused there when
 * the caller may not create a project in that workspace — the form is never a
 * permission decision.
 */

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, DefinitionList } from "@/components/ui/card";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useToasts } from "@/components/ui/toast";
import { Field, authStyles as formStyles } from "@/components/auth/field";
import { useApiResource } from "@/hooks/use-api-resource";
import { useWorkspace } from "@/context/workspace-context";
import { ApiClient, ApiError } from "@/lib/api-client";

export function ProjectsView() {
  const client = useMemo(() => new ApiClient(), []);
  const { activeWorkspace, resolution } = useWorkspace();
  const { publish } = useToasts();
  const workspaceId = activeWorkspace?.id ?? null;

  const projects = useApiResource(
    () =>
      workspaceId
        ? client.projects({ workspace_id: workspaceId })
        : Promise.resolve({ items: [], page: { number: 1, size: 0, total: 0 } }),
    [client, workspaceId],
  );

  const [name, setName] = useState("");
  const [isBusy, setBusy] = useState(false);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!workspaceId) return;
    setBusy(true);
    try {
      await client.createProject({ workspace_id: workspaceId, name });
      publish({ tone: "success", title: "Project created" });
      setName("");
      projects.reload();
    } catch (cause) {
      const error = cause instanceof ApiError ? cause : null;
      publish({
        tone: "danger",
        title: "The project was not created",
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
          <ErrorState description="Workspaces could not be loaded, so no project list can be shown." />
        ) : (
          <LoadingState label="Resolving your workspace" />
        )}
      </Card>
    );
  }

  return (
    <>
      <Card
        title={`Projects in ${activeWorkspace.name}`}
        description={
          activeWorkspace.kind === "personal"
            ? "Personal workspace. Its resources are private by default."
            : "Organization workspace. Collaboration follows explicit project membership."
        }
      >
        {projects.status === "loading" ? (
          <LoadingState label="Loading projects" />
        ) : projects.status === "error" ? (
          <ErrorState
            description={projects.error ?? undefined}
            correlationId={projects.correlationId ?? undefined}
            action={
              projects.isForbidden ? undefined : <Button onClick={projects.reload}>Try again</Button>
            }
          />
        ) : projects.data && projects.data.items.length > 0 ? (
          <ul>
            {projects.data.items.map((project) => (
              <li key={project.id}>
                <DefinitionList
                  items={[
                    { term: "Name", value: project.name },
                    { term: "State", value: project.state.replace(/_/g, " ") },
                    { term: "Your role", value: project.role ?? "none" },
                    {
                      term: "Created",
                      value: new Date(project.created_at).toLocaleDateString(),
                    },
                  ]}
                />
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            title="No projects in this workspace"
            description="Nothing is hidden here: this workspace contains no project you may read."
          />
        )}
      </Card>

      <Card title="Create a project">
        <form className={formStyles.form} onSubmit={create} noValidate>
          <Field
            id="project-name"
            label="Project name"
            required
            value={name}
            onChange={(event) => setName(event.target.value)}
          />
          <div className={formStyles.actions}>
            <Button type="submit" variant="primary" isBusy={isBusy}>
              Create project
            </Button>
          </div>
        </form>
      </Card>
    </>
  );
}
