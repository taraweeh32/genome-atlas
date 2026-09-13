import type { Metadata } from "next";
import { PageHeader } from "@/components/shell/app-shell";
import { ProjectsView } from "./projects-view";

export const metadata: Metadata = { title: "Projects" };

/**
 * Projects route.
 *
 * A project belongs to exactly one workspace. Access to a project is a separate
 * relationship from organization membership, so this page shows only what the
 * backend returns for the caller.
 */
export default function ProjectsPage() {
  return (
    <>
      <PageHeader
        title="Projects"
        description="A project belongs to exactly one workspace. Project access is granted per project, never inherited from organization membership."
      />
      <ProjectsView />
    </>
  );
}
