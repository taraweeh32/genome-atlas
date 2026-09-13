/**
 * Transport types for result surfaces and variant records.
 *
 * These mirror the versioned REST contract exactly. Three rules govern how the
 * UI is allowed to use them:
 *
 * - `is_readable`, `capabilities` and `is_attributable` are server answers. The
 *   client renders them and never derives an equivalent locally.
 * - `is_development_payload` marks content produced by a development stub of the
 *   scientific subsystem. It must always be surfaced, never hidden.
 * - Absent scientific values arrive as `null` beside a `value_semantics` field.
 *   The UI shows the semantics; it never substitutes `0`, `false` or `""`.
 *
 * Nothing here computes, normalizes, annotates, filters, ranks or classifies:
 * variant content is displayed exactly as the scientific subsystem declared it.
 */

import type { PageMeta } from "./identity-types";
import type { EntityId } from "./types";

export interface ResultProvenanceResponse {
  readonly analysis_execution_id: EntityId;
  readonly scientific_execution_id: string | null;
  readonly analysis_configuration_id: EntityId | null;
  readonly engine_resource_id: string | null;
  readonly engine_version: string | null;
  readonly environment_version: string | null;
  readonly container_image_digest: string | null;
  readonly node_identity: string | null;
  readonly reference_genome_resource_id: string | null;
  readonly resource_identities: Record<string, unknown>;
  readonly parameters_digest: string | null;
  readonly is_attributable: boolean;
}

export interface ResultArtifactResponse {
  readonly id: EntityId;
  readonly result_set_id: EntityId;
  readonly artifact_key: string;
  readonly kind: string;
  readonly artifact_format: string;
  readonly state: string;
  readonly media_type: string | null;
  readonly size_bytes: number | null;
  readonly checksum_algorithm: string | null;
  readonly row_count: number | null;
  readonly column_schema: Record<string, unknown>;
  readonly failure_code: string | null;
}

export interface ResultSetResponse {
  readonly id: EntityId;
  readonly workspace_id: EntityId;
  readonly project_id: EntityId;
  readonly result_key: string;
  readonly state: string;
  readonly completeness: string;
  readonly origin: string;
  readonly row_count: number | null;
  readonly column_schema: Record<string, unknown>;
  readonly provenance: ResultProvenanceResponse;
  readonly superseded_by_result_set_id: EntityId | null;
  readonly invalidation_reason: string | null;
  readonly failure_code: string | null;
  readonly failure_message: string | null;
  readonly available_at: string | null;
  readonly created_at: string | null;
  readonly is_readable: boolean;
  readonly is_development_payload: boolean;
  readonly artifacts: readonly ResultArtifactResponse[];
  readonly capabilities: readonly string[];
}

export interface ResultSetCollection {
  readonly items: readonly ResultSetResponse[];
  readonly page: PageMeta;
}

/** A bounded window of a materialized surface, exactly as stored. */
export interface ResultContentResponse {
  readonly result_set_id: EntityId;
  readonly state: string;
  readonly columns: readonly string[];
  readonly rows: readonly (readonly unknown[])[];
  readonly total_rows: number;
  readonly offset: number;
  readonly is_development_payload: boolean;
}

export interface ArtifactDownloadResponse {
  readonly artifact_id: EntityId;
  readonly artifact_key: string;
  readonly url: string;
  readonly expires_in_seconds: number;
}

export interface VariantResponse {
  readonly id: EntityId;
  readonly canonical_key: string;
  readonly reference_genome_resource_id: string;
  readonly contig: string;
  readonly source_contig: string | null;
  readonly position: number;
  readonly end_position: number | null;
  readonly reference_allele: string;
  readonly alternate_allele: string;
  readonly variant_class: string;
  readonly normalization_state: string;
  readonly normalization_version: string;
  readonly symbolic_allele: string | null;
  readonly structural_variant_type: string | null;
  readonly origin: string;
  readonly scientific_execution_id: string | null;
}

export interface VariantCollection {
  readonly items: readonly VariantResponse[];
  readonly page: PageMeta;
}

export interface VariantRepresentationResponse {
  readonly id: EntityId;
  readonly normalization_state: string;
  readonly normalization_version: string;
  readonly origin: string;
  readonly contig: string;
  readonly position: number | null;
  readonly reference_allele: string | null;
  readonly alternate_allele: string | null;
  readonly normalization_engine_resource_id: string | null;
  readonly scientific_execution_id: string | null;
  readonly failure_code: string | null;
  readonly failure_message: string | null;
  readonly recorded_at: string | null;
  readonly succeeded: boolean;
}

