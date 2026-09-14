/**
 * Transport types for filtering, ranking, variant queries and saved views.
 *
 * These mirror the versioned REST contract exactly, and four rules govern how
 * the UI may use them:
 *
 * - A filter is **structured data**, never text. The builder assembles
 *   `FilterGroupPayload` trees; nothing in this module carries SQL, an
 *   expression language, or anything else that could be executed.
 * - Filtering and ranking are **separate payloads**. A ranking never narrows a
 *   set and a filter never produces a score, so the two never share a type.
 * - `capabilities` is the server's answer about what the caller may do. The UI
 *   enables controls from it and never derives an equivalent locally.
 * - A count that was not computed arrives as `null` and is displayed as unknown.
 *   The UI never substitutes `0` for "not reported" or "not requested".
 *
 * A ranking score is a **prioritization score**: a transparent, declared
 * arithmetic combination of stored values. It is not a clinical conclusion and
 * this module never presents it as one.
 */

import type { PageMeta } from "./identity-types";

export type FilterLogicalOperator = "and" | "or" | "not";

export interface FilterConditionPayload {
  readonly kind: "condition";
  readonly field_id: string;
  readonly operator: string;
  readonly values: readonly unknown[];
  readonly negated?: boolean;
}

export interface FilterGroupPayload {
  readonly kind: "group";
  readonly operator: FilterLogicalOperator;
  readonly children: readonly FilterNodePayload[];
}

export type FilterNodePayload = FilterConditionPayload | FilterGroupPayload;

export interface FilterFieldResponse {
  readonly id: string;
  readonly label: string;
  readonly description: string;
  readonly data_type: string;
  readonly category: string;
  readonly origin: string;
  readonly supported_operators: readonly string[];
  readonly nullable: boolean;
  readonly missing_semantics: readonly string[];
  readonly allowed_values: readonly string[] | null;
  readonly high_cardinality: boolean;
  readonly searchable: boolean;
  readonly sortable: boolean;
  readonly filterable: boolean;
  readonly scientific_category: string | null;
  readonly requires_context: readonly string[];
  readonly version: string;
  readonly available: boolean;
}

export interface FieldDictionaryResponse {
  readonly version: string;
  readonly fields: readonly FilterFieldResponse[];
  readonly result_set_id: string | null;
  /** Null means no surface was named — not that the surface carries nothing. */
  readonly available_field_ids: readonly string[] | null;
}

export interface FieldValueResponse {
  readonly value: unknown;
  readonly count: number | null;
}

export interface FieldValuesResponse {
  readonly field_id: string;
  readonly result_set_id: string;
  readonly values: readonly FieldValueResponse[];
  readonly truncated: boolean;
  readonly field_dictionary_version: string;
}

export interface FilterValidationIssueResponse {
  readonly path: string;
  readonly message: string;
  readonly code: string | null;
  readonly field_id: string | null;
  readonly detail: Record<string, unknown> | null;
}

export interface FilterValidationResponse {
  readonly valid: boolean;
  readonly canonical: FilterGroupPayload | null;
  readonly canonical_hash: string | null;
  readonly field_dictionary_version: string;
  readonly condition_count: number;
  readonly depth: number;
  readonly field_ids: readonly string[];
  readonly issues: readonly FilterValidationIssueResponse[];
}

export interface QueryConfigurationVersionResponse {
  readonly id: string;
  readonly definition_id: string;
  readonly version_number: number;
  readonly canonical: Record<string, unknown>;
  readonly canonical_hash: string;
  readonly field_dictionary_version: string;
  readonly required_field_ids: readonly string[];
  readonly change_note: string | null;
  readonly is_referenced: boolean;
  readonly created_by: string;
  readonly created_at: string;
  readonly condition_count: number | null;
  readonly depth: number | null;
  readonly method_id: string | null;
  readonly method_version: string | null;
  readonly component_count: number | null;
}

export interface QueryConfigurationResponse {
  readonly id: string;
  readonly name: string;
  readonly description: string | null;
  readonly scope: string;
  readonly state: string;
  readonly deletion_state: string;
  readonly owner_user_id: string | null;
  readonly workspace_id: string | null;
  readonly project_id: string | null;
  readonly organization_id: string | null;
  readonly latest_version_number: number;
  readonly is_referenced: boolean;
  readonly version: number;
  readonly created_by: string;
  readonly created_at: string;
  readonly updated_at: string;
  readonly applicable_contexts: readonly string[] | null;
  readonly method_id: string | null;
  readonly capabilities: readonly string[];
  readonly latest_version: QueryConfigurationVersionResponse | null;
}

export interface QueryConfigurationCollection {
  readonly items: readonly QueryConfigurationResponse[];
  readonly page: PageMeta;
}

export interface QueryConfigurationVersionCollection {
  readonly items: readonly QueryConfigurationVersionResponse[];
}

export interface RankingMethodResponse {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly version: string;
  readonly implementation_id: string;
  readonly supported_component_kinds: readonly string[];
  readonly requires_components: boolean;
  readonly min_components: number;
  readonly max_components: number;
  readonly supported_parameters: readonly string[];
  readonly supported_contexts: readonly string[];
  readonly deterministic: boolean;
  readonly available: boolean;
  /** False for every shipped method: prioritization, not a validated claim. */
  readonly scientifically_validated: boolean;
}

export interface RankingMethodCollection {
  readonly items: readonly RankingMethodResponse[];
}

