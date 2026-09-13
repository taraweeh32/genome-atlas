import { describe, expect, it } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { useWorkspace, WorkspaceProvider } from "@/context/workspace-context";
import type { WorkspaceContextValue } from "@/context/workspace-context";

function Probe({ onReady }: { onReady: (value: WorkspaceContextValue) => void }) {
  const value = useWorkspace();
  onReady(value);
  return (
    <div>
      <span data-testid="resolution">{value.resolution}</span>
      <span data-testid="workspace">{value.activeWorkspace?.name ?? "none"}</span>
      <span data-testid="project">{value.activeProject?.name ?? "none"}</span>
      <span data-testid="error">{value.error ?? ""}</span>
    </div>
  );
}

function setup() {
  let latest!: WorkspaceContextValue;
  render(
    <WorkspaceProvider>
      <Probe onReady={(value) => (latest = value)} />
    </WorkspaceProvider>,
  );
  return () => latest;
}

describe("workspace context foundation", () => {
  it("starts unresolved with no workspace, organization or project", () => {
    setup();
    expect(screen.getByTestId("resolution").textContent).toBe("unresolved");
    expect(screen.getByTestId("workspace").textContent).toBe("none");
    expect(screen.getByTestId("project").textContent).toBe("none");
  });

  it("supports a user with only a personal workspace", () => {
    const get = setup();
    act(() => {
      get().applyResolved([{ id: "wsp_1", kind: "personal", name: "Ada Lovelace" }]);
    });
    expect(screen.getByTestId("resolution").textContent).toBe("resolved");
    expect(screen.getByTestId("workspace").textContent).toBe("Ada Lovelace");
  });

  it("supports membership of multiple organizations and prefers the personal workspace", () => {
    const get = setup();
    act(() => {
      get().applyResolved([
        { id: "wsp_org_a", kind: "organization", name: "Institute A", organizationId: "org_a" },
        { id: "wsp_personal", kind: "personal", name: "Personal" },
        { id: "wsp_org_b", kind: "organization", name: "Institute B", organizationId: "org_b" },
      ]);
    });
    expect(screen.getByTestId("workspace").textContent).toBe("Personal");

    act(() => get().selectWorkspace("wsp_org_b"));
    expect(screen.getByTestId("workspace").textContent).toBe("Institute B");
  });

  it("rejects selecting a workspace that was not granted by the backend", () => {
    const get = setup();
    act(() => {
      get().applyResolved([{ id: "wsp_1", kind: "personal", name: "Personal" }]);
    });
    act(() => get().selectWorkspace("wsp_not_mine"));
    expect(screen.getByTestId("workspace").textContent).toBe("Personal");
    expect(screen.getByTestId("error").textContent).toContain("not available");
  });

  it("rejects a project from a different workspace and clears project on workspace change", () => {
    const get = setup();
    act(() => {
      get().applyResolved([
        { id: "wsp_a", kind: "personal", name: "Personal" },
        { id: "wsp_b", kind: "organization", name: "Institute", organizationId: "org_b" },
      ]);
    });

    act(() => get().selectProject({ id: "prj_1", workspaceId: "wsp_b", name: "Foreign" }));
    expect(screen.getByTestId("project").textContent).toBe("none");
    expect(screen.getByTestId("error").textContent).toContain("different workspace");

    act(() => get().selectProject({ id: "prj_2", workspaceId: "wsp_a", name: "Cohort" }));
    expect(screen.getByTestId("project").textContent).toBe("Cohort");

    act(() => get().selectWorkspace("wsp_b"));
    expect(screen.getByTestId("project").textContent).toBe("none");
  });

  it("exposes an explicit error resolution", () => {
    const get = setup();
    act(() => get().markError("backend unreachable"));
    expect(screen.getByTestId("resolution").textContent).toBe("error");
    expect(screen.getByTestId("error").textContent).toBe("backend unreachable");
  });
});
