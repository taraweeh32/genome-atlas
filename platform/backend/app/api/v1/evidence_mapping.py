"""Mapping between the evidence layer and its transport schemas.

One-directional and explicit, like the other mapping modules: every field a client
sees is named here, so adding a domain field never leaks it by accident.

The judgements encoded here: identity always travels with its version, release time
and retrieval time stay separate, origin is always stated, source values are passed
through verbatim, and disagreement is serialized as its own object rather than
folded into a record.
"""

from __future__ import annotations

from typing import Any

from app.api.v1.mapping import parse_enum
from app.api.v1.schemas.evidence import (
    EvidenceClaimBody,
    EvidenceConflictResponse,
    EvidenceContextResponse,
    EvidenceIngestionBatchResponse,
    EvidenceRecordResponse,
    EvidenceSourceResponse,
    EvidenceValidationFindingResponse,
    IngestEvidencePayloadBody,
)
from app.domain.evidence.entities import (
    EvidenceConflict,
    EvidenceIngestionBatch,
    EvidenceRecord,
    EvidenceSourceRecord,
    EvidenceValidationFinding,
)
from app.domain.value_objects.enums import (
    ChecksumAlgorithm,
    CriterionDirection,
    DataOrigin,
    EvidenceApplicability,
    EvidenceCategory,
    EvidenceStrength,
)
from app.scientific.evidence import (
    EvidenceArtifactClaim,
    EvidenceClaim,
    EvidencePayload,
    EvidenceSourceIdentity,
)


def _plain(value: dict[str, Any] | None) -> dict[str, object]:
    return dict(value or {})


def source_response(record: EvidenceSourceRecord) -> EvidenceSourceResponse:
    return EvidenceSourceResponse(
        id=record.id,
        source_key=record.source_key,
        version=record.version,
        display_name=record.display_name,
        category=record.category.value,
        state=record.state.value,
        usable=record.is_usable,
        provider=record.provider,
        description=record.description,
        release_label=record.release_label,
        released_at=record.released_at,
        retrieved_at=record.retrieved_at,
        schema_version=record.schema_version,
        genome_assembly=record.genome_assembly,
        checksum_algorithm=record.checksum_algorithm,
        checksum_value=record.checksum_value,
        size_bytes=record.size_bytes,
        supplies=[item.value for item in record.supplies],
        supplies_strength=record.supplies_strength,
        licensing=_plain(record.licensing),
        provenance=_plain(record.provenance),
        registered_by=record.registered_by,
        activated_at=record.activated_at,
        deprecated_at=record.deprecated_at,
        retired_at=record.retired_at,
        invalidated_at=record.invalidated_at,
        invalidation_reason=record.invalidation_reason,
        created_at=record.created_at,
    )


def record_response(record: EvidenceRecord) -> EvidenceRecordResponse:
    return EvidenceRecordResponse(
        id=record.id,
        variant_id=record.variant_id,
        category=record.category.value,
        origin=record.origin.value,
        state=record.state.value,
        current=record.is_current,
        source_key=record.source_key,
        source_version=record.source_version,
        source_identifier=record.source_identifier,
        source_released_at=record.source_released_at,
        retrieved_at=record.retrieved_at,
        workspace_id=record.workspace_id,
        project_id=record.project_id,
        context=EvidenceContextResponse(
            gene_symbol=record.context.gene_symbol,
            gene_identifier=record.context.gene_identifier,
            transcript_identifier=record.context.transcript_identifier,
            condition_identifier=record.context.condition_identifier,
            condition_term=record.context.condition_term,
            inheritance=record.context.inheritance,
        ),
        direction=record.direction.value,
        strength=record.strength.value,
        applicability=record.applicability.value,
        summary=record.summary,
        rationale=record.rationale,
        external_reference=record.external_reference,
        method=record.method,
        evidence_key=record.evidence_key,
        version_number=record.version_number,
        supersedes_id=record.supersedes_id,
        superseded_by_id=record.superseded_by_id,
        ingestion_batch_id=record.ingestion_batch_id,
        scientific_execution_id=record.scientific_execution_id,
        values=_plain(record.payload),
        provenance=_plain(record.provenance),
        recorded_at=record.recorded_at,
        created_by=record.created_by,
        created_at=record.created_at,
    )


def conflict_response(conflict: EvidenceConflict) -> EvidenceConflictResponse:
    return EvidenceConflictResponse(
        group_key=conflict.group_key,
        variant_id=conflict.variant_id,
        category=conflict.category.value,
        kind=conflict.kind.value,
        evidence_ids=list(conflict.evidence_ids),
        source_keys=list(conflict.source_keys),
        detail=_plain(conflict.detail),
    )


