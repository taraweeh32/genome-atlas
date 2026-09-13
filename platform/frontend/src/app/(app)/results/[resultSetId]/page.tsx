import type { Metadata } from "next";
import { PageHeader } from "@/components/shell/app-shell";
import { ResultDetailView } from "./result-detail-view";

export const metadata: Metadata = { title: "Result set" };

/**
 * Result set detail route.
 *
 * Shows the recorded provenance, the artifacts and a bounded window of the
 * materialized surface. Downloads are short-lived grants issued by the server;
 * the browser never receives artifact bytes through the platform API.
 */
export default async function ResultSetPage({
  params,
}: {
  params: Promise<{ resultSetId: string }>;
}) {
  const { resultSetId } = await params;
  return (
    <>
      <PageHeader
        title="Result set"
        description="One readable surface, its provenance chain and its artifacts. Content is immutable; withdrawal and supersession change only how it may be used."
      />
      <ResultDetailView resultSetId={resultSetId} />
    </>
  );
}
