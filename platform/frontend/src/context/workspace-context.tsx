"use client";

/**
 * Workspace context foundation.
 *
 * Structural mechanism only. It supports:
 * - a personal workspace for every user,
 * - membership of zero, one or many organization workspaces,
 * - an optional project context inside the selected workspace.
 *
 * It hardcodes no organization and no project, and it assumes no user belongs to
 * an organization. Package 1 loads nothing: the authoritative workspace list and
 * every permission come from the backend in a later package. Until then the
 * state is explicitly `unresolved`.
 */

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import type { EntityId, ProjectRef, WorkspaceRef } from "@/lib/types";

export type WorkspaceResolution = "unresolved" | "loading" | "resolved" | "error";

export interface WorkspaceState {
  readonly resolution: WorkspaceResolution;
  /** Workspaces the backend says this identity may access. Never guessed. */
  readonly workspaces: readonly WorkspaceRef[];
  readonly activeWorkspace: WorkspaceRef | null;
  readonly activeProject: ProjectRef | null;
  readonly error: string | null;
}

export interface WorkspaceContextValue extends WorkspaceState {
  selectWorkspace(workspaceId: EntityId): void;
  selectProject(project: ProjectRef | null): void;
  /** Applied when the backend has answered with the authoritative list. */
  applyResolved(workspaces: readonly WorkspaceRef[]): void;
  markLoading(): void;
  markError(message: string): void;
}

export const INITIAL_WORKSPACE_STATE: WorkspaceState = {
  resolution: "unresolved",
  workspaces: [],
  activeWorkspace: null,
  activeProject: null,
  error: null,
};

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

export function WorkspaceProvider({
  children,
  initialState = INITIAL_WORKSPACE_STATE,
}: {
  children: ReactNode;
  initialState?: WorkspaceState;
}) {
  const [state, setState] = useState<WorkspaceState>(initialState);

  const selectWorkspace = useCallback((workspaceId: EntityId) => {
    setState((current) => {
      const match = current.workspaces.find((workspace) => workspace.id === workspaceId);
      if (!match) {
        // Selecting an unknown workspace is not silently accepted.
        return { ...current, error: "That workspace is not available to you." };
      }
      // Changing workspace always clears project context: a project belongs to
      // exactly one workspace.
      return { ...current, activeWorkspace: match, activeProject: null, error: null };
    });
  }, []);

  const selectProject = useCallback((project: ProjectRef | null) => {
    setState((current) => {
      if (project && project.workspaceId !== current.activeWorkspace?.id) {
        return { ...current, error: "That project belongs to a different workspace." };
      }
      return { ...current, activeProject: project, error: null };
    });
  }, []);

  const applyResolved = useCallback((workspaces: readonly WorkspaceRef[]) => {
    setState({
      resolution: "resolved",
      workspaces,
      // A user may legitimately have only a personal workspace, or none yet.
      activeWorkspace: workspaces.find((item) => item.kind === "personal") ?? workspaces[0] ?? null,
      activeProject: null,
      error: null,
    });
  }, []);

  const markLoading = useCallback(() => {
    setState((current) => ({ ...current, resolution: "loading", error: null }));
  }, []);

  const markError = useCallback((message: string) => {
    setState((current) => ({ ...current, resolution: "error", error: message }));
  }, []);

  const value = useMemo<WorkspaceContextValue>(
    () => ({ ...state, selectWorkspace, selectProject, applyResolved, markLoading, markError }),
    [state, selectWorkspace, selectProject, applyResolved, markLoading, markError],
  );

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace(): WorkspaceContextValue {
  const value = useContext(WorkspaceContext);
  if (!value) {
    throw new Error("useWorkspace must be used inside a WorkspaceProvider");
  }
  return value;
}
