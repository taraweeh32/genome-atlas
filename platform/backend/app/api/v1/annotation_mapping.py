"""Mapping between the annotation layer and its transport schemas.

One-directional and explicit, like the other mapping modules: every field a client
sees is named here, so adding a domain field never leaks it by accident.

The judgements encoded here: identity always travels with its version, absence
markers are preserved rather than flattened, and bulk annotation values are not
serialized — a result version exposes counts and its analytical location, and the
values themselves are read through the variant and filtering surfaces.
"""

from __future__ import annotations

from typing import Any

from app.api.v1.mapping import parse_enum
from app.api.v1.schemas.annotation import (
    AnnotationFieldSpecPayload,
    AnnotationFieldSpecResponse,
    AnnotationProfileResponse,
    AnnotationProfileVersionResponse,
    AnnotationResourceResponse,
    AnnotationResultResponse,
    AnnotationRunResponse,
    AnnotationValidationFindingResponse,
    FilterFieldSummaryResponse,
    IngestAnnotationPayloadBody,
    ProfileResourceBindingResponse,
)
from app.domain.annotation.entities import (
    AnnotationFieldSpec,
    AnnotationProfileRecord,
    AnnotationProfileVersionRecord,
    AnnotationResourceRecord,
    AnnotationResultVersionRecord,
    AnnotationRunRecord,
    AnnotationValidationFinding,
    ProfileResourceBinding,
)
from app.domain.query.fields import FilterFieldDefinition
from app.domain.value_objects.enums import (
    AnnotationValueType,
    DataOrigin,
    ResultCompleteness,
    ValueSemantics,
)
from app.scientific.annotation import (
    AnnotationArtifactClaim,
    AnnotationFieldValueClaim,
    AnnotationPayload,
    AnnotationRecordClaim,
    AnnotationResourceIdentity,
)


def _plain(value: dict[str, Any] | None) -> dict[str, object]:
    return dict(value or {})


def field_spec_from_payload(payload: AnnotationFieldSpecPayload) -> AnnotationFieldSpec:
    return AnnotationFieldSpec(
        field_key=payload.field_key,
        label=payload.label,
        value_type=parse_enum(
            AnnotationValueType, payload.value_type, field="fields.value_type"
        ),
        description=payload.description,
        missing_semantics=tuple(
            parse_enum(ValueSemantics, item, field="fields.missing_semantics")
            for item in payload.missing_semantics or ()
        )
        or AnnotationFieldSpec.missing_semantics,
        allowed_values=tuple(payload.allowed_values or ()),
        unit=payload.unit,
        high_cardinality=payload.high_cardinality,
        filterable=payload.filterable,
        sortable=payload.sortable,
        scientific_category=payload.scientific_category,
        column=payload.column,
        metadata=payload.metadata,
    )


def field_spec_response(spec: AnnotationFieldSpec) -> AnnotationFieldSpecResponse:
    return AnnotationFieldSpecResponse(
        field_key=spec.field_key,
        label=spec.label,
        value_type=spec.value_type.value,
        description=spec.description,
        missing_semantics=[item.value for item in spec.missing_semantics],
        allowed_values=list(spec.allowed_values),
        unit=spec.unit,
        high_cardinality=spec.high_cardinality,
        filterable=spec.filterable,
        sortable=spec.sortable,
        scientific_category=spec.scientific_category,
        analytical_column=spec.analytical_column,
    )


def resource_response(record: AnnotationResourceRecord) -> AnnotationResourceResponse:
    return AnnotationResourceResponse(
        id=record.id,
        resource_key=record.resource_key,
        version=record.version,
        display_name=record.display_name,
        category=record.category.value,
        state=record.state.value,
        provider=record.provider,
        description=record.description,
        genome_assembly=record.genome_assembly,
        reference_genome_resource_id=record.reference_genome_resource_id,
        release_label=record.release_label,
        released_at=record.released_at,
        schema_version=record.schema_version,
        checksum_algorithm=record.checksum_algorithm,
        checksum_value=record.checksum_value,
        size_bytes=record.size_bytes,
        is_usable=record.is_usable,
        fields=[field_spec_response(spec) for spec in record.fields],
        provenance=_plain(record.provenance),
        licensing=_plain(record.licensing),
        metadata=_plain(record.metadata),
        activated_at=record.activated_at,
        deprecated_at=record.deprecated_at,
        retired_at=record.retired_at,
        invalidated_at=record.invalidated_at,
        invalidation_reason=record.invalidation_reason,
        created_at=record.created_at,
    )


