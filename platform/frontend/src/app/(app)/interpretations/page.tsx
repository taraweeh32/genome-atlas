import type { Metadata } from "next";
import { PageHeader } from "@/components/shell/app-shell";
import { InterpretationReviewView } from "./interpretation-review-view";

export const metadata: Metadata = { title: "Interpretation review" };

/**
 * Interpretation, human review and adjudication route.
 *
 * The browser records what people decided; it never evaluates a criterion,
 * combines criteria or derives a classification. Every action here is authorized
 * and applied by the backend, which keeps the automated suggestion, each reviewer
 * decision, the adjudicated decision and the final interpretation apart.
 */
export default function InterpretationsPage() {
  return (
    <>
      <PageHeader
        title="Interpretation review"
        description="Decision records for variants you may access: what the rules engine suggested, what each reviewer decided, how disagreement was adjudicated, and what was finalized. Finalized records are closed — a correction opens a successor."
      />
      <InterpretationReviewView />
    </>
  );
}
