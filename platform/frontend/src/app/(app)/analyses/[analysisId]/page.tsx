import type { Metadata } from "next";
import { PageHeader } from "@/components/shell/app-shell";
import { AnalysisDetailView } from "./analysis-detail-view";

export const metadata: Metadata = { title: "Analysis" };

/**
 * One analysis definition.
 *
 * Knowing the identifier grants nothing: the backend authorizes every read and
 * every requested transition against the scope recorded on the analysis itself.
 */
export default async function AnalysisPage({
  params,
}: {
  params: Promise<{ analysisId: string }>;
}) {
  const { analysisId } = await params;
  return (
    <>
      <PageHeader
        title="Analysis"
        description="Configuration versions, executions and recorded provenance. Requesting a run queues durable server-side work."
      />
      <AnalysisDetailView analysisId={analysisId} />
    </>
  );
}
