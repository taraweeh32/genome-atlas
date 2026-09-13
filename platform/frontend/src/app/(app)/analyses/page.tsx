import type { Metadata } from "next";
import { PageHeader } from "@/components/shell/app-shell";
import { AnalysesView } from "./analyses-view";

export const metadata: Metadata = { title: "Analyses" };

/**
 * Analyses route.
 *
 * An analysis definition, its configuration versions and its executions are
 * distinct records. Requesting a run queues durable work on the server; the
 * browser never executes an analysis and never computes a scientific result.
 */
export default function AnalysesPage() {
  return (
    <>
      <PageHeader
        title="Analyses"
        description="Definitions, versioned configurations and the executions produced from them. Every run keeps the configuration it was requested with, so history cannot be rewritten by a later edit."
      />
      <AnalysesView />
    </>
  );
}