def finding_response(
    finding: EvidenceValidationFinding,
) -> EvidenceValidationFindingResponse:
    return EvidenceValidationFindingResponse(
        id=finding.id,
        code=finding.code,
        message=finding.message,
        severity=finding.severity.value,
        evidence_id=finding.evidence_id,
        variant_id=finding.variant_id,
        record_index=finding.record_index,
        detail=_plain(finding.detail),
        created_at=finding.created_at,
    )


def batch_response(batch: EvidenceIngestionBatch) -> EvidenceIngestionBatchResponse:
    return EvidenceIngestionBatchResponse(
        id=batch.id,
        source_key=batch.source_key,
        source_version=batch.source_version,
        state=batch.state.value,
        origin=batch.origin.value,
        workspace_id=batch.workspace_id,
        project_id=batch.project_id,
        claimed_record_count=batch.claimed_record_count,
        stored_record_count=batch.stored_record_count,
        superseded_record_count=batch.superseded_record_count,
        duplicate_record_count=batch.duplicate_record_count,
        rejected_record_count=batch.rejected_record_count,
        retrieved_at=batch.retrieved_at,
        source_released_at=batch.source_released_at,
        requested_by=batch.requested_by,
        job_id=batch.job_id,
        correlation_id=batch.correlation_id,
        provenance=_plain(batch.provenance),
        failure_code=batch.failure_code,
        failure_message=batch.failure_message,
        completed_at=batch.completed_at,
        created_at=batch.created_at,
    )


def _claim(body: EvidenceClaimBody) -> EvidenceClaim:
    return EvidenceClaim(
        category=parse_enum(EvidenceCategory, body.category, field="category"),
        variant_id=body.variant_id,
        variant_identifier=body.variant_identifier,
        direction=parse_enum(CriterionDirection, body.direction, field="direction")
        if body.direction
        else CriterionDirection.NEUTRAL,
        strength=parse_enum(EvidenceStrength, body.strength, field="strength")
        if body.strength
        else EvidenceStrength.NOT_APPLICABLE,
        applicability=parse_enum(
            EvidenceApplicability, body.applicability, field="applicability"
        )
        if body.applicability
        else EvidenceApplicability.UNDETERMINED,
        source_identifier=body.source_identifier,
        evidence_key=body.evidence_key,
        summary=body.summary,
        rationale=body.rationale,
        method=body.method,
        external_reference=body.external_reference,
        gene_symbol=body.gene_symbol,
        gene_identifier=body.gene_identifier,
        transcript_identifier=body.transcript_identifier,
        condition_identifier=body.condition_identifier,
        condition_term=body.condition_term,
        inheritance=body.inheritance,
        source_released_at=body.source_released_at,
        retrieved_at=body.retrieved_at,
        # Verbatim. The platform never reshapes a scientific value.
        values=_plain(body.values),
    )


def ingestion_payload(body: IngestEvidencePayloadBody) -> EvidencePayload:
    """Build the delivery contract object from transport input.

    Enum values are parsed here so an unknown value is a 400 with the allowed set —
    never a silent default that would misattribute provenance.
    """
    return EvidencePayload(
        source=EvidenceSourceIdentity(
            source_key=body.source_key,
            version=body.source_version,
            release_label=body.release_label,
            released_at=body.source_released_at,
        ),
        origin=parse_enum(DataOrigin, body.origin, field="origin")
        if body.origin
        else DataOrigin.RETRIEVED,
        contract_version=body.contract_version,
        retrieved_at=body.retrieved_at,
        scientific_execution_id=body.scientific_execution_id,
        correlation_id=body.correlation_id,
        is_development_payload=body.is_development_payload,
        claims=tuple(_claim(claim) for claim in body.claims),
        artifact=EvidenceArtifactClaim(
            storage_key=body.artifact.storage_key,
            media_type=body.artifact.format,
            record_count=body.artifact.record_count,
            size_bytes=body.artifact.size_bytes,
            checksum_algorithm=parse_enum(
                ChecksumAlgorithm,
                body.artifact.checksum_algorithm,
                field="checksum_algorithm",
            )
            if body.artifact.checksum_algorithm
            else None,
            checksum_value=body.artifact.checksum_value,
        )
        if body.artifact
        else None,
        provenance=_plain(body.provenance),
    )


__all__ = [
    "batch_response",
    "conflict_response",
    "finding_response",
    "ingestion_payload",
    "record_response",
    "source_response",
]
