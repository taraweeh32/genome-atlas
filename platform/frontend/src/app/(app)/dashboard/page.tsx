import type { Metadata } from "next";
import { PageHeader } from "@/components/shell/app-shell";
import { Card } from "@/components/ui/card";
import { WorkspaceContextPanel } from "./workspace-context-panel";
import { PlatformStatusPanel } from "./platform-status-panel";

export const metadata: Metadata = { title: "Dashboard" };

/**
 * Dashboard foundation.
 *
 * It shows only facts the platform can actually establish in Package 1: the
 * resolved workspace context and live backend health/readiness. No genomic
 * datasets, analyses, variants or metrics are fabricated.
 */
export default function DashboardPage() {
  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Foundation release. Workspace, project, dataset, analysis and variant modules are introduced in later packages."
      />
      <WorkspaceContextPanel />
      <PlatformStatusPanel />
      <Card
        title="Scientific compute"
        description="The scientific compute subsystem is independently deployable and is not implemented inside the normal application domain."
      >
        <p>
          The application communicates with it exclusively through a versioned integration contract:
          capability discovery, engine and reference identity, execution requests, structured
          scientific errors, artifact references and provenance metadata. No scientific algorithm
          runs in this application.
        </p>
      </Card>
    </>
  );
}
