import type { Metadata } from "next";
import { PageHeader } from "@/components/shell/app-shell";
import { VariantsView } from "./variants-view";

export const metadata: Metadata = { title: "Variants" };

/**
 * Variant records route.
 *
 * Variants are always reached through one authorized dataset version, never by
 * identifier alone. Everything shown was declared by the scientific subsystem:
 * the browser performs no normalization, annotation, frequency lookup or
 * classification, and never fills an unreported value.
 */
export default function VariantsPage() {
  return (
    <>
      <PageHeader
        title="Variants"
        description="Recorded variant identities and their contexts, read through a dataset version you may access. Source representations are preserved beside canonical ones."
      />
      <VariantsView />
    </>
  );
}
