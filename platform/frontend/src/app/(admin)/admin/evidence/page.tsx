import type { Metadata } from "next";
import { PageHeader } from "@/components/shell/app-shell";
import { EvidenceGovernanceView } from "./evidence-governance-view";

export const metadata: Metadata = { title: "Evidence source governance" };

/**
 * Administration of the evidence control plane: which evidence source versions
 * are registered, which of them may supply evidence, what each one is allowed to
 * state, and how recent deliveries were validated. Every read and every action is
 * authorized by the backend.
 */
export default function EvidenceGovernancePage() {
  return (
    <>
      <PageHeader
        title="Evidence source governance"
        description="Registered evidence source versions, their lifecycle state, what each source is declared to supply, and the validation outcome of recent deliveries."
      />
      <EvidenceGovernanceView />
    </>
  );
}