def filter_field_response(
    definition: FilterFieldDefinition,
) -> FilterFieldSummaryResponse:
    metadata = _plain(definition.metadata)
    return FilterFieldSummaryResponse(
        id=definition.id,
        label=definition.label,
        description=definition.description,
        data_type=definition.data_type.value,
        category=definition.category.value,
        operators=[operator.value for operator in definition.operators],
        nullable=definition.nullable,
        missing_semantics=[item.value for item in definition.missing_semantics],
        high_cardinality=definition.high_cardinality,
        sortable=definition.sortable,
        filterable=definition.filterable,
        scientific_category=definition.scientific_category,
        source_resource_key=metadata.get("annotation_resource_key"),  # type: ignore[arg-type]
        source_resource_version=metadata.get("annotation_resource_version"),  # type: ignore[arg-type]
        available=definition.available,
        version=definition.version,
    )


def binding_response(
    binding: ProfileResourceBinding,
) -> ProfileResourceBindingResponse:
    return ProfileResourceBindingResponse(
        resource_id=binding.resource_id,
        resource_key=binding.resource_key,
        resource_version=binding.resource_version,
        category=binding.category.value,
        role=binding.role,
    )


def profile_version_response(
    version: AnnotationProfileVersionRecord,
) -> AnnotationProfileVersionResponse:
    return AnnotationProfileVersionResponse(
        id=version.id,
        profile_id=version.profile_id,
        version_number=version.version_number,
        capability_id=version.capability_id,
        capability_version=version.capability_version,
        configuration_digest=version.configuration_digest,
        engine_resource_id=version.engine_resource_id,
        engine_version=version.engine_version,
        genome_assembly=version.genome_assembly,
        reference_genome_resource_id=version.reference_genome_resource_id,
        required_inputs=list(version.required_inputs),
        output_field_keys=list(version.output_field_keys),
        parameters=_plain(version.parameters),
        provenance_requirements=list(version.provenance_requirements),
        schema_version=version.schema_version,
        change_note=version.change_note,
        is_referenced=version.is_referenced,
        resources=[binding_response(binding) for binding in version.resources],
        created_at=version.created_at,
    )


def profile_response(
    profile: AnnotationProfileRecord,
    *,
    versions: tuple[AnnotationProfileVersionRecord, ...] = (),
) -> AnnotationProfileResponse:
    return AnnotationProfileResponse(
        id=profile.id,
        name=profile.name,
        state=profile.state.value,
        description=profile.description,
        latest_version_number=profile.latest_version_number,
        is_referenced=profile.is_referenced,
        is_offered=profile.is_offered,
        metadata=_plain(profile.metadata),
        created_at=profile.created_at,
        versions=[profile_version_response(version) for version in versions],
    )


def finding_response(
    finding: AnnotationValidationFinding,
) -> AnnotationValidationFindingResponse:
    return AnnotationValidationFindingResponse(
        id=finding.id,
        code=finding.code,
        message=finding.message,
        severity=finding.severity.value,
        field_key=finding.field_key,
        variant_id=finding.variant_id,
        record_index=finding.record_index,
        detail=_plain(finding.detail),
    )


def run_response(
    run: AnnotationRunRecord,
    *,
    findings: tuple[AnnotationValidationFinding, ...] = (),
) -> AnnotationRunResponse:
    return AnnotationRunResponse(
        id=run.id,
        workspace_id=run.workspace_id,
        project_id=run.project_id,
        profile_id=run.profile_id,
        profile_version_id=run.profile_version_id,
        profile_version_number=run.profile_version_number,
        state=run.state.value,
        result_set_id=run.result_set_id,
        dataset_version_id=run.dataset_version_id,
        requested_by=run.requested_by,
        requested_at=run.requested_at,
        submitted_at=run.submitted_at,
        completed_at=run.completed_at,
        job_id=run.job_id,
        scientific_execution_id=run.scientific_execution_id,
        external_execution_id=run.external_execution_id,
        capability_id=run.capability_id,
        capability_version=run.capability_version,
        engine_resource_id=run.engine_resource_id,
        engine_version=run.engine_version,
        environment_version=run.environment_version,
        container_image_digest=run.container_image_digest,
        node_identity=run.node_identity,
        genome_assembly=run.genome_assembly,
        configuration_digest=run.configuration_digest,
        configuration_snapshot=_plain(dict(run.configuration_snapshot)),
        correlation_id=run.correlation_id,
        failure_code=run.failure_code,
        failure_message=run.failure_message,
        record_count=run.record_count,
        is_terminal=run.is_terminal,
        findings=[finding_response(item) for item in findings],
    )


