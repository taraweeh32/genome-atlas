/**
 * Transport types for interpretations, human review and adjudication.
 *
 * The distinctions the backend keeps are kept here too, because collapsing them
 * in the UI would misrepresent the record:
 *
 * - `suggested_classification` is what the rules engine proposed. It is never
 *   shown as the decision, and the browser never derives it.
 * - `decision_role` says whose decision a version is: an automated suggestion, a
 *   reviewer decision, an adjudicated decision or the final interpretation.
 * - Decisions are append-only. A rejected or overruled reviewer position stays in
 *   the history and is displayed, never filtered away.
 * - `finalized_at` means closed. A correction is a new interpretation, which is
 *   why the UI offers reclassification rather than editing.
 */

import type { PageMeta } from "./identity-types";
import type { EntityId } from "./types";

export interface InterpretationResponse {
  readonly id: EntityId;
  readonly workspace_id: EntityId;
  readonly project_id: EntityId;
  readonly variant_id: EntityId;
  readonly sample_id: EntityId | null;
  readonly condition_identifier: string | null;
  readonly condition_term: string | null;
  readonly state: string;
  readonly review_state: string;
  readonly current_version_id: EntityId | null;
  readonly current_version_number: number;
  readonly version: number;
  readonly created_by: EntityId;
  readonly created_at: string | null;
  readonly updated_at: string | null;
}

export interface InterpretationVersionResponse {
  readonly id: EntityId;
  readonly interpretation_id: EntityId;
  readonly version_number: number;
  readonly classification: string;
  readonly suggested_classification: string | null;
  readonly decision_role: string;
  readonly origin: string;
  readonly rationale: string | null;
  readonly clinical_significance_statement: string | null;
  readonly ruleset_id: EntityId | null;
  readonly ruleset_version: string | null;
  readonly classification_evaluation_id: EntityId | null;
  readonly automated_classification_id: EntityId | null;
  readonly criterion_evaluation_ids: readonly EntityId[];
  readonly evidence_item_ids: readonly EntityId[];
  readonly disagreement_summary: Record<string, unknown>;
  readonly review_round: number;
  readonly authored_by: EntityId | null;
  readonly adjudicated_by: EntityId | null;
  readonly adjudicated_at: string | null;
  readonly finalized_by: EntityId | null;
  readonly finalized_at: string | null;
  readonly supersedes_version_id: EntityId | null;
  readonly created_at: string | null;
}

export interface ReviewAssignmentResponse {
  readonly id: EntityId;
  readonly interpretation_id: EntityId;
  readonly reviewer_user_id: EntityId;
  readonly review_role: string;
  readonly state: string;
  readonly review_round: number;
  readonly assigned_by: EntityId | null;
  readonly assigned_at: string | null;
  readonly due_at: string | null;
  readonly completed_at: string | null;
}

export interface ReviewDecisionResponse {
  readonly id: EntityId;
  readonly interpretation_id: EntityId;
  readonly interpretation_version_id: EntityId;
  readonly reviewer_user_id: EntityId;
  readonly decision: string;
  readonly decision_role: string;
  readonly criterion_evaluation_id: EntityId | null;
  readonly proposed_classification: string | null;
  readonly previous_classification: string | null;
  readonly rationale: string | null;
  readonly review_round: number;
  readonly is_adjudication: boolean;
  readonly resolves_decision_id: EntityId | null;
  readonly decided_at: string;
}

export interface InterpretationDetailResponse {
  readonly interpretation: InterpretationResponse;
  readonly current_version: InterpretationVersionResponse | null;
  readonly versions: readonly InterpretationVersionResponse[];
  readonly assignments: readonly ReviewAssignmentResponse[];
  readonly decisions: readonly ReviewDecisionResponse[];
}

export interface InterpretationCollection {
  readonly items: readonly InterpretationResponse[];
  readonly page: PageMeta;
}

/** Values a reviewer may record. Adjudication is a separate authority. */
export const REVIEW_DECISIONS = [
  "accept",
  "reject",
  "modify",
  "add_criterion",
  "remove_criterion",
  "override",
  "abstain",
] as const;

/** Classification values the platform records. The browser never derives one. */
export const CLASSIFICATIONS = [
  "pathogenic",
  "likely_pathogenic",
  "uncertain_significance",
  "likely_benign",
  "benign",
] as const;
