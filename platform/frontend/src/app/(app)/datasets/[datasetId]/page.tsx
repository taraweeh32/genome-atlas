import type { Metadata } from "next";
import { PageHeader } from "@/components/shell/app-shell";
import { DatasetDetailView } from "./dataset-detail-view";

export const metadata: Metadata = { title: "Dataset" };

/**
 * Dataset detail route.
 *
 * Knowing this identifier proves nothing: the backend resolves the dataset's own
 * workspace/project scope and refuses the request unless the caller holds the
 * permission there.
 */
export default function DatasetPage({ params }: { params: { datasetId: string } }) {
  return (
    <>
      <PageHeader
        title="Dataset"
        description="Versions, files, verification and imports. Validation is not acceptance: making a version the current input is a separate, explicit decision."
      />
      <DatasetDetailView datasetId={params.datasetId} />
    </>
  );
}
