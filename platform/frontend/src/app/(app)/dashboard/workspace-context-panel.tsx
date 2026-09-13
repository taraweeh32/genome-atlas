"use client";

import { Card, DefinitionList } from "@/components/ui/card";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { useWorkspace } from "@/context/workspace-context";

/**
 * Renders the current workspace context exactly as the context foundation holds
 * it. When the backend has not supplied an authoritative list, that is stated —
 * no placeholder organization or project is invented.
 */
export function WorkspaceContextPanel() {
  const { resolution, workspaces, activeWorkspace, activeProject, error } = useWorkspace();

  if (resolution === "error") {
    return (
      <Card title="Workspace context">
        <ErrorState
          title="Workspace context unavailable"
          description={error ?? "The workspace list could not be loaded."}
        />
      </Card>
    );
  }

  if (resolution === "loading" || resolution === "unresolved") {
    return (
      <Card title="Workspace context">
        <LoadingState label="Resolving the workspaces you may reach" />
      </Card>
    );
  }

  if (workspaces.length === 0) {
    return (
      <Card title="Workspace context">
        <EmptyState
          title="No workspace is available to you"
          description="The backend reported no reachable workspace. Nothing is assumed on your behalf."
        />
      </Card>
    );
  }

  return (
    <Card title="Workspace context">
      <DefinitionList
        items={[
          {
            term: "Active workspace",
            value: activeWorkspace
              ? `${activeWorkspace.name} (${activeWorkspace.kind})`
              : "None selected",
          },
          { term: "Available workspaces", value: String(workspaces.length) },
          { term: "Active project", value: activeProject ? activeProject.name : "None selected" },
        ]}
      />
    </Card>
  );
}