export interface VariantSourceRepresentationResponse {
  readonly id: EntityId;
  readonly dataset_version_id: EntityId;
  readonly source_record_key: string;
  readonly source_contig: string;
  readonly source_position: number;
  readonly source_reference_allele: string | null;
  readonly source_alternate_allele: string | null;
  readonly source_identifier: string | null;
  readonly normalization_state: string;
  readonly normalization_failure_reason: string | null;
  readonly is_unresolved: boolean;
}

export interface VariantIdentifierResponse {
  readonly namespace: string;
  readonly external_identifier: string;
  readonly origin: string;
  readonly source_resource_id: string | null;
  readonly is_primary: boolean;
}

export interface TranscriptContextResponse {
  readonly id: EntityId;
  readonly consequence_term: string;
  readonly origin: string;
  readonly transcript_id: string | null;
  readonly gene_id: string | null;
  readonly impact: string | null;
  readonly hgvs_genomic: string | null;
  readonly hgvs_coding: string | null;
  readonly hgvs_protein: string | null;
  readonly exon: string | null;
  readonly intron: string | null;
  readonly source_resource_id: string | null;
  readonly engine_resource_id: string | null;
  readonly scientific_execution_id: string | null;
}

export interface SampleObservationResponse {
  readonly id: EntityId;
  readonly sample_id: EntityId;
  readonly dataset_version_id: EntityId;
  readonly zygosity: string;
  readonly genotype_semantics: string;
  readonly genotype: string | null;
  readonly allele_balance: number | null;
  readonly read_depth: number | null;
  readonly alternate_allele_depth: number | null;
  readonly genotype_quality: number | null;
  readonly variant_quality: number | null;
  readonly filter_status: string | null;
}

export interface AnnotationResponse {
  readonly id: EntityId;
  readonly annotation_resource_id: string;
  readonly resource_version: string;
  readonly field_key: string;
  readonly value_type: string;
  readonly value_semantics: string;
  readonly value_string: string | null;
  readonly value_number: number | null;
  readonly value_integer: number | null;
  readonly value_boolean: boolean | null;
  readonly value_json: Record<string, unknown> | null;
  readonly origin: string;
  readonly engine_resource_id: string | null;
  readonly engine_version: string | null;
  readonly retrieved_at: string | null;
}

export interface FrequencyResponse {
  readonly id: EntityId;
  readonly population_id: EntityId;
  readonly population_resource_id: string;
  readonly resource_version: string;
  readonly origin: string;
  readonly allele_frequency: number | null;
  readonly allele_count: number | null;
  readonly allele_number: number | null;
  readonly homozygote_count: number | null;
  readonly hemizygote_count: number | null;
  readonly value_semantics: string;
  readonly subset_key: string | null;
  readonly denominator_context: Record<string, unknown>;
  readonly retrieved_at: string | null;
}

export interface ClinicalAssertionResponse {
  readonly id: EntityId;
  readonly source_id: string;
  readonly external_record_identifier: string;
  readonly reported_classification: string | null;
  readonly review_status_text: string | null;
  readonly assertion_statement: string | null;
  readonly condition_term: string | null;
  readonly condition_namespace: string | null;
  readonly condition_identifier: string | null;
  readonly assertion_method: string | null;
  readonly submitter: string | null;
  readonly asserted_at: string | null;
  readonly last_evaluated_at: string | null;
  readonly conflict_information: Record<string, unknown>;
  readonly origin: string;
  readonly value_semantics: string;
  readonly retrieved_at: string | null;
}

/** A variant with every recorded context, each keeping its own attribution. */
export interface VariantDetailResponse {
  readonly variant: VariantResponse;
  readonly representations: readonly VariantRepresentationResponse[];
  readonly source_representations: readonly VariantSourceRepresentationResponse[];
  readonly identifiers: readonly VariantIdentifierResponse[];
  readonly transcript_contexts: readonly TranscriptContextResponse[];
  readonly observations: readonly SampleObservationResponse[];
  readonly annotations: readonly AnnotationResponse[];
  readonly frequencies: readonly FrequencyResponse[];
  readonly clinical_assertions: readonly ClinicalAssertionResponse[];
}
