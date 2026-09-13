import type { Metadata } from "next";
import { PageHeader } from "@/components/shell/app-shell";
import { ResultsView } from "./results-view";

export const metadata: Metadata = { title: "Results" };

/**
 * Result sets route.
 *
 * A result set is the readable surface an execution produced. Its content is
 * immutable: withdrawing or superseding one changes its lifecycle state, never
 * the scientific content it recorded. The browser reads bounded windows only and
 * computes nothing scientific.
 */
export default function ResultsPage() {
  return (
    <>
      <PageHeader
        title="Results"
        description="Surfaces produced by analysis executions, each carrying the provenance it was produced with. Content is immutable; only readability and lifecycle state change."
      />
      <ResultsView />
    </>
  );
}
