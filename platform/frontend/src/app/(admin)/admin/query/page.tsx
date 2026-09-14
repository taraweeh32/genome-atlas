import type { Metadata } from "next";
import { PageHeader } from "@/components/shell/app-shell";
import { QueryGovernanceView } from "./query-governance-view";

export const metadata: Metadata = { title: "Filtering & ranking governance" };

/**
 * Administration of the filtering and prioritization control plane: the field
 * dictionary, the prioritization-method registry, the platform safety limits and
 * the lifecycle of shared presets. Every read and every action is authorized by
 * the backend, which refuses the request when the caller lacks the permission.
 */
export default function QueryGovernancePage() {
  return (
    <>
      <PageHeader
        title="Filtering & ranking governance"
        description="The published field dictionary, prioritization methods, query safety limits and the lifecycle of platform and organization presets."
      />
      <QueryGovernanceView />
    </>
  );
}
