import type { Metadata } from "next";
import { PageHeader } from "@/components/shell/app-shell";
import { QueryLibraryView } from "./library-view";

export const metadata: Metadata = { title: "Query library" };

/**
 * Saved filters, filter presets, saved prioritizations and prioritization
 * presets, with their versions and lifecycle.
 *
 * Definitions are versioned rather than edited in place, so an analysis that
 * referenced a version keeps that version verbatim no matter what is published
 * later.
 */
export default function QueryLibraryPage() {
  return (
    <>
      <PageHeader
        title="Query library"
        description="Saved filters, presets and prioritization configurations. Changing content issues a new version; a version an execution referenced never changes."
      />
      <QueryLibraryView />
    </>
  );
}
