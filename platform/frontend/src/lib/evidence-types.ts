/**
 * Transport types for evidence sources, records, deliveries and conflicts.
 *
 * Three rules govern their use in the UI:
 *
 * - Nothing here is interpreted in the browser. A record is what a source or a
 *   curator *stated*; the client displays it and never decides what it means.
 * - `current`, `usable` and `state` are server answers. The client renders them
 *   and never derives an equivalent locally.
 * - Conflicts arrive unresolved on purpose. The UI shows disagreement side by
 *   side; it never picks a winner and never hides the losing record.
 */

import type { PageMeta } from "./identity-types";
import type { EntityId } from "./types";

export interface EvidenceSourceResponse {
  readonly id: EntityId;
  readonly source_key: string;
  readonly version: string;
  readonly display_name: string;
  readonly category: string;
  readonly state: string;
  readonly usable: boolean;
  readonly provider: string | null;
  readonly description: string | null;
  readonly release_label: string | null;
  readonly released_at: string | null;
  readonly retrieved_at: string | null;
  readonly schema_version: string | null;
  readonly genome_assembly: string | null;
  readonly checksum_algorithm: string | null;
  readonly checksum_value: string | null;
  readonly size_bytes: number | null;
  readonly supplies: readonly string[];
  readonly supplies_strength: boolean;
  readonly licensing: Record<string, unknown>;
  readonly provenance: Record<string, unknown>;
  readonly registered_by: string | null;
  readonly activated_at: string | null;
  readonly deprecated_at: string | null;
  readonly retired_at: string | null;
  readonly invalidated_at: string | null;
  readonly invalidation_reason: string | null;
  readonly created_at: string | null;
}

export interface EvidenceSourceCollection {
  readonly items: readonly EvidenceSourceResponse[];
  readonly page: PageMeta;
}

export interface EvidenceContextResponse {
  readonly gene_symbol: string | null;
  readonly gene_identifier: string | null;
  readonly transcript_identifier: string | null;
  readonly condition_identifier: string | null;
  readonly condition_term: string | null;
  readonly inheritance: string | null;
}

export interface EvidenceRecordResponse {
  readonly id: EntityId;
  readonly variant_id: EntityId;
  readonly category: string;
  readonly origin: string;
  readonly state: string;
  readonly current: boolean;
  readonly source_key: string | null;
  readonly source_version: string | null;
  readonly source_identifier: string | null;
  readonly source_released_at: string | null;
  readonly retrieved_at: string | null;
  readonly workspace_id: EntityId | null;
  readonly project_id: EntityId | null;
  readonly context: EvidenceContextResponse;
  readonly direction: string;
  readonly strength: string;
  readonly applicability: string;
  readonly summary: string | null;
  readonly rationale: string | null;
  readonly external_reference: string | null;
  readonly method: string | null;
  readonly evidence_key: string | null;
  readonly version_number: number;
  readonly supersedes_id: EntityId | null;
  readonly superseded_by_id: EntityId | null;
  readonly ingestion_batch_id: EntityId | null;
  readonly scientific_execution_id: EntityId | null;
  readonly values: Record<string, unknown>;
  readonly provenance: Record<string, unknown>;
  readonly recorded_at: string | null;
  readonly created_by: EntityId | null;
  readonly created_at: string | null;
}

export interface EvidenceRecordCollection {
  readonly items: readonly EvidenceRecordResponse[];
  readonly page: PageMeta;
}

export interface EvidenceHistoryResponse {
  readonly variant_id: EntityId;
  readonly records: readonly EvidenceRecordResponse[];
}

export interface EvidenceConflictResponse {
  readonly group_key: string;
  readonly variant_id: EntityId;
  readonly category: string;
  readonly kind: string;
  readonly evidence_ids: readonly EntityId[];
  readonly source_keys: readonly string[];
  readonly detail: Record<string, unknown>;
}

export interface EvidenceConflictCollection {
  readonly variant_id: EntityId;
  readonly conflicts: readonly EvidenceConflictResponse[];
}

export interface EvidenceValidationFindingResponse {
  readonly id: EntityId;
  readonly code: string;
  readonly message: string;
  readonly severity: string;
  readonly evidence_id: EntityId | null;
  readonly variant_id: EntityId | null;
  readonly record_index: number | null;
  readonly detail: Record<string, unknown>;
  readonly created_at: string | null;
}

export interface EvidenceValidationFindingCollection {
  readonly items: readonly EvidenceValidationFindingResponse[];
  readonly page: PageMeta;
}

export interface EvidenceIngestionBatchResponse {
  readonly id: EntityId;
  readonly source_key: string;
  readonly source_version: string;
  readonly state: string;
  readonly origin: string;
  readonly workspace_id: EntityId | null;
  readonly project_id: EntityId | null;
  readonly claimed_record_count: number;
  readonly stored_record_count: number;
  readonly superseded_record_count: number;
  readonly duplicate_record_count: number;
  readonly rejected_record_count: number;
  readonly retrieved_at: string | null;
  readonly source_released_at: string | null;
  readonly requested_by: EntityId | null;
  readonly job_id: EntityId | null;
  readonly correlation_id: string | null;
  readonly provenance: Record<string, unknown>;
  readonly failure_code: string | null;
  readonly failure_message: string | null;
  readonly completed_at: string | null;
  readonly created_at: string | null;
}

export interface EvidenceIngestionBatchCollection {
  readonly items: readonly EvidenceIngestionBatchResponse[];
  readonly page: PageMeta;
}
