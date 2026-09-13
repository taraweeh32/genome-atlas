"""Transport schemas for variants and result surfaces.

Conventions carried over from the other schema modules: request payloads forbid
unknown fields, responses expose enum *values*, and nothing internal is
serialized to a tenant client.

Two things specific to this surface:

* Every response that carries scientific content also carries its provenance and
  its ``is_development_payload`` flag. A stub result must be recognisable as one
  in the API, not only in the database.
* Absent values are ``null`` with a semantics field beside them, never ``0`` or
  ``""``. A client that shows "0.0" where nothing was reported is a client that
  invents a scientific claim.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.v1.schemas.common import ApiModel, Collection
from app.api.v1.schemas.tenancy import PageMeta

# --------------------------------------------------------------------------- #
# Result surfaces                                                             #
# --------------------------------------------------------------------------- #


class ResultProvenanceResponse(ApiModel):
    """The full chain a result is attributable to. Nulls are meaningful."""

    analysis_execution_id: str
    scientific_execution_id: str | None
    analysis_configuration_id: str | None
    engine_resource_id: str | None
    engine_version: str | None
    environment_version: str | None
    container_image_digest: str | None
    node_identity: str | None
    reference_genome_resource_id: str | None
    resource_identities: dict[str, object]
    parameters_digest: str | None
    is_attributable: bool


class ResultArtifactResponse(ApiModel):
    id: str
    result_set_id: str
    artifact_key: str
    kind: str
    artifact_format: str
    state: str
    media_type: str | None
    size_bytes: int | None
    checksum_algorithm: str | None
    row_count: int | None
    column_schema: dict[str, object]
    failure_code: str | None
    failure_message: str | None
    verified_at: datetime | None
    is_readable: bool


class ResultSetResponse(ApiModel):
    id: str
    workspace_id: str
    project_id: str
    result_key: str
    state: str
    completeness: str
    origin: str
    row_count: int | None
    column_schema: dict[str, object]
    provenance: ResultProvenanceResponse
    superseded_by_result_set_id: str | None
    invalidation_reason: str | None
    failure_code: str | None
    failure_message: str | None
    available_at: datetime | None
    created_at: datetime | None
    is_readable: bool
    is_development_payload: bool
    artifacts: list[ResultArtifactResponse] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)


class ResultSetCollection(Collection[ResultSetResponse]):
    page: PageMeta


class ResultContentResponse(ApiModel):
    """A bounded window of a materialized surface, exactly as stored."""

    result_set_id: str
    state: str
    columns: list[str]
    rows: list[list[object]]
    total_rows: int
    offset: int
    is_development_payload: bool


class ArtifactDownloadResponse(ApiModel):
    artifact_id: str
    artifact_key: str
    url: str
    expires_in_seconds: int


class ResultInvalidatePayload(ApiModel):
    reason: str = Field(min_length=1, max_length=1000)


class ResultSupersedePayload(ApiModel):
    superseded_by_result_set_id: str


# --------------------------------------------------------------------------- #
# Variants                                                                    #
# --------------------------------------------------------------------------- #


class VariantResponse(ApiModel):
    id: str
    canonical_key: str
    reference_genome_resource_id: str
    contig: str
    source_contig: str | None
    position: int
    end_position: int | None
    reference_allele: str
    alternate_allele: str
    variant_class: str
    normalization_state: str
    normalization_version: str
    symbolic_allele: str | None
    structural_variant_type: str | None
    origin: str
    scientific_execution_id: str | None


class VariantCollection(Collection[VariantResponse]):
    page: PageMeta


class VariantRepresentationResponse(ApiModel):
    id: str
    normalization_state: str
    normalization_version: str
    origin: str
    contig: str
    position: int | None
    reference_allele: str | None
    alternate_allele: str | None
    normalization_engine_resource_id: str | None
    scientific_execution_id: str | None
    failure_code: str | None
    failure_message: str | None
    recorded_at: datetime | None
    succeeded: bool


class VariantSourceRepresentationResponse(ApiModel):
    id: str
    dataset_version_id: str
    source_record_key: str
    source_contig: str
    source_position: int
    source_reference_allele: str | None
    source_alternate_allele: str | None
    source_identifier: str | None
    normalization_state: str
    normalization_failure_reason: str | None
    is_unresolved: bool


class VariantIdentifierResponse(ApiModel):
    namespace: str
    external_identifier: str
    origin: str
    source_resource_id: str | None
    is_primary: bool


class TranscriptContextResponse(ApiModel):
    id: str
    consequence_term: str
    origin: str
    transcript_id: str | None
    gene_id: str | None
    impact: str | None
    hgvs_genomic: str | None
    hgvs_coding: str | None
    hgvs_protein: str | None
    exon: str | None
    intron: str | None
    source_resource_id: str | None
    engine_resource_id: str | None
    scientific_execution_id: str | None


class SampleObservationResponse(ApiModel):
    id: str
    sample_id: str
    dataset_version_id: str
    zygosity: str
    genotype_semantics: str
    genotype: str | None
    allele_balance: float | None
    read_depth: int | None
    alternate_allele_depth: int | None
    genotype_quality: int | None
    variant_quality: float | None
    filter_status: str | None


class AnnotationResponse(ApiModel):
    id: str
    annotation_resource_id: str
    resource_version: str
    field_key: str
    value_type: str
    value_semantics: str
    value_string: str | None
    value_number: float | None
    value_integer: int | None
    value_boolean: bool | None
    value_json: dict[str, object] | None
    origin: str
    engine_resource_id: str | None
    engine_version: str | None
    retrieved_at: datetime | None


class FrequencyResponse(ApiModel):
    id: str
    population_id: str
    population_resource_id: str
    resource_version: str
    origin: str
    allele_frequency: float | None
    allele_count: int | None
    allele_number: int | None
    homozygote_count: int | None
    hemizygote_count: int | None
    value_semantics: str
    subset_key: str | None
    denominator_context: dict[str, object]
    retrieved_at: datetime | None


class ClinicalAssertionResponse(ApiModel):
    id: str
    source_id: str
    external_record_identifier: str
    reported_classification: str | None
    review_status_text: str | None
    assertion_statement: str | None
    condition_term: str | None
    condition_namespace: str | None
    condition_identifier: str | None
    assertion_method: str | None
    submitter: str | None
    asserted_at: datetime | None
    last_evaluated_at: datetime | None
    conflict_information: dict[str, object]
    origin: str
    value_semantics: str
    retrieved_at: datetime | None


class VariantDetailResponse(ApiModel):
    """A variant with every recorded context, each keeping its own attribution."""

    variant: VariantResponse
    representations: list[VariantRepresentationResponse]
    source_representations: list[VariantSourceRepresentationResponse]
    identifiers: list[VariantIdentifierResponse]
    transcript_contexts: list[TranscriptContextResponse]
    observations: list[SampleObservationResponse]
    annotations: list[AnnotationResponse]
    frequencies: list[FrequencyResponse]
    clinical_assertions: list[ClinicalAssertionResponse]


__all__ = [
    "AnnotationResponse",
    "ArtifactDownloadResponse",
    "ClinicalAssertionResponse",
    "FrequencyResponse",
    "ResultArtifactResponse",
    "ResultContentResponse",
    "ResultInvalidatePayload",
    "ResultProvenanceResponse",
    "ResultSetCollection",
    "ResultSetResponse",
    "ResultSupersedePayload",
    "SampleObservationResponse",
    "TranscriptContextResponse",
    "VariantCollection",
    "VariantDetailResponse",
    "VariantIdentifierResponse",
    "VariantRepresentationResponse",
    "VariantResponse",
    "VariantSourceRepresentationResponse",
]
