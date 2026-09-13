"""Structural acceptance of an ingestion payload.

Structural, and only structural. This module answers questions of the form
"is this claim well-formed, attributed and internally consistent?" It never
answers "is this claim scientifically correct?" — that judgement belongs to the
scientific subsystem and its independent validation, and nothing here would be a
substitute for it.

The distinction shows up in the vocabulary of the findings. A finding is either

``ERROR``
    the payload violates the contract, so the claim cannot be stored without
    changing its meaning (an unattributed annotation, a normalized record with no
    coordinates, an observation whose sample is not in the dataset version);
``WARNING``
    the payload is storable but something about it should be visible to a human
    (a normalization the engine reported as unavailable, a source contig spelled
    differently from the reference, zero variants in a payload declared complete).

Errors reject the payload. Warnings are recorded on the ingestion request and
travel with the result set, because quietly dropping them would make a degraded
ingestion look like a clean one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.value_objects.enums import (
    AnnotationValueType,
    DataOrigin,
    NormalizationState,
    ResultArtifactFormat,
    ResultArtifactKind,
    ResultCompleteness,
    ValueSemantics,
    VariantClass,
    Zygosity,
)
from app.scientific.results import (
    RESULT_CONTRACT_VERSION,
    ClaimAttribution,
    ResultPayload,
    VariantClaim,
    VariantIngestionPayload,
)

SEVERITY_ERROR = "error"
SEVERITY_WARNING = "warning"


@dataclass(frozen=True, slots=True)
class Finding:
    """One structural observation about a payload."""

    severity: str
    code: str
    message: str
    location: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "location": self.location,
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    """The verdict on a payload, with every finding retained.

    ``accepted`` is not "no findings": a payload with warnings is accepted *and*
    keeps its warnings. Callers store ``findings`` verbatim.
    """

    findings: tuple[Finding, ...] = ()

    @property
    def errors(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == SEVERITY_ERROR)

    @property
    def warnings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity == SEVERITY_WARNING)

    @property
    def accepted(self) -> bool:
        return not self.errors

    def as_dicts(self) -> tuple[dict[str, Any], ...]:
        return tuple(finding.as_dict() for finding in self.findings)


def _known(vocabulary: type, value: str | None) -> bool:
    if value is None:
        return False
    try:
        vocabulary(value)
    except ValueError:
        return False
    return True


def _check_attribution(
    attribution: ClaimAttribution, location: str, findings: list[Finding]
) -> None:
    if not _known(DataOrigin, attribution.origin):
        findings.append(
            Finding(
                SEVERITY_ERROR,
                "unknown_origin",
                "origin is not a recognized data origin",
                location,
                {"origin": attribution.origin},
            )
        )
    if not attribution.names_a_producer:
        # An unattributed scientific claim is worse than a missing one: it cannot
        # be reproduced, re-evaluated or withdrawn when its producer is found to
        # be defective.
        findings.append(
            Finding(
                SEVERITY_ERROR,
                "unattributed_claim",
                "a derived claim must name a versioned engine or source resource",
                location,
            )
        )


def _validate_canonical(claim: VariantClaim, location: str, findings: list[Finding]) -> None:
    canonical = claim.canonical
    if not _known(NormalizationState, canonical.normalization_state):
        findings.append(
            Finding(
                SEVERITY_ERROR,
                "unknown_normalization_state",
                "normalization state is not a recognized value",
                location,
                {"normalization_state": canonical.normalization_state},
            )
        )
        return
    state = NormalizationState(canonical.normalization_state)

    if not _known(VariantClass, canonical.variant_class):
        # Not defaulted to SNV: guessing the class from allele strings is exactly
        # the kind of scientific inference this layer must not perform.
        findings.append(
            Finding(
                SEVERITY_ERROR,
                "unknown_variant_class",
                "variant class is not a recognized value",
                location,
                {"variant_class": canonical.variant_class},
            )
        )
    if not canonical.reference_genome_resource_id:
        findings.append(
            Finding(
                SEVERITY_ERROR,
                "missing_reference_genome",
                "a canonical representation requires its reference genome resource",
                location,
            )
        )
    if not canonical.normalization_version:
        findings.append(
            Finding(
                SEVERITY_ERROR,
                "missing_normalization_version",
                "the normalization procedure must be identified even when it did not run",
                location,
            )
        )

    if state is NormalizationState.NORMALIZED:
        if canonical.position is None or canonical.reference_allele is None:
            findings.append(
                Finding(
                    SEVERITY_ERROR,
                    "incomplete_normalized_representation",
                    "a normalized representation must carry coordinates and alleles",
                    location,
                )
            )
        if canonical.position is not None and canonical.position < 1:
            findings.append(
                Finding(
                    SEVERITY_ERROR,
                    "invalid_position",
                    "positions are 1-based",
                    location,
                    {"position": canonical.position},
                )
            )
    elif state is NormalizationState.NORMALIZATION_FAILED:
        if not (canonical.failure_code or canonical.failure_message):
            findings.append(
                Finding(
                    SEVERITY_ERROR,
                    "unexplained_normalization_failure",
                    "a normalization failure must state its reason",
                    location,
                )
            )
        findings.append(
            Finding(
                SEVERITY_WARNING,
                "normalization_failed",
                "the record is retained without a canonical representation",
                location,
            )
        )
    elif state is NormalizationState.NORMALIZATION_UNAVAILABLE:
        findings.append(
            Finding(
                SEVERITY_WARNING,
                "normalization_unavailable",
                "the engine had no normalization capability for this record",
                location,
            )
        )

    if claim.source is not None and claim.source.contig != canonical.contig:
        findings.append(
            Finding(
                SEVERITY_WARNING,
                "contig_renamed",
                "the reference context spells the contig differently from the source",
                location,
                {"source": claim.source.contig, "canonical": canonical.contig},
            )
        )


def _validate_observations(
    claim: VariantClaim,
    location: str,
    known_sample_keys: frozenset[str] | None,
    findings: list[Finding],
) -> None:
    for index, observation in enumerate(claim.observations):
        where = f"{location}.observations[{index}]"
        if not _known(Zygosity, observation.zygosity):
            findings.append(
                Finding(
                    SEVERITY_ERROR,
                    "unknown_zygosity",
                    "zygosity is not a recognized value and is never inferred",
                    where,
                    {"zygosity": observation.zygosity},
                )
            )
        if not _known(ValueSemantics, observation.genotype_semantics):
            findings.append(
                Finding(
                    SEVERITY_ERROR,
                    "unknown_value_semantics",
                    "genotype semantics is not a recognized value",
                    where,
                )
            )
        elif (
            observation.genotype is None
            and ValueSemantics(observation.genotype_semantics) is ValueSemantics.PRESENT
        ):
            findings.append(
                Finding(
                    SEVERITY_ERROR,
                    "absent_genotype_declared_present",
                    "an absent genotype cannot be recorded as present",
                    where,
                )
            )
        if known_sample_keys is not None and observation.sample_key not in known_sample_keys:
            # Accepting it would attach subject-level data to a sample the
            # dataset version never declared — an integrity and a privacy problem.
            findings.append(
                Finding(
                    SEVERITY_ERROR,
                    "unknown_sample",
                    "the observation names a sample that this dataset version does not declare",
                    where,
                    {"sample_key": observation.sample_key},
                )
            )


def _validate_evidence(claim: VariantClaim, location: str, findings: list[Finding]) -> None:
    for index, context in enumerate(claim.transcript_contexts):
        _check_attribution(context.attribution, f"{location}.transcript_contexts[{index}]", findings)
    for index, annotation in enumerate(claim.annotations):
        where = f"{location}.annotations[{index}]"
        _check_attribution(annotation.attribution, where, findings)
        if not _known(AnnotationValueType, annotation.value_type):
            findings.append(
                Finding(
                    SEVERITY_ERROR,
                    "unknown_value_type",
                    "annotation value type is not a recognized value",
                    where,
                    {"value_type": annotation.value_type},
                )
            )
        if not _known(ValueSemantics, annotation.value_semantics):
            findings.append(
                Finding(
                    SEVERITY_ERROR,
                    "unknown_value_semantics",
                    "annotation value semantics is not a recognized value",
                    where,
                )
            )
    for index, frequency in enumerate(claim.frequencies):
        where = f"{location}.frequencies[{index}]"
        _check_attribution(frequency.attribution, where, findings)
        if (
            _known(ValueSemantics, frequency.value_semantics)
            and ValueSemantics(frequency.value_semantics) is ValueSemantics.PRESENT
            and frequency.allele_frequency is None
            and frequency.allele_count is None
        ):
            findings.append(
                Finding(
                    SEVERITY_ERROR,
                    "empty_frequency_observation",
                    "a present frequency observation must report a frequency or a count",
                    where,
                )
            )
        if frequency.allele_frequency is not None and not 0.0 <= frequency.allele_frequency <= 1.0:
            findings.append(
                Finding(
                    SEVERITY_ERROR,
                    "frequency_out_of_range",
                    "an allele frequency outside [0, 1] cannot be stored as a frequency",
                    where,
                    {"allele_frequency": frequency.allele_frequency},
                )
            )
    for index, assertion in enumerate(claim.clinical_assertions):
        where = f"{location}.clinical_assertions[{index}]"
        _check_attribution(assertion.attribution, where, findings)
        if assertion.clinical_significance is None and assertion.review_status is None:
            findings.append(
                Finding(
                    SEVERITY_WARNING,
                    "empty_clinical_assertion",
                    "the assertion carries neither a significance nor a review status",
                    where,
                )
            )


def validate_variant_payload(
    payload: VariantIngestionPayload,
    *,
    known_sample_keys: frozenset[str] | None = None,
    max_variants: int = 50_000,
) -> ValidationOutcome:
    """Check one variant batch against the contract.

    ``known_sample_keys`` comes from the dataset version's declared samples. When
    it is ``None`` the caller has stated that sample membership is not checkable
    here; that is a deliberate, explicit choice rather than a silent skip.
    """
    findings: list[Finding] = []

    if payload.contract_version != RESULT_CONTRACT_VERSION:
        findings.append(
            Finding(
                SEVERITY_ERROR,
                "unsupported_contract_version",
                "the payload was produced against a different result contract version",
                "payload",
                {
                    "received": payload.contract_version,
                    "supported": RESULT_CONTRACT_VERSION,
                },
            )
        )
    if not _known(ResultCompleteness, payload.completeness):
        findings.append(
            Finding(
                SEVERITY_ERROR,
                "unknown_completeness",
                "completeness is not a recognized value",
                "payload",
                {"completeness": payload.completeness},
            )
        )
    _check_attribution(payload.attribution, "payload", findings)

    if len(payload.variants) > max_variants:
        # Bulk volumes belong in artifacts on the analytical path, not in a
        # single transactional payload.
        findings.append(
            Finding(
                SEVERITY_ERROR,
                "payload_too_large",
                "the batch exceeds the transactional ingestion limit; use result artifacts",
                "payload",
                {"variants": len(payload.variants), "limit": max_variants},
            )
        )
    if (
        payload.declared_variant_count is not None
        and payload.declared_variant_count != len(payload.variants)
    ):
        findings.append(
            Finding(
                SEVERITY_ERROR,
                "variant_count_mismatch",
                "the payload contains a different number of variants than it declared",
                "payload",
                {
                    "declared": payload.declared_variant_count,
                    "received": len(payload.variants),
                },
            )
        )
    if not payload.variants and payload.completeness == ResultCompleteness.COMPLETE.value:
        findings.append(
            Finding(
                SEVERITY_WARNING,
                "complete_but_empty",
                "the engine declared a complete batch that contains no variants",
                "payload",
            )
        )

    seen_source_keys: set[str] = set()
    for index, claim in enumerate(payload.variants):
        location = f"variants[{index}]"
        _validate_canonical(claim, location, findings)
        _validate_observations(claim, location, known_sample_keys, findings)
        _validate_evidence(claim, location, findings)
        if claim.source is not None:
            if claim.source.source_record_key in seen_source_keys:
                findings.append(
                    Finding(
                        SEVERITY_ERROR,
                        "duplicate_source_record",
                        "the batch claims the same source record twice",
                        location,
                        {"source_record_key": claim.source.source_record_key},
                    )
                )
            seen_source_keys.add(claim.source.source_record_key)

    return ValidationOutcome(tuple(findings))


def validate_result_payload(payload: ResultPayload) -> ValidationOutcome:
    """Check a result surface registration against the contract."""
    findings: list[Finding] = []

    if payload.contract_version != RESULT_CONTRACT_VERSION:
        findings.append(
            Finding(
                SEVERITY_ERROR,
                "unsupported_contract_version",
                "the payload was produced against a different result contract version",
                "payload",
                {
                    "received": payload.contract_version,
                    "supported": RESULT_CONTRACT_VERSION,
                },
            )
        )
    if not payload.result_key.strip():
        findings.append(
            Finding(SEVERITY_ERROR, "missing_result_key", "a result key is required", "payload")
        )
    if not _known(ResultCompleteness, payload.completeness):
        findings.append(
            Finding(
                SEVERITY_ERROR,
                "unknown_completeness",
                "completeness is not a recognized value",
                "payload",
                {"completeness": payload.completeness},
            )
        )
    _check_attribution(payload.attribution, "payload", findings)

    if not payload.artifacts and payload.analytical_location is None:
        findings.append(
            Finding(
                SEVERITY_ERROR,
                "empty_result_surface",
                "a result set must register at least one artifact or an analytical location",
                "payload",
            )
        )

    seen_keys: set[str] = set()
    for index, artifact in enumerate(payload.artifacts):
        where = f"artifacts[{index}]"
        if artifact.artifact_key in seen_keys:
            findings.append(
                Finding(
                    SEVERITY_ERROR,
                    "duplicate_artifact_key",
                    "artifact keys are unique within a result set",
                    where,
                    {"artifact_key": artifact.artifact_key},
                )
            )
        seen_keys.add(artifact.artifact_key)
        if not _known(ResultArtifactKind, artifact.kind):
            findings.append(
                Finding(
                    SEVERITY_ERROR,
                    "unknown_artifact_kind",
                    "artifact kind is not a recognized value",
                    where,
                    {"kind": artifact.kind},
                )
            )
        if not _known(ResultArtifactFormat, artifact.artifact_format):
            findings.append(
                Finding(
                    SEVERITY_ERROR,
                    "unknown_artifact_format",
                    "artifact format is not a recognized value",
                    where,
                    {"format": artifact.artifact_format},
                )
            )
        if artifact.storage_uri is None and artifact.analytical_location is None:
            findings.append(
                Finding(
                    SEVERITY_ERROR,
                    "unlocatable_artifact",
                    "an artifact must be locatable in storage",
                    where,
                )
            )
        if artifact.checksum_value is None:
            # Without a declared checksum the platform can register the object but
            # can never prove it is the object the engine produced.
            findings.append(
                Finding(
                    SEVERITY_WARNING,
                    "artifact_without_checksum",
                    "the artifact cannot be integrity-verified without a checksum",
                    where,
                )
            )
        if (
            artifact.artifact_format == ResultArtifactFormat.PARQUET.value
            and not artifact.column_schema
        ):
            findings.append(
                Finding(
                    SEVERITY_WARNING,
                    "tabular_artifact_without_schema",
                    "a tabular artifact without a column contract cannot be filtered later",
                    where,
                )
            )

    return ValidationOutcome(tuple(findings))


__all__ = [
    "SEVERITY_ERROR",
    "SEVERITY_WARNING",
    "Finding",
    "ValidationOutcome",
    "validate_result_payload",
    "validate_variant_payload",
]
