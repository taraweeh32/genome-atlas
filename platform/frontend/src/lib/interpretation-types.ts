/**
 * Transport types for interpretation rulesets and automated classification.
 *
 * Three rules govern their use in the UI:
 *
 * - No criterion is evaluated and no classification is combined in the browser.
 *   The rules engine decides behind the scientific boundary; the client displays
 *   what it returned.
 * - `decision_role` is always shown. An automated classification is a suggestion,
 *   never a reviewer decision and never a final clinical conclusion.
 * - A superseded suggestion stays visible. Hiding it would hide that the automated
 *   answer changed.
 */

import type { PageMeta } from "./identity-types";
import type { EntityId } from "./types";

export interface CriterionDefinitionResponse {
  readonly criterion_key: string;
  readonly family: string;
  readonly direction: string;
  readonly default_strength: string;
  readonly description: string | null;
  readonly permitted_strengths: readonly string[];
  readonly evidence_categories: readonly string[];
  readonly requires_evidence: boolean;
  readonly display_order: number | null;
}

export interface CombinationRuleResponse {
  readonly rule_key: string;
  readonly classification: string;
  readonly description: string | null;
  readonly requirements: Record<string, unknown>;
  readonly precedence: number | null;
}

export interface RulesetResponse {
  readonly id: EntityId;
  readonly ruleset_key: string;
  readonly version: string;
  readonly display_name: string;
  readonly guideline_source: string;
  readonly state: string;
  readonly description: string | null;
  readonly guideline_citation: string | null;
  readonly publication_reference: string | null;
  readonly publication_year: number | null;
  readonly specification_scope: string;
  readonly gene_symbol: string | null;
  readonly condition_identifier: string | null;
  readonly condition_term: string | null;
  readonly combination_strategy: string;
  readonly effective_from: string | null;
  readonly effective_to: string | null;
  readonly capability_id: string | null;
  readonly capability_version: string | null;
  readonly engine_resource_id: string | null;
  readonly genome_assembly: string | null;
  readonly configuration_digest: string | null;
  readonly criteria: readonly CriterionDefinitionResponse[];
  readonly combination_rules: readonly CombinationRuleResponse[];
  readonly is_usable: boolean;
  readonly activated_at: string | null;
  readonly deprecated_at: string | null;
  readonly retired_at: string | null;
  readonly invalidated_at: string | null;
  readonly invalidation_reason: string | null;
  readonly created_at: string | null;
}

export interface RulesetCollection {
  readonly items: readonly RulesetResponse[];
  readonly page: PageMeta;
}

export interface CriterionEvaluationResponse {
  readonly id: EntityId;
  readonly criterion_key: string;
  readonly family: string | null;
  readonly applied: boolean;
  readonly strength: string;
  readonly direction: string;
  readonly origin: string;
  readonly rationale: string | null;
  readonly evidence_ids: readonly string[];
  readonly evaluation_method: string | null;
  readonly is_override: boolean;
  readonly evaluated_at: string | null;
}

export interface AutomatedClassificationResponse {
  readonly id: EntityId;
  readonly evaluation_id: EntityId;
  readonly variant_id: EntityId;
  readonly ruleset_id: EntityId;
  readonly ruleset_key: string;
  readonly ruleset_version: string;
  readonly classification: string;
  readonly decision_role: string;
  readonly version_number: number;
  readonly combination_rule_key: string | null;
  readonly rationale: string | null;
  readonly applied_criterion_keys: readonly string[];
  readonly evidence_ids: readonly string[];
  readonly engine_version: string | null;
  readonly environment_version: string | null;
  readonly node_identity: string | null;
  readonly scientific_execution_id: string | null;
  readonly contract_version: string | null;
  readonly input_digest: string | null;
  readonly configuration_digest: string | null;
  readonly payload_digest: string | null;
  readonly supersedes_id: string | null;
  readonly superseded_by_id: string | null;
  readonly is_current: boolean;
  readonly is_development_payload: boolean;
  readonly produced_at: string | null;
  readonly created_at: string | null;
}

export interface ClassificationEvaluationResponse {
  readonly id: EntityId;
  readonly workspace_id: EntityId;
  readonly project_id: EntityId | null;
  readonly variant_id: EntityId;
  readonly ruleset_id: EntityId;
  readonly ruleset_key: string;
  readonly ruleset_version: string;
  readonly state: string;
  readonly gene_symbol: string | null;
  readonly transcript_identifier: string | null;
  readonly condition_identifier: string | null;
  readonly condition_term: string | null;
  readonly inheritance: string | null;
  readonly genome_assembly: string | null;
  readonly evidence_ids: readonly string[];
  readonly input_digest: string | null;
  readonly configuration_digest: string | null;
  readonly capability_id: string | null;
  readonly engine_version: string | null;
  readonly node_identity: string | null;
  readonly scientific_execution_id: string | null;
  readonly job_id: string | null;
  readonly classification_id: string | null;
  readonly failure_code: string | null;
  readonly failure_message: string | null;
  readonly requested_at: string | null;
  readonly submitted_at: string | null;
  readonly completed_at: string | null;
}

export interface ClassificationEvaluationCollection {
  readonly items: readonly ClassificationEvaluationResponse[];
  readonly page: PageMeta;
}

export interface ClassificationEvaluationDetailResponse {
  readonly evaluation: ClassificationEvaluationResponse;
  readonly classification: AutomatedClassificationResponse | null;
  readonly criteria: readonly CriterionEvaluationResponse[];
}

export interface ClassificationHistoryResponse {
  readonly items: readonly AutomatedClassificationResponse[];
}

export interface BenchmarkCaseResponse {
  readonly id: EntityId;
  readonly ruleset_id: EntityId;
  readonly case_key: string;
  readonly validation_kind: string;
  readonly expected_classification: string | null;
  readonly expected_criteria: Record<string, unknown>;
  readonly description: string | null;
  readonly source_reference: string | null;
  readonly is_active: boolean;
  readonly created_at: string | null;
}

export interface BenchmarkCaseCollection {
  readonly items: readonly BenchmarkCaseResponse[];
}

export interface BenchmarkComparisonResponse {
  readonly case_id: EntityId;
  readonly case_key: string;
  readonly outcome: string;
  readonly validation_kind: string;
  readonly expected_classification: string | null;
  readonly observed_classification: string | null;
  readonly criterion_differences: readonly Record<string, unknown>[];
  readonly severity: string;
  readonly detail: string | null;
}

export interface BenchmarkRunResponse {
  readonly id: EntityId;
  readonly ruleset_id: EntityId;
  readonly ruleset_key: string;
  readonly ruleset_version: string;
  readonly validation_kind: string;
  readonly case_count: number;
  readonly matched_count: number;
  readonly mismatched_count: number;
  readonly not_evaluated_count: number;
  readonly is_accuracy_run: boolean;
  readonly comparisons: readonly BenchmarkComparisonResponse[];
  readonly executed_at: string | null;
}

export interface BenchmarkRunCollection {
  readonly items: readonly BenchmarkRunResponse[];
  readonly page: PageMeta;
}
