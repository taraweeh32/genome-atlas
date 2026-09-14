import type { Metadata } from "next";
import { PageHeader } from "@/components/shell/app-shell";
import { AnnotationGovernanceView } from "./annotation-governance-view";

export const metadata: Metadata = { title: "Annotation resource governance" };

/**
 * Administration of the annotation control plane: which annotation resource
 * versions are registered, which of them are usable, which annotation profiles
 * pin them, and which annotation fields the filtering system is offered. Every
 * read and every action is authorized by the backend.
 */
export default function AnnotationGovernancePage() {
  return (
    <>
      <PageHeader
        title="Annotation resource governance"
        description="Registered annotation resource versions, their lifecycle state, the profiles that pin them and the annotation fields offered to filtering."
      />
      <AnnotationGovernanceView />
    </>
  );
}