def result_response(
    result: AnnotationResultVersionRecord,
) -> AnnotationResultResponse:
    return AnnotationResultResponse(
        id=result.id,
        annotation_run_id=result.annotation_run_id,
        workspace_id=result.workspace_id,
        project_id=result.project_id,
        resource_id=result.resource_id,
        resource_key=result.resource_key,
        resource_version=result.resource_version,
        version_number=result.version_number,
        state=result.state.value,
        result_set_id=result.result_set_id,
        dataset_version_id=result.dataset_version_id,
        profile_version_id=result.profile_version_id,
        scientific_execution_id=result.scientific_execution_id,
        engine_version=result.engine_version,
        environment_version=result.environment_version,
        container_image_digest=result.container_image_digest,
        node_identity=result.node_identity,
        genome_assembly=result.genome_assembly,
        analytical_location=result.analytical_location,
        checksum_algorithm=result.checksum_algorithm,
        checksum_value=result.checksum_value,
        row_count=result.row_count,
        stored_record_count=result.stored_record_count,
        declared_record_count=result.declared_record_count,
        rejected_record_count=result.rejected_record_count,
        field_keys=list(result.field_keys),
        contract_version=result.contract_version,
        payload_digest=result.payload_digest,
        parameters_digest=result.parameters_digest,
        completeness=result.completeness.value
        if hasattr(result.completeness, "value")
        else str(result.completeness),
        is_development_payload=result.is_development_payload,
        supersedes_id=result.supersedes_id,
        superseded_by_id=result.superseded_by_id,
        is_readable=result.is_readable,
        provenance=_plain(result.provenance),
        ingested_at=result.ingested_at,
        created_at=result.created_at,
    )


def ingestion_payload(
    body: IngestAnnotationPayloadBody, *, annotation_run_id: str
) -> AnnotationPayload:
    """Transport body to the scientific annotation contract.

    Enum values are parsed here rather than coerced: an unrecognised value type,
    absence marker or origin is a validation error, never a silent default, because
    defaulting it would change what the producer claimed.
    """
    return AnnotationPayload(
        contract_version=body.contract_version,
        annotation_run_id=annotation_run_id,
        resource=AnnotationResourceIdentity(
            resource_key=body.resource.resource_key,
            resource_version=body.resource.resource_version,
            resource_id=body.resource.resource_id,
            schema_version=body.resource.schema_version,
            genome_assembly=body.resource.genome_assembly,
            checksum_algorithm=body.resource.checksum_algorithm,
            checksum_value=body.resource.checksum_value,
        ),
        engine_resource_id=body.engine_resource_id,
        engine_version=body.engine_version,
        environment_version=body.environment_version,
        container_image_digest=body.container_image_digest,
        node_identity=body.node_identity,
        scientific_execution_id=body.scientific_execution_id,
        genome_assembly=body.genome_assembly,
        parameters_digest=body.parameters_digest,
        records=tuple(
            AnnotationRecordClaim(
                variant_id=record.variant_id,
                values=tuple(
                    AnnotationFieldValueClaim(
                        field_key=value.field_key,
                        value_type=parse_enum(
                            AnnotationValueType,
                            value.value_type,
                            field="records.values.value_type",
                        ),
                        value_semantics=parse_enum(
                            ValueSemantics,
                            value.value_semantics,
                            field="records.values.value_semantics",
                        )
                        if value.value_semantics
                        else ValueSemantics.PRESENT,
                        value_string=value.value_string,
                        value_number=value.value_number,
                        value_integer=value.value_integer,
                        value_boolean=value.value_boolean,
                        value_json=value.value_json,
                        transcript_identifier=value.transcript_identifier,
                    )
                    for value in record.values
                ),
                source_variant_key=record.source_variant_key,
                origin=parse_enum(DataOrigin, record.origin, field="records.origin")
                if record.origin
                else DataOrigin.RETRIEVED,
                retrieved_at=record.retrieved_at,
            )
            for record in body.records
        ),
        artifacts=tuple(
            AnnotationArtifactClaim(
                artifact_key=artifact.artifact_key,
                kind=artifact.kind,
                storage_uri=artifact.storage_uri,
                analytical_location=artifact.analytical_location,
                media_type=artifact.media_type,
                size_bytes=artifact.size_bytes,
                checksum_algorithm=artifact.checksum_algorithm,
                checksum_value=artifact.checksum_value,
                row_count=artifact.row_count,
                column_schema=artifact.column_schema,
            )
            for artifact in body.artifacts
        ),
        declared_record_count=body.declared_record_count,
        completeness=parse_enum(
            ResultCompleteness, body.completeness, field="completeness"
        )
        if body.completeness
        else ResultCompleteness.COMPLETE,
        metadata=body.metadata,
        is_development_payload=body.is_development_payload,
    )


__all__ = [
    "field_spec_from_payload",
    "field_spec_response",
    "filter_field_response",
    "finding_response",
    "ingestion_payload",
    "profile_response",
    "profile_version_response",
    "resource_response",
    "result_response",
    "run_response",
]