export interface RankingComponentPayload {
  readonly field_id: string;
  readonly kind: string;
  readonly weight: number;
  readonly scale_min?: number;
  readonly scale_max?: number;
  readonly category_priority?: readonly string[];
  readonly missing_behaviour?: string;
  readonly missing_floor?: number;
  readonly label?: string;
}

export interface RankingConfigurationPayload {
  readonly method_id: string;
  readonly method_version: string;
  readonly components: readonly RankingComponentPayload[];
  readonly direction?: string;
  readonly tie_breakers?: readonly string[];
  readonly parameters?: Record<string, unknown>;
}

export interface FilterSelectionPayload {
  readonly expression?: FilterGroupPayload;
  readonly filter_definition_id?: string;
  readonly filter_version_number?: number;
  readonly filter_preset_id?: string;
  readonly filter_preset_version_number?: number;
}

export interface RankingSelectionPayload {
  readonly configuration?: RankingConfigurationPayload;
  readonly ranking_definition_id?: string;
  readonly ranking_version_number?: number;
  readonly ranking_preset_id?: string;
  readonly ranking_preset_version_number?: number;
}

export interface VariantQueryRequest {
  readonly result_set_id: string;
  readonly filter?: FilterSelectionPayload;
  readonly ranking?: RankingSelectionPayload;
  readonly field_ids?: readonly string[];
  readonly page_size?: number;
  readonly cursor?: string;
  readonly sort_field_id?: string;
  readonly sort_descending?: boolean;
  readonly include_total?: boolean;
}

export interface FilterExecutionResponse {
  readonly id: string;
  readonly result_set_id: string;
  readonly effective_canonical: Record<string, unknown>;
  readonly effective_hash: string;
  readonly field_dictionary_version: string;
  readonly outcome: string;
  readonly filter_definition_id: string | null;
  readonly filter_version_number: number | null;
  readonly filter_preset_id: string | null;
  readonly filter_preset_version_number: number | null;
  readonly custom_canonical: Record<string, unknown> | null;
  readonly returned_count: number;
  readonly total_count: number | null;
  readonly page_size: number;
  readonly duration_ms: number | null;
  readonly software_version: string | null;
  readonly executed_at: string;
  readonly executed_by: string;
}

export interface RankingExecutionResponse {
  readonly id: string;
  readonly filter_execution_id: string;
  readonly method_id: string;
  readonly method_version: string;
  readonly method_implementation_id: string;
  readonly effective_canonical: Record<string, unknown>;
  readonly effective_hash: string;
  readonly direction: string;
  readonly tie_breakers: readonly string[];
  readonly outcome: string;
  readonly ranking_definition_id: string | null;
  readonly ranking_version_number: number | null;
  readonly ranking_preset_id: string | null;
  readonly ranking_preset_version_number: number | null;
  readonly scored_count: number;
  /** Rows nothing could score. A data fact, never a low priority. */
  readonly unscored_count: number;
  readonly duration_ms: number | null;
  readonly executed_at: string;
}

export interface VariantQueryResponse {
  readonly result_set_id: string;
  readonly columns: readonly string[];
  readonly field_ids: readonly string[];
  readonly rows: readonly Record<string, unknown>[];
  readonly returned_count: number;
  readonly total_count: number | null;
  readonly next_cursor: string | null;
  readonly execution: FilterExecutionResponse;
  readonly ranking_execution: RankingExecutionResponse | null;
  readonly ranking_window_exceeded: boolean;
  readonly ranking_window_rows: number | null;
}

export interface DeferredQueryResponse {
  readonly job_id: string;
  readonly result_set_id: string;
  readonly effective_hash: string;
  readonly field_dictionary_version: string;
  readonly max_rows: number;
}

export interface SavedViewResponse {
  readonly id: string;
  readonly name: string;
  readonly description: string | null;
  readonly scope: string;
  readonly owner_user_id: string;
  readonly workspace_id: string | null;
  readonly project_id: string | null;
  readonly organization_id: string | null;
  readonly columns: readonly string[];
  readonly pinned_columns: readonly string[];
  readonly column_widths: Record<string, number>;
  readonly sort_field_id: string | null;
  readonly sort_descending: boolean;
  readonly page_size: number;
  readonly default_filter_definition_id: string | null;
  readonly default_filter_preset_id: string | null;
  readonly default_ranking_definition_id: string | null;
  readonly default_ranking_preset_id: string | null;
  readonly deletion_state: string;
  readonly version: number;
  readonly created_at: string;
  readonly updated_at: string;
  readonly capabilities: readonly string[];
}

export interface SavedViewCollection {
  readonly items: readonly SavedViewResponse[];
  readonly page: PageMeta;
}

export interface QueryLimitsResponse {
  readonly field_dictionary_version: string;
  readonly max_conditions: number;
  readonly max_depth: number;
  readonly max_values_per_condition: number;
  readonly max_value_length: number;
  readonly max_expression_bytes: number;
  readonly max_text_match_conditions: number;
  readonly max_page_size: number;
  readonly software_version: string;
}

export interface QueryConfigurationCreateRequest {
  readonly name: string;
  readonly scope: string;
  readonly content: Record<string, unknown>;
  readonly description?: string;
  readonly workspace_id?: string;
  readonly project_id?: string;
  readonly organization_id?: string;
  readonly applicable_contexts?: readonly string[];
  readonly change_note?: string;
  readonly publish?: boolean;
}

/** Which lifecycle resource a configuration call addresses. */
export type QueryConfigurationKind =
  | "filters"
  | "filter-presets"
  | "rankings"
  | "ranking-presets";
