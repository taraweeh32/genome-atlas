import type { Metadata } from "next";
import { PageHeader } from "@/components/shell/app-shell";
import { DatasetsView } from "./datasets-view";

export const metadata: Metadata = { title: "Datasets" };

/**
 * Datasets route.
 *
 * A dataset lives in exactly one scope — a workspace or a project inside it —
 * and every operation is authorized against that scope on the server. This page
 * shows only what the backend returns for the caller.
 */
export default function DatasetsPage() {
  return (
    <>
      <PageHeader
        title="Datasets"
        description="Scientific inputs. Each version is immutable once accepted, and a version becomes the dataset's current input only through an explicit human decision."
      />
      <DatasetsView />
    </>
  );
}
