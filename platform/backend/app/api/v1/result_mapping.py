"""Mapping between the scientific data layer and its transport schemas.

One-directional and explicit, like the other mapping modules: every field a
client sees is named here, so adding a domain field never leaks it by accident.

The one judgement encoded here is that absence is preserved. A frequency that was
never reported serializes as ``null`` with ``value_semantics`` saying so — not as
``0.0``, which a downstream reader would treat as "this variant is absent from
that cohort", a completely different scientific statement.
"""

from __future__ import annotations

from typing import Any

from app.api.v1.schemas.results import (
    AnnotationResponse,
    ClinicalAssertionResponse,
    FrequencyResponse,
    ResultArtifactResponse,
    ResultContentResponse,
    ResultProvenanceResponse,
    ResultSetResponse,
    SampleObservationResponse,
    TranscriptContextResponse,
    VariantDetailResponse,
    VariantIdentifierResponse,
    VariantRepresentationResponse,
    VariantResponse,
    VariantSourceRepresentationResponse,
)
from app.domain.variant.entities import (
    ClinicalAssertionRecord,
    PopulationFrequencyRecord,
    SampleObservation,
    TranscriptContext,
    VariantAnnotationRecord,
    VariantExternalIdentifier,
    VariantRecord,
    VariantRepresentation,
    VariantSourceRepresentation,
)
from app.domain.variant.results import (
    ResultArtifactRecord,
    ResultProvenance,
    ResultSetRecord,
)


def _plain(value: dict[str, Any] | None) -> dict[str, object]:
    return dict(value or {})


def provenance_response(provenance: ResultProvenance) -> ResultProvenanceResponse:
    return ResultProvenanceResponse(
        analysis_execution_id=provenance.analysis_execution_id,
        scientific_execution_id=provenance.scientific_execution_id,
        analysis_configuration_id=provenance.analysis_configuration_id,
        engine_resource_id=provenance.engine_resource_id,
        engine_version=provenance.engine_version,
        environment_version=provenance.environment_version,
        container_image_digest=provenance.container_image_digest,
        node_identity=provenance.node_identity,
        reference_genome_resource_id=provenance.reference_genome_resource_id,
        resource_identities=_plain(provenance.resource_identities),
        parameters_digest=provenance.parameters_digest,
        is_attributable=provenance.is_attributable,
    )


def artifact_response(artifact: ResultArtifactRecord) -> ResultArtifactResponse:
    return ResultArtifactResponse(
        id=artifact.id,
        result_set_id=artifact.result_set_id,
        artifact_key=artifact.artifact_key,
        kind=artifact.kind.value,
        artifact_format=artifact.artifact_format.value,
        state=artifact.state.value,
        media_type=artifact.media_type,
        size_bytes=artifact.size_bytes,
        checksum_algorithm=(
            artifact.checksum_algorithm.value if artifact.checksum_algorithm else None
        ),
        row_count=artifact.row_count,
        column_schema=_plain(artifact.column_schema),
        failure_code=artifact.failure_code,
        failure_message=artifact.failure_message,
        verified_at=artifact.verified_at,
        is_readable=artifact.is_readable,
    )


def result_set_response(
    result_set: ResultSetRecord,
    *,
    artifacts: tuple[ResultArtifactRecord, ...] = (),
    capabilities: tuple[str, ...] = (),
) -> ResultSetResponse:
    return ResultSetResponse(
        id=result_set.id,
        workspace_id=result_set.workspace_id,
        project_id=result_set.project_id,
        result_key=result_set.result_key,
        state=result_set.state.value,
        completeness=result_set.completeness.value,
        origin=result_set.origin.value,
        row_count=result_set.row_count,
        column_schema=_plain(result_set.column_schema),
        provenance=provenance_response(result_set.provenance),
        superseded_by_result_set_id=result_set.superseded_by_result_set_id,
        invalidation_reason=result_set.invalidation_reason,
        failure_code=result_set.failure_code,
        failure_message=result_set.failure_message,
        available_at=result_set.available_at,
        created_at=result_set.created_at,
        is_readable=result_set.is_readable,
        is_development_payload=bool(
            (result_set.metadata or {}).get("is_development_payload")
        ),
        artifacts=[artifact_response(item) for item in artifacts],
        capabilities=list(capabilities),
    )


