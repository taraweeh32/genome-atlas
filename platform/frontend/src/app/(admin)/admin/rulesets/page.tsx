import type { Metadata } from "next";
import { PageHeader } from "@/components/shell/app-shell";
import { RulesetGovernanceView } from "./ruleset-governance-view";

export const metadata: Metadata = { title: "Interpretation ruleset governance" };

/**
 * Administration of the interpretation control plane: which ruleset versions are
 * registered, which of them may be used for an evaluation, what criteria and
 * combination rules each declares, and how its controlled benchmark cases behaved.
 * Every read and every action is authorized by the backend.
 */
export default function RulesetGovernancePage() {
  return (
    <>
      <PageHeader
        title="Interpretation ruleset governance"
        description="Registered ruleset versions, their criteria and declared combination rules, their lifecycle state, and the outcome of their controlled benchmark runs."
      />
      <RulesetGovernanceView />
    </>
  );
}
