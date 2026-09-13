/**
 * Transport types for datasets, versions, artifacts, uploads, imports and
 * validation.
 *
 * These mirror the versioned REST contract exactly and carry no client-side
 * rules. Three shapes matter for how the UI must behave:
 *
 * - `capabilities` tells the UI which controls are worth rendering. It is a
 *   rendering hint produced by the server; the server re-checks every operation.
 * - `acceptance_blocked_reason` / `submission_blocked_reason` are the server's
 *   own answer to "may this proceed right now". The UI displays the reason and
 *   never computes one.
 * - `value_semantics` keeps missing, empty, NA, unknown, not-applicable, zero
 *   and false distinct. The UI must render them distinctly too, and must never
 *   display an absent value as 0 or false.
 *
 * No storage key is ever part of a response: bytes move only through a
 * short-lived, explicitly authorized transfer or download grant.
 */

import type { EntityId, PageMeta } from "./identity-types";

export interface DatasetResponse {
  readonly id: EntityId;
  readonly workspace_id: EntityId;
  readonly project_id: EntityId | null;
  readonly name: string;
  readonly kind: string;
  readonly state: string;
  readonly description: string | null;
  readonly created_by: EntityId;
  readonly owner_user_id: EntityId | null;
  readonly reference_build_declared: string;
  readonly current_version_id: EntityId | null;
  readonly deletion_state: string;
  readonly retention_expires_at: string | null;
  readonly version_count: number;
  readonly capabilities: readonly string[];
  readonly created_at: string | null;
  readonly version: number;
}

export interface DatasetCollection {
  readonly items: readonly DatasetResponse[];
  readonly page: PageMeta;
}

export interface FileArtifactResponse {
  readonly id: EntityId;
  readonly filename: string;
  readonly original_filename: string | null;
  readonly size_bytes: number | null;
  readonly content_type: string | null;
  readonly upload_state: string;
  readonly validation_state: string;
  readonly scan_state: string;
  readonly scan_detail: string | null;
  readonly declared_format: string;
  readonly detected_format: string;
  readonly compression: string;
  readonly checksum_algorithm: string;
  readonly checksum_value: string | null;
  readonly is_retrievable: boolean;
  readonly quarantined_at: string | null;
  readonly uploaded_at: string | null;
}

export interface ValidationRunSummary {
  readonly id: EntityId;
  readonly state: string;
  readonly validator_name: string;
  readonly validator_version: string;
  readonly blocking_issue_count: number;
  readonly error_issue_count: number;
  readonly warning_issue_count: number;
  readonly info_issue_count: number;
  readonly started_at: string | null;
  readonly completed_at: string | null;
  readonly summary: Record<string, unknown>;
}

export interface DatasetVersionResponse {
  readonly id: EntityId;
  readonly dataset_id: EntityId;
  readonly version_number: number;
  readonly state: string;
  readonly created_by: EntityId;
  readonly declared_format: string;
  readonly detected_format: string;
  readonly compression: string;
  readonly reference_build_declared: string;
  readonly checksum_algorithm: string;
  readonly checksum_value: string | null;
  readonly source_representation: Record<string, unknown>;
  readonly validated_at: string | null;
  readonly accepted_at: string | null;
  readonly accepted_by: EntityId | null;
  readonly rejected_at: string | null;
  readonly rejection_reason: string | null;
  readonly superseded_by_version_id: EntityId | null;
  readonly artifacts: readonly FileArtifactResponse[];
  readonly latest_validation: ValidationRunSummary | null;
  /** Server-derived: non-null means acceptance is refused, with the reason. */
  readonly acceptance_blocked_reason: string | null;
  readonly created_at: string | null;
}

export interface DatasetVersionCollection {
  readonly items: readonly DatasetVersionResponse[];
  readonly page: PageMeta;
}

export interface UploadSessionResponse {
  readonly id: EntityId;
  readonly state: string;
  readonly dataset_id: EntityId;
  readonly dataset_version_id: EntityId;
  readonly file_artifact_id: EntityId;
  readonly declared_filename: string;
  readonly declared_size_bytes: number;
  readonly declared_format: string;
  readonly expires_at: string | null;
  readonly completed_at: string | null;
  readonly failure_reason: string | null;
  readonly duplicate_relation: string;
  readonly duplicate_of_file_artifact_id: EntityId | null;
  readonly artifact: FileArtifactResponse;
  readonly latest_validation: ValidationRunSummary | null;
}

export interface UploadTicketResponse {
  readonly session: UploadSessionResponse;
  /** Short-lived transfer grant. Holding it does not make the artifact usable. */
  readonly upload_url: string;
  readonly expires_at: string;
}

export interface DownloadGrantResponse {
  readonly file_artifact_id: EntityId;
  readonly filename: string;
  readonly download_url: string;
  readonly expires_in_seconds: number;
}

export interface ColumnMappingResponse {
  readonly id: EntityId;
  readonly source_column_name: string;
  readonly source_column_index: number;
  readonly status: string;
  /** `human_confirmed` vs `system_suggested`: never conflated in the UI. */
  readonly origin: string;
  readonly target_concept: string;
  readonly declared_unit: string | null;
  readonly sample_value_semantics: string;
  readonly notes: string | null;
}

export interface ImportSessionResponse {
  readonly id: EntityId;
  readonly state: string;
  readonly dataset_id: EntityId | null;
  readonly dataset_version_id: EntityId | null;
  readonly file_artifact_id: EntityId | null;
  readonly declared_format: string;
  readonly detected_format: string;
  readonly reference_build_declared: string;
  readonly importer_version: string | null;
  readonly mapping_confirmed_at: string | null;
  readonly submitted_at: string | null;
  readonly decided_at: string | null;
  readonly rejection_reason: string | null;
  readonly import_provenance: Record<string, unknown>;
  readonly mappings: readonly ColumnMappingResponse[];
  readonly latest_validation: ValidationRunSummary | null;
  /** Server-derived: non-null means submission is refused, with the reason. */
  readonly submission_blocked_reason: string | null;
  readonly created_at: string | null;
  readonly version: number;
}

export interface ImportSessionSummary {
  readonly id: EntityId;
  readonly state: string;
  readonly dataset_version_id: EntityId | null;
  readonly file_artifact_id: EntityId | null;
  readonly detected_format: string;
  readonly mapping_confirmed_at: string | null;
  readonly submitted_at: string | null;
  readonly decided_at: string | null;
  readonly rejection_reason: string | null;
  readonly created_at: string | null;
}

export interface ImportSessionCollection {
  readonly items: readonly ImportSessionSummary[];
  readonly page: PageMeta;
}

export interface ValidationIssueResponse {
  readonly id: EntityId;
  readonly severity: string;
  readonly category: string;
  readonly code: string;
  readonly message: string;
  readonly validation_rule_id: string | null;
  readonly locator: Record<string, unknown>;
  readonly value_semantics: string;
  readonly observed_value: string | null;
  readonly details: Record<string, unknown>;
}

export interface ValidationRunResponse {
  readonly run: ValidationRunSummary;
  readonly subject: Record<string, string | null>;
  readonly issues: readonly ValidationIssueResponse[];
  readonly issue_total: number;
}

export interface ValidationRunCollection {
  readonly items: readonly ValidationRunSummary[];
  readonly page: PageMeta;
}

export interface ColumnMappingDecision {
  readonly source_column_index: number;
  readonly source_column_name: string;
  readonly target_concept: string;
  readonly declared_unit?: string | null;
  readonly notes?: string | null;
}
