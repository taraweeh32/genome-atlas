/**
 * Transport types for annotation resources, profiles, runs and result versions.
 *
 * These mirror the versioned REST contract exactly. Three rules govern their use
 * in the UI:
 *
 * - Nothing here is computed in the browser. Annotation values are produced by
 *   the scientific subsystem, stored by the backend and only displayed here.
 * - `is_usable`, `is_readable` and `is_offered` are server answers; the client
 *   renders them and never derives an equivalent locally.
 * - `is_development_payload` marks content produced by a development stub of the
 *   scientific subsystem. It must always be surfaced, never hidden.
 */

import type { PageMeta } from "./identity-types";
import type { EntityId } from "./types";

export interface AnnotationFieldSpecResponse {
  readonly field_key: string;
  readonly label: string;
  readonly value_type: string;
  readonly description: string | null;
  readonly missing_semantics: readonly string[];
  readonly allowed_values: readonly string[];
  readonly unit: string | null;
  readonly high_cardinality: boolean;
  readonly filterable: boolean;
  readonly sortable: boolean;
  readonly scientific_category: string | null;
  readonly analytical_column: string;
}

/** An annotation field as the Package 7 filtering system sees it. */
export interface AnnotationFilterFieldResponse {
  readonly id: string;
  readonly label: string;
  readonly description: string | null;
  readonly data_type: string;
  readonly category: string;
  readonly operators: readonly string[];
  readonly nullable: boolean;
  readonly missing_semantics: readonly string[];
  readonly high_cardinality: boolean;
  readonly sortable: boolean;
  readonly filterable: boolean;
  readonly scientific_category: string | null;
  readonly source_resource_key: string | null;
  readonly source_resource_version: string | null;
  readonly available: boolean;
  readonly version: string | null;
}

export interface AnnotationFieldCollection {
  readonly items: readonly AnnotationFilterFieldResponse[];
  readonly registry_version: string;
}

export interface AnnotationResourceResponse {
  readonly id: EntityId;
  readonly resource_key: string;
  readonly version: string;
  readonly display_name: string;
  readonly category: string;
  readonly state: string;
  readonly provider: string | null;
  readonly description: string | null;
  readonly genome_assembly: string | null;
  readonly reference_genome_resource_id: string | null;
  readonly release_label: string | null;
  readonly released_at: string | null;
  readonly schema_version: string | null;
  readonly checksum_algorithm: string | null;
  readonly checksum_value: string | null;
  readonly size_bytes: number | null;
  readonly is_usable: boolean;
  readonly fields: readonly AnnotationFieldSpecResponse[];
  readonly provenance: Record<string, unknown>;
  readonly licensing: Record<string, unknown>;
  readonly metadata: Record<string, unknown>;
  readonly activated_at: string | null;
  readonly deprecated_at: string | null;
  readonly retired_at: string | null;
  readonly invalidated_at: string | null;
  readonly invalidation_reason: string | null;
  readonly created_at: string;
}

export interface AnnotationResourceCollection {
  readonly items: readonly AnnotationResourceResponse[];
  readonly page: PageMeta;
}

export interface ProfileResourceBindingResponse {
  readonly resource_id: EntityId;
  readonly resource_key: string;
  readonly resource_version: string;
  readonly category: string;
  readonly role: string;
}

export interface AnnotationProfileVersionResponse {
  readonly id: EntityId;
  readonly profile_id: EntityId;
  readonly version_number: number;
  readonly capability_id: string;
  readonly capability_version: string | null;
  readonly configuration_digest: string;
  readonly engine_resource_id: string | null;
  readonly engine_version: string | null;
  readonly genome_assembly: string | null;
  readonly reference_genome_resource_id: string | null;
  readonly required_inputs: readonly string[];
  readonly output_field_keys: readonly string[];
  readonly parameters: Record<string, unknown>;
  readonly provenance_requirements: readonly string[];
  readonly schema_version: string | null;
  readonly change_note: string | null;
  readonly is_referenced: boolean;
  readonly resources: readonly ProfileResourceBindingResponse[];
  readonly created_at: string;
}

