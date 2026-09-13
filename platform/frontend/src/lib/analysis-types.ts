/**
 * Transport types for analyses, configurations, executions, jobs, schedules and
 * compute nodes.
 *
 * These mirror the versioned REST contract exactly and carry no client-side
 * rules. Three shapes decide how the UI must behave:
 *
 * - `capabilities` and `can_cancel` are rendering hints produced by the server.
 *   The server re-authorizes every operation regardless of what is rendered.
 * - `is_executable` is the server's own answer to "may this run right now". The
 *   UI displays it and never computes an equivalent from other fields.
 * - Provenance fields (engine, environment, container digest, node identity,
 *   reference resources) are recorded facts about a past run. The UI presents
 *   them read-only and never fills a missing one with a plausible value.
 *
 * Nothing here interprets scientific content: artifacts are referenced, never
 * inlined, and no scientific result is computed in the browser.
 */

import type { PageMeta } from "./identity-types";
import type { EntityId } from "./types";

export interface AnalysisResponse {
  readonly id: EntityId;
  readonly workspace_id: EntityId;
  readonly project_id: EntityId;
  readonly name: string;
  readonly kind: string;
  readonly state: string;
  readonly description: string | null;
  readonly capability_key: string | null;
  readonly current_configuration_id: EntityId | null;
  readonly execution_defaults: Record<string, unknown>;
  readonly deletion_state: string;
  readonly is_executable: boolean;
  readonly configuration_count: number;
  readonly active_execution_count: number;
  readonly capabilities: readonly string[];
  readonly created_by: EntityId;
  readonly created_at: string | null;
  readonly updated_at: string | null;
}

export interface AnalysisCollection {
  readonly items: readonly AnalysisResponse[];
  readonly page: PageMeta;
}

export interface ConfigurationInputResponse {
  readonly id: EntityId;
  readonly dataset_version_id: EntityId;
  readonly role: string;
}

export interface ConfigurationResponse {
  readonly id: EntityId;
  readonly analysis_id: EntityId;
  readonly version_number: number;
  readonly label: string | null;
  readonly validation_state: string;
  readonly validation_findings: Record<string, unknown>;
  readonly content_hash: string | null;
  readonly is_current: boolean;
  readonly filtering_configuration: Record<string, unknown>;
  readonly ranking_configuration: Record<string, unknown>;
  readonly annotation_configuration: Record<string, unknown>;
  readonly evidence_configuration: Record<string, unknown>;
  readonly interpretation_configuration: Record<string, unknown>;
  readonly reporting_configuration: Record<string, unknown>;
  readonly execution_parameters: Record<string, unknown>;
  readonly pipeline_resource_id: EntityId | null;
  readonly engine_resource_id: EntityId | null;
  readonly reference_genome_resource_id: EntityId | null;
  readonly ruleset_resource_id: EntityId | null;
  readonly execution_profile_resource_id: EntityId | null;
  readonly inputs: readonly ConfigurationInputResponse[];
  readonly created_by: EntityId;
  readonly created_at: string | null;
}

export interface ConfigurationCollection {
  readonly items: readonly ConfigurationResponse[];
  readonly page: PageMeta;
}

export interface ExecutionInputResponse {
  readonly id: EntityId;
  readonly dataset_version_id: EntityId;
  readonly role: string;
}

export interface ExecutionResponse {
  readonly id: EntityId;
  readonly analysis_id: EntityId;
  readonly analysis_name: string | null;
  readonly workspace_id: EntityId;
  readonly project_id: EntityId;
  readonly analysis_configuration_id: EntityId;
  readonly attempt_sequence: number;
  readonly state: string;
  readonly queue: string;
  readonly priority: number;
  readonly capability_key: string | null;
  readonly capability_version: string | null;
  readonly schedule_id: EntityId | null;
  readonly scheduled_for: string | null;
  readonly scheduled_job_id: EntityId | null;
  readonly scientific_execution_id: EntityId | null;
  readonly compute_node_id: EntityId | null;
  readonly progress_percent: number | null;
  readonly progress_message: string | null;
  readonly requested_by: EntityId | null;
  readonly requested_at: string;
  readonly started_at: string | null;
  readonly completed_at: string | null;
  readonly correlation_id: string;
  readonly execution_environment: Record<string, unknown>;
  readonly scientific_versions: Record<string, unknown>;
  readonly resource_requirements: Record<string, unknown>;
  readonly failure_code: string | null;
  readonly failure_message: string | null;
  readonly inputs: readonly ExecutionInputResponse[];
  readonly can_cancel: boolean;
}

