"use client";

/**
 * Workspace switcher.
 *
 * Reflects whatever the workspace context holds. It hardcodes no organization,
 * does not assume the user belongs to one, and shows an explicit unresolved
 * state until the backend supplies the authoritative list.
 */

import { useWorkspace } from "@/context/workspace-context";
import styles from "./workspace-switcher.module.css";

export function WorkspaceSwitcher() {
  const { resolution, workspaces, activeWorkspace, activeProject, selectWorkspace } =
    useWorkspace();

  if (resolution !== "resolved" || workspaces.length === 0) {
    return (
      <p className={styles.placeholder} data-testid="workspace-unresolved">
        {resolution === "error"
          ? "Workspaces unavailable"
          : resolution === "loading"
            ? "Loading workspaces…"
            : "No workspace context"}
      </p>
    );
  }

  return (
    <div className={styles.switcher}>
      <label className="visually-hidden" htmlFor="workspace-select">
        Active workspace
      </label>
      <select
        id="workspace-select"
        className={styles.select}
        value={activeWorkspace?.id ?? ""}
        onChange={(event) => selectWorkspace(event.target.value)}
      >
        {workspaces.map((workspace) => (
          <option key={workspace.id} value={workspace.id}>
            {workspace.kind === "personal"
              ? `${workspace.name} (personal)`
              : `${workspace.name} (organization)`}
          </option>
        ))}
      </select>
      {activeProject ? (
        <span className={styles.project} aria-label="Active project">
          {activeProject.name}
        </span>
      ) : null}
    </div>
  );
}