export interface AnnotationProfileResponse {
  readonly id: EntityId;
  readonly name: string;
  readonly state: string;
  readonly description: string | null;
  readonly latest_version_number: number;
  readonly is_referenced: boolean;
  readonly is_offered: boolean;
  readonly metadata: Record<string, unknown>;
  readonly created_at: string;
  readonly versions: readonly AnnotationProfileVersionResponse[];
}

export interface AnnotationProfileCollection {
  readonly items: readonly AnnotationProfileResponse[];
  readonly page: PageMeta;
}

export interface AnnotationValidationFindingResponse {
  readonly id: EntityId;
  readonly code: string;
  readonly message: string;
  readonly severity: string;
  readonly field_key: string | null;
  readonly variant_id: string | null;
  readonly record_index: number | null;
  readonly detail: Record<string, unknown>;
}

export interface AnnotationRunResponse {
  readonly id: EntityId;
  readonly workspace_id: EntityId;
  readonly project_id: EntityId | null;
  readonly profile_id: EntityId;
  readonly profile_version_id: EntityId;
  readonly profile_version_number: number;
  readonly state: string;
  readonly result_set_id: EntityId | null;
  readonly dataset_version_id: EntityId | null;
  readonly requested_by: string | null;
  readonly requested_at: string;
  readonly submitted_at: string | null;
  readonly completed_at: string | null;
  readonly job_id: string | null;
  readonly scientific_execution_id: string | null;
  readonly external_execution_id: string | null;
  readonly capability_id: string;
  readonly capability_version: string | null;
  readonly engine_resource_id: string | null;
  readonly engine_version: string | null;
  readonly environment_version: string | null;
  readonly container_image_digest: string | null;
  readonly node_identity: string | null;
  readonly genome_assembly: string | null;
  readonly configuration_digest: string;
  readonly configuration_snapshot: Record<string, unknown>;
  readonly correlation_id: string;
  readonly failure_code: string | null;
  readonly failure_message: string | null;
  readonly record_count: number | null;
  readonly is_terminal: boolean;
  readonly findings: readonly AnnotationValidationFindingResponse[];
}

export interface AnnotationRunCollection {
  readonly items: readonly AnnotationRunResponse[];
  readonly page: PageMeta;
}

export interface AnnotationResultResponse {
  readonly id: EntityId;
  readonly annotation_run_id: EntityId;
  readonly workspace_id: EntityId;
  readonly project_id: EntityId | null;
  readonly resource_id: EntityId;
  readonly resource_key: string;
  readonly resource_version: string;
  readonly version_number: number;
  readonly state: string;
  readonly result_set_id: EntityId | null;
  readonly dataset_version_id: EntityId | null;
  readonly profile_version_id: EntityId | null;
  readonly scientific_execution_id: string | null;
  readonly engine_version: string | null;
  readonly environment_version: string | null;
  readonly container_image_digest: string | null;
  readonly node_identity: string | null;
  readonly genome_assembly: string | null;
  readonly analytical_location: string | null;
  readonly checksum_algorithm: string | null;
  readonly checksum_value: string | null;
  readonly row_count: number | null;
  readonly stored_record_count: number;
  readonly declared_record_count: number | null;
  readonly rejected_record_count: number;
  readonly field_keys: readonly string[];
  readonly contract_version: string;
  readonly payload_digest: string | null;
  readonly parameters_digest: string | null;
  readonly completeness: string;
  readonly is_development_payload: boolean;
  readonly supersedes_id: string | null;
  readonly superseded_by_id: string | null;
  readonly is_readable: boolean;
  readonly provenance: Record<string, unknown>;
  readonly ingested_at: string | null;
  readonly created_at: string;
}

export interface AnnotationResultCollection {
  readonly items: readonly AnnotationResultResponse[];
  readonly page: PageMeta;
}