export interface ExecutionCollection {
  readonly items: readonly ExecutionResponse[];
  readonly page: PageMeta;
}

export interface ScientificArtifactResponse {
  readonly id: EntityId;
  readonly artifact_key: string;
  readonly artifact_kind: string;
  readonly content_type: string | null;
  readonly size_bytes: number | null;
  readonly checksum_algorithm: string | null;
  readonly checksum_value: string | null;
}

export interface ScientificExecutionResponse {
  readonly id: EntityId;
  readonly capability_key: string;
  readonly capability_version: string | null;
  readonly state: string;
  readonly external_execution_id: string | null;
  readonly engine_version: string | null;
  readonly environment_version: string | null;
  readonly container_image_digest: string | null;
  readonly node_identity: string | null;
  readonly resource_identities: Record<string, unknown>;
  readonly submitted_at: string;
  readonly started_at: string | null;
  readonly completed_at: string | null;
  readonly failure_code: string | null;
  readonly failure_message: string | null;
  readonly artifacts: readonly ScientificArtifactResponse[];
}

export interface ExecutionProvenanceResponse {
  readonly execution: ExecutionResponse;
  readonly scientific_executions: readonly ScientificExecutionResponse[];
  readonly configuration_snapshot: Record<string, unknown>;
}

export interface JobAttemptResponse {
  readonly attempt_number: number;
  readonly state: string;
  readonly worker_id: string | null;
  readonly node_id: string | null;
  readonly started_at: string | null;
  readonly finished_at: string | null;
  readonly failure_code: string | null;
  readonly failure_message: string | null;
  readonly error_class: string | null;
}

export interface JobResponse {
  readonly id: EntityId;
  readonly kind: string;
  readonly state: string;
  readonly queue: string;
  readonly priority: number;
  readonly node_class: string;
  readonly workspace_id: EntityId | null;
  readonly project_id: EntityId | null;
  readonly analysis_execution_id: EntityId | null;
  readonly attempt_number: number;
  readonly max_attempts: number;
  readonly available_at: string | null;
  readonly started_at: string | null;
  readonly completed_at: string | null;
  readonly progress_percent: number | null;
  readonly progress_message: string | null;
  readonly failure_code: string | null;
  readonly failure_message: string | null;
  readonly error_class: string | null;
  readonly cancellation_requested_at: string | null;
  readonly correlation_id: string;
  readonly created_at: string | null;
  readonly attempts: readonly JobAttemptResponse[];
}

export interface JobCollection {
  readonly items: readonly JobResponse[];
  readonly page: PageMeta;
}

export interface ScheduleResponse {
  readonly id: EntityId;
  readonly name: string;
  readonly description: string | null;
  readonly analysis_id: EntityId | null;
  readonly analysis_configuration_id: EntityId | null;
  readonly workspace_id: EntityId | null;
  readonly project_id: EntityId | null;
  readonly state: string;
  readonly schedule_kind: string;
  readonly schedule_expression: string;
  readonly timezone_name: string;
  readonly concurrency_policy: string;
  readonly missed_policy: string;
  readonly queue: string;
  readonly priority: number;
  readonly catch_up_limit: number;
  readonly next_execution_at: string | null;
  readonly last_triggered_at?: string | null;
  readonly capabilities?: readonly string[];
}

export interface ScheduleCollection {
  readonly items: readonly ScheduleResponse[];
  readonly page: PageMeta;
}