def result_content_response(view: Any, *, offset: int) -> ResultContentResponse:
    return ResultContentResponse(
        result_set_id=view.result_set_id,
        state=view.state.value,
        columns=list(view.page.columns),
        rows=[list(row) for row in view.page.rows],
        total_rows=view.page.total_rows,
        offset=offset,
        is_development_payload=view.is_development_payload,
    )


def variant_response(variant: VariantRecord) -> VariantResponse:
    identity = variant.identity
    return VariantResponse(
        id=variant.id,
        canonical_key=identity.key,
        reference_genome_resource_id=identity.reference_genome_resource_id,
        contig=identity.contig.canonical,
        source_contig=identity.contig.source,
        position=identity.position,
        end_position=identity.end_position,
        reference_allele=identity.reference_allele,
        alternate_allele=identity.alternate_allele,
        variant_class=identity.variant_class.value,
        normalization_state=identity.normalization_state.value,
        normalization_version=identity.normalization_version,
        symbolic_allele=identity.symbolic_allele,
        structural_variant_type=identity.structural_variant_type,
        origin=variant.origin.value,
        scientific_execution_id=variant.scientific_execution_id,
    )


def representation_response(
    representation: VariantRepresentation,
) -> VariantRepresentationResponse:
    return VariantRepresentationResponse(
        id=representation.id,
        normalization_state=representation.normalization_state.value,
        normalization_version=representation.normalization_version,
        origin=representation.origin.value,
        contig=representation.contig.canonical,
        position=representation.position,
        reference_allele=representation.reference_allele,
        alternate_allele=representation.alternate_allele,
        normalization_engine_resource_id=(
            representation.normalization_engine_resource_id
        ),
        scientific_execution_id=representation.scientific_execution_id,
        failure_code=representation.failure_code,
        failure_message=representation.failure_message,
        recorded_at=representation.recorded_at,
        succeeded=representation.succeeded,
    )


def source_representation_response(
    source: VariantSourceRepresentation,
) -> VariantSourceRepresentationResponse:
    return VariantSourceRepresentationResponse(
        id=source.id,
        dataset_version_id=source.dataset_version_id,
        source_record_key=source.source_record_key,
        source_contig=source.source_contig,
        source_position=source.source_position,
        source_reference_allele=source.source_reference_allele,
        source_alternate_allele=source.source_alternate_allele,
        source_identifier=source.source_identifier,
        normalization_state=source.normalization_state.value,
        normalization_failure_reason=source.normalization_failure_reason,
        is_unresolved=source.is_unresolved,
    )


def identifier_response(
    identifier: VariantExternalIdentifier,
) -> VariantIdentifierResponse:
    return VariantIdentifierResponse(
        namespace=identifier.namespace,
        external_identifier=identifier.external_identifier,
        origin=identifier.origin.value,
        source_resource_id=identifier.source_resource_id,
        is_primary=identifier.is_primary,
    )


def transcript_context_response(context: TranscriptContext) -> TranscriptContextResponse:
    return TranscriptContextResponse(
        id=context.id,
        consequence_term=context.consequence_term,
        origin=context.origin.value,
        transcript_id=context.transcript_id,
        gene_id=context.gene_id,
        impact=context.impact,
        hgvs_genomic=context.hgvs_genomic,
        hgvs_coding=context.hgvs_coding,
        hgvs_protein=context.hgvs_protein,
        exon=context.exon,
        intron=context.intron,
        source_resource_id=context.source_resource_id,
        engine_resource_id=context.engine_resource_id,
        scientific_execution_id=context.scientific_execution_id,
    )


