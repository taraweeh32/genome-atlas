"""Validation of an annotation payload against the platform's own expectations.

This is where the platform decides whether it may store what an external tool
produced. It checks *attribution and shape* only:

* the contract version is one the platform understands;
* the payload answers the run it claims to answer;
* the resource identity matches the registered, usable resource version;
* the reference context matches the annotated surface;
* every field was declared by that resource version, with the declared type;
* every variant is part of the annotated surface;
* absence markers stay absence markers.

It never repairs a scientific value. A record that fails is rejected and recorded
as a finding; the remaining records are still accepted, so one malformed row does
not discard a whole annotation run.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.domain.annotation.entities import (
    AnnotationFieldSpec,
    AnnotationProfileVersionRecord,
    AnnotationResourceRecord,
    AnnotationRunRecord,
    AnnotationValidationFinding,
)
from app.domain.value_objects.enums import (
    AnnotationValueType,
    DataOrigin,
    ValidationSeverity,
    ValueSemantics,
)
from app.domain.variant.entities import AnnotationValue, VariantAnnotationRecord
from app.scientific.annotation import (
    ANNOTATION_CONTRACT_VERSION,
    MAX_INLINE_ANNOTATION_RECORDS,
    AnnotationPayload,
    AnnotationRecordClaim,
)

#: Contract versions the platform will still read. Old payloads stay readable.
ACCEPTED_ANNOTATION_CONTRACT_VERSIONS = frozenset({ANNOTATION_CONTRACT_VERSION})


@dataclass(frozen=True, slots=True)
class AnnotationValidationOutcome:
    """What may be stored, what was refused, and why."""

    records: tuple[VariantAnnotationRecord, ...]
    findings: tuple[AnnotationValidationFinding, ...]
    accepted_record_count: int
    rejected_record_count: int
    field_keys: tuple[str, ...]
    payload_digest: str

    @property
    def is_rejected(self) -> bool:
        """True when the payload as a whole cannot be stored."""
        return any(
            finding.severity is ValidationSeverity.BLOCKING for finding in self.findings
        )

    @property
    def blocking_finding(self) -> AnnotationValidationFinding | None:
        for finding in self.findings:
            if finding.severity is ValidationSeverity.BLOCKING:
                return finding
        return None


def payload_digest(payload: AnnotationPayload) -> str:
    """Stable digest of a payload's attributable content.

    Used for idempotency: re-delivering the same payload must not create a second
    annotation result version.
    """

    canonical = {
        "contract_version": payload.contract_version,
        "annotation_run_id": payload.annotation_run_id,
        "resource_key": payload.resource.resource_key,
        "resource_version": payload.resource.resource_version,
        "scientific_execution_id": payload.scientific_execution_id,
        "engine_version": payload.engine_version,
        "parameters_digest": payload.parameters_digest,
        "declared_record_count": payload.declared_record_count,
        "records": [
            {
                "variant_id": record.variant_id,
                "values": [
                    {
                        "field_key": value.field_key,
                        "transcript": value.transcript_identifier,
                        "semantics": value.value_semantics,
                        "value": (
                            value.value_string,
                            value.value_number,
                            value.value_integer,
                            value.value_boolean,
                            value.value_json,
                        ),
                    }
                    for value in record.values
                ],
            }
            for record in payload.records
        ],
        "artifacts": [
            {
                "artifact_key": artifact.artifact_key,
                "checksum": artifact.checksum_value,
                "location": artifact.analytical_location or artifact.storage_uri,
                "row_count": artifact.row_count,
            }
            for artifact in payload.artifacts
        ],
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


_TYPED_SLOTS: dict[AnnotationValueType, str] = {
    AnnotationValueType.STRING: "value_string",
    AnnotationValueType.INTEGER: "value_integer",
    AnnotationValueType.NUMBER: "value_number",
    AnnotationValueType.BOOLEAN: "value_boolean",
    AnnotationValueType.DATE: "value_string",
    AnnotationValueType.JSON: "value_json",
}


def _enum(raw: str, enumeration: Any) -> Any | None:
    try:
        return enumeration(raw)
    except ValueError:
        return None


def validate_annotation_payload(
    *,
    payload: AnnotationPayload,
    run: AnnotationRunRecord,
    resource: AnnotationResourceRecord,
    profile_version: AnnotationProfileVersionRecord | None = None,
    known_variant_ids: frozenset[str] | None = None,
    identifiers: Callable[[], str],
    now: datetime,
) -> AnnotationValidationOutcome:
    """Validate one annotation payload; never mutate scientific values."""

    findings: list[AnnotationValidationFinding] = []
    records: list[VariantAnnotationRecord] = []
    field_keys: list[str] = []
    rejected = 0
    digest = payload_digest(payload)

    def finding(
        code: str,
        message: str,
        *,
        severity: ValidationSeverity = ValidationSeverity.ERROR,
        field_key: str | None = None,
        variant_id: str | None = None,
        index: int | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        findings.append(
            AnnotationValidationFinding(
                id=identifiers(),
                annotation_run_id=run.id,
                code=code,
                message=message,
                severity=severity,
                field_key=field_key,
                variant_id=variant_id,
                record_index=index,
                detail=detail or {},
                created_at=now,
            )
        )

    def outcome() -> AnnotationValidationOutcome:
        return AnnotationValidationOutcome(
            records=tuple(records),
            findings=tuple(findings),
            accepted_record_count=len(records),
            rejected_record_count=rejected,
            field_keys=tuple(dict.fromkeys(field_keys)),
            payload_digest=digest,
        )

    # --- payload-level checks: any failure here rejects the whole payload ----
    if payload.contract_version not in ACCEPTED_ANNOTATION_CONTRACT_VERSIONS:
        finding(
            "unsupported_contract_version",
            "the annotation contract version is not supported",
            severity=ValidationSeverity.BLOCKING,
            detail={
                "contract_version": payload.contract_version,
                "supported": sorted(ACCEPTED_ANNOTATION_CONTRACT_VERSIONS),
            },
        )
        return outcome()

    if payload.annotation_run_id != run.id:
        finding(
            "run_mismatch",
            "the payload does not belong to this annotation run",
            severity=ValidationSeverity.BLOCKING,
            detail={"declared": payload.annotation_run_id},
        )
        return outcome()

    if not payload.resource.is_identified:
        finding(
            "resource_identity_missing",
            "an annotation payload must name its resource key and version",
            severity=ValidationSeverity.BLOCKING,
        )
        return outcome()

    if (
        payload.resource.resource_key != resource.resource_key
        or payload.resource.resource_version != resource.version
    ):
        finding(
            "resource_identity_mismatch",
            "the payload names a different annotation resource version than the run",
            severity=ValidationSeverity.BLOCKING,
            detail={
                "expected": f"{resource.resource_key}@{resource.version}",
                "declared": (
                    f"{payload.resource.resource_key}@{payload.resource.resource_version}"
                ),
            },
        )
        return outcome()

    if not resource.is_usable:
        finding(
            "resource_not_usable",
            "the annotation resource version is not available for use",
            severity=ValidationSeverity.BLOCKING,
            detail={"state": resource.state.value},
        )
        return outcome()

    if (
        resource.checksum_value
        and payload.resource.checksum_value
        and payload.resource.checksum_value != resource.checksum_value
    ):
        finding(
            "resource_checksum_mismatch",
            "the payload's resource content identity differs from the registered one",
            severity=ValidationSeverity.BLOCKING,
        )
        return outcome()

    expected_assembly = (
        run.genome_assembly
        or (profile_version.genome_assembly if profile_version else None)
        or resource.genome_assembly
    )
    if expected_assembly and payload.genome_assembly:
        if payload.genome_assembly != expected_assembly:
            finding(
                "reference_context_mismatch",
                "the annotation was produced against a different reference assembly",
                severity=ValidationSeverity.BLOCKING,
                detail={
                    "expected": expected_assembly,
                    "declared": payload.genome_assembly,
                },
            )
            return outcome()
    elif expected_assembly and not payload.genome_assembly:
        finding(
            "reference_context_undeclared",
            "the payload does not declare the reference assembly it used",
            severity=ValidationSeverity.WARNING,
            detail={"expected": expected_assembly},
        )

    if len(payload.records) > MAX_INLINE_ANNOTATION_RECORDS:
        finding(
            "inline_batch_too_large",
            "too many inline annotation records; deliver them as an artifact",
            severity=ValidationSeverity.BLOCKING,
            detail={
                "records": len(payload.records),
                "maximum": MAX_INLINE_ANNOTATION_RECORDS,
            },
        )
        return outcome()

    declared_fields = {
        specification.field_key: specification for specification in resource.fields
    }
    seen: set[tuple[str, str, str | None]] = set()

    # --- record-level checks: a bad record is refused, the rest are kept -----
    for index, record in enumerate(payload.records):
        accepted_any = False
        if not record.variant_id:
            finding(
                "variant_linkage_missing",
                "an annotation record must address a stored variant",
                index=index,
            )
            rejected += 1
            continue
        if known_variant_ids is not None and record.variant_id not in known_variant_ids:
            finding(
                "variant_not_in_surface",
                "the annotated variant is not part of the annotated surface",
                variant_id=record.variant_id,
                index=index,
            )
            rejected += 1
            continue
        origin = _enum(record.origin, DataOrigin)
        if origin is None:
            finding(
                "unknown_origin",
                "the annotation record declares an unknown origin",
                variant_id=record.variant_id,
                index=index,
                detail={"origin": record.origin},
            )
            rejected += 1
            continue
        if not record.values:
            finding(
                "empty_record",
                "the annotation record carries no field values",
                variant_id=record.variant_id,
                index=index,
                severity=ValidationSeverity.WARNING,
            )

        for claim in record.values:
            specification = declared_fields.get(claim.field_key)
            problem = _validate_claim(claim, specification)
            if problem is not None:
                code, message, detail = problem
                finding(
                    code,
                    message,
                    field_key=claim.field_key,
                    variant_id=record.variant_id,
                    index=index,
                    detail=detail,
                )
                rejected += 1
                continue
            key = (record.variant_id, claim.field_key, claim.transcript_identifier)
            if key in seen:
                # Idempotent by construction: a repeated claim inside one payload
                # is dropped rather than stored twice or used to overwrite.
                finding(
                    "duplicate_claim",
                    "a repeated annotation claim in the same payload was ignored",
                    severity=ValidationSeverity.INFO,
                    field_key=claim.field_key,
                    variant_id=record.variant_id,
                    index=index,
                )
                continue
            seen.add(key)
            value_type = AnnotationValueType(claim.value_type)
            semantics = ValueSemantics(claim.value_semantics)
            records.append(
                VariantAnnotationRecord(
                    id=identifiers(),
                    variant_id=record.variant_id,
                    annotation_resource_id=resource.id,
                    resource_version=resource.version,
                    field_key=claim.field_key,
                    value=AnnotationValue(
                        value_type=value_type,
                        semantics=semantics,
                        value_string=claim.value_string,
                        value_number=claim.value_number,
                        value_integer=claim.value_integer,
                        value_boolean=claim.value_boolean,
                        value_json=claim.value_json,
                    ),
                    origin=origin,
                    transcript_id=claim.transcript_identifier,
                    engine_resource_id=payload.engine_resource_id,
                    engine_version=payload.engine_version,
                    scientific_execution_id=payload.scientific_execution_id,
                    retrieved_at=record.retrieved_at,
                    provenance={
                        "annotation_run_id": run.id,
                        "resource_key": resource.resource_key,
                        "contract_version": payload.contract_version,
                        "node_identity": payload.node_identity,
                        "container_image_digest": payload.container_image_digest,
                        "is_development_payload": payload.is_development_payload,
                    },
                    created_at=now,
                )
            )
            field_keys.append(claim.field_key)
            accepted_any = True
        del accepted_any

    if (
        payload.declared_record_count is not None
        and payload.declared_record_count != len(payload.records)
        and not payload.artifacts
    ):
        # Reported, not corrected: the producer's own count is evidence about
        # completeness and the platform does not overrule it.
        finding(
            "record_count_mismatch",
            "the declared record count differs from the delivered records",
            severity=ValidationSeverity.WARNING,
            detail={
                "declared": payload.declared_record_count,
                "delivered": len(payload.records),
            },
        )

    return outcome()


def _validate_claim(
    claim: Any, specification: AnnotationFieldSpec | None
) -> tuple[str, str, dict[str, Any]] | None:
    """Return a problem tuple, or ``None`` when the claim is storable."""

    if specification is None:
        return (
            "undeclared_field",
            "the annotation resource version does not declare this field",
            {"field_key": claim.field_key},
        )
    value_type = _enum(claim.value_type, AnnotationValueType)
    if value_type is None:
        return (
            "unknown_value_type",
            "the annotation value declares an unknown type",
            {"value_type": claim.value_type},
        )
    if value_type is not specification.value_type:
        return (
            "value_type_mismatch",
            "the annotation value type differs from the declared field type",
            {"declared": value_type.value, "expected": specification.value_type.value},
        )
    semantics = _enum(claim.value_semantics, ValueSemantics)
    if semantics is None:
        return (
            "unknown_value_semantics",
            "the annotation value declares unknown semantics",
            {"value_semantics": claim.value_semantics},
        )
    slots = {
        "value_string": claim.value_string,
        "value_number": claim.value_number,
        "value_integer": claim.value_integer,
        "value_boolean": claim.value_boolean,
        "value_json": claim.value_json,
    }
    populated = [name for name, value in slots.items() if value is not None]
    if semantics is ValueSemantics.PRESENT:
        if len(populated) != 1:
            return (
                "value_slot_invalid",
                "a present annotation value populates exactly one typed slot",
                {"populated": populated},
            )
        if populated[0] != _TYPED_SLOTS[value_type]:
            return (
                "value_slot_mismatch",
                "the populated value slot does not match the declared type",
                {"populated": populated[0], "expected": _TYPED_SLOTS[value_type]},
            )
        if specification.allowed_values and claim.value_string is not None:
            if claim.value_string not in specification.allowed_values:
                return (
                    "value_not_allowed",
                    "the value is outside the vocabulary the field declares",
                    {"value": claim.value_string},
                )
    else:
        if populated:
            # The whole point of the semantics field: "missing" may never smuggle
            # a value that a later consumer would treat as real.
            return (
                "absent_value_carries_data",
                "a non-present annotation value must not carry a value",
                {"populated": populated},
            )
        if semantics not in specification.missing_semantics:
            return (
                "absence_marker_not_declared",
                "the field does not declare this absence marker",
                {
                    "value_semantics": semantics.value,
                    "declared": [item.value for item in specification.missing_semantics],
                },
            )
    if claim.transcript_identifier is not None and not str(
        claim.transcript_identifier
    ).strip():
        return ("blank_transcript", "a transcript identifier must not be blank", {})
    return None


__all__ = [
    "ACCEPTED_ANNOTATION_CONTRACT_VERSIONS",
    "AnnotationValidationOutcome",
    "payload_digest",
    "validate_annotation_payload",
]