def observation_response(observation: SampleObservation) -> SampleObservationResponse:
    return SampleObservationResponse(
        id=observation.id,
        sample_id=observation.sample_id,
        dataset_version_id=observation.dataset_version_id,
        zygosity=observation.zygosity.value,
        genotype_semantics=observation.genotype_semantics.value,
        genotype=observation.genotype,
        allele_balance=observation.allele_balance,
        read_depth=observation.read_depth,
        alternate_allele_depth=observation.alternate_allele_depth,
        genotype_quality=observation.genotype_quality,
        variant_quality=observation.variant_quality,
        filter_status=observation.filter_status,
    )


def annotation_response(annotation: VariantAnnotationRecord) -> AnnotationResponse:
    value = annotation.value
    return AnnotationResponse(
        id=annotation.id,
        annotation_resource_id=annotation.annotation_resource_id,
        resource_version=annotation.resource_version,
        field_key=annotation.field_key,
        value_type=value.value_type.value,
        value_semantics=value.semantics.value,
        value_string=value.value_string,
        value_number=value.value_number,
        value_integer=value.value_integer,
        value_boolean=value.value_boolean,
        value_json=value.value_json,
        origin=annotation.origin.value,
        engine_resource_id=annotation.engine_resource_id,
        engine_version=annotation.engine_version,
        retrieved_at=annotation.retrieved_at,
    )


def frequency_response(frequency: PopulationFrequencyRecord) -> FrequencyResponse:
    return FrequencyResponse(
        id=frequency.id,
        population_id=frequency.population_id,
        population_resource_id=frequency.population_resource_id,
        resource_version=frequency.resource_version,
        origin=frequency.origin.value,
        allele_frequency=frequency.allele_frequency,
        allele_count=frequency.allele_count,
        allele_number=frequency.allele_number,
        homozygote_count=frequency.homozygote_count,
        hemizygote_count=frequency.hemizygote_count,
        value_semantics=frequency.value_semantics.value,
        subset_key=frequency.subset_key,
        denominator_context=_plain(frequency.denominator_context),
        retrieved_at=frequency.retrieved_at,
    )


def clinical_assertion_response(
    assertion: ClinicalAssertionRecord,
) -> ClinicalAssertionResponse:
    return ClinicalAssertionResponse(
        id=assertion.id,
        source_id=assertion.source_id,
        external_record_identifier=assertion.external_record_identifier,
        reported_classification=assertion.reported_classification,
        review_status_text=assertion.review_status_text,
        assertion_statement=assertion.assertion_statement,
        condition_term=assertion.condition_term,
        condition_namespace=assertion.condition_namespace,
        condition_identifier=assertion.condition_identifier,
        assertion_method=assertion.assertion_method,
        submitter=assertion.submitter,
        asserted_at=assertion.asserted_at,
        last_evaluated_at=assertion.last_evaluated_at,
        conflict_information=_plain(assertion.conflict_information),
        origin=assertion.origin.value,
        value_semantics=assertion.value_semantics.value,
        retrieved_at=assertion.retrieved_at,
    )


def variant_detail_response(view: Any) -> VariantDetailResponse:
    return VariantDetailResponse(
        variant=variant_response(view.variant),
        representations=[representation_response(item) for item in view.representations],
        source_representations=[
            source_representation_response(item) for item in view.source_representations
        ],
        identifiers=[identifier_response(item) for item in view.identifiers],
        transcript_contexts=[
            transcript_context_response(item) for item in view.transcript_contexts.items
        ],
        observations=[observation_response(item) for item in view.observations.items],
        annotations=[annotation_response(item) for item in view.annotations.items],
        frequencies=[frequency_response(item) for item in view.frequencies.items],
        clinical_assertions=[
            clinical_assertion_response(item) for item in view.clinical_assertions.items
        ],
    )


__all__ = [
    "annotation_response",
    "artifact_response",
    "clinical_assertion_response",
    "frequency_response",
    "identifier_response",
    "observation_response",
    "provenance_response",
    "representation_response",
    "result_content_response",
    "result_set_response",
    "source_representation_response",
    "transcript_context_response",
    "variant_detail_response",
    "variant_response",
]
