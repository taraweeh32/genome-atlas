"""Validation of an interpretation payload against the platform's expectations.

This is where the platform decides whether it may store what the rules engine
returned. It checks *attribution, shape and authorization* only:

* the contract version is one the platform understands;
* the payload answers the evaluation it claims to answer;
* the ruleset identity matches the pinned, usable ruleset version — not a
  different version, and not a version resolved by guesswork;
* every criterion exists in that version, at a strength that version permits;
* every applied criterion that the version says requires evidence cites some;
* every cited evidence record was part of the selection the request carried, so
  the engine cannot introduce evidence it was never authorized to see;
* the suggested classification is a real classification and is produced by a
  combination rule the version declares.

It never repairs a scientific value, never recomputes a strength, and never
decides a criterion or a classification itself. A payload that fails validation is
rejected with findings; the evaluation records the refusal rather than storing a
half-attributable result.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from app.domain.interpretation.entities import (
    ClassificationEvaluationRecord,
    RulesetRecord,
)
from app.domain.value_objects.enums import (
    Classification,
    CriterionDirection,
    CriterionStrength,
    ValidationSeverity,
)
from app.scientific.interpretation import (
    INTERPRETATION_CONTRACT_VERSION,
    MAX_INLINE_CRITERION_EVALUATIONS,
    ClassificationClaim,
    CriterionEvaluationClaim,
    InterpretationPayload,
)

#: Contract versions the platform will still read. Old payloads stay readable.
ACCEPTED_INTERPRETATION_CONTRACT_VERSIONS = frozenset({INTERPRETATION_CONTRACT_VERSION})


@dataclass(frozen=True, slots=True)
class InterpretationFinding:
    """Why something in a payload was refused or flagged."""

    code: str
    message: str
    severity: ValidationSeverity = ValidationSeverity.ERROR
    criterion_key: str | None = None
    detail: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class ValidatedInterpretation:
    """What may be stored, what was refused, and why."""

    criteria: tuple[CriterionEvaluationClaim, ...]
    classification: ClassificationClaim | None
    findings: tuple[InterpretationFinding, ...]
    payload_digest: str

    @property
    def is_rejected(self) -> bool:
        return any(
            finding.severity is ValidationSeverity.BLOCKING for finding in self.findings
        )

    @property
    def blocking_finding(self) -> InterpretationFinding | None:
        for finding in self.findings:
            if finding.severity is ValidationSeverity.BLOCKING:
                return finding
        return None


def payload_digest(payload: InterpretationPayload) -> str:
    """Stable digest of the attributable content of one payload."""
    content = {
        "contract_version": payload.contract_version,
        "evaluation_id": payload.evaluation_id,
        "ruleset_key": payload.ruleset.ruleset_key,
        "ruleset_version": payload.ruleset.ruleset_version,
        "criteria": sorted(
            (
                claim.criterion_key,
                claim.applied,
                claim.strength,
                tuple(sorted(claim.evidence_ids)),
            )
            for claim in payload.criteria
        ),
        "classification": payload.classification.classification
        if payload.classification
        else None,
        "combination_rule_key": payload.classification.combination_rule_key
        if payload.classification
        else None,
    }
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _enum_or_none(vocabulary, value: str | None):
    if value is None:
        return None
    try:
        return vocabulary(value)
    except ValueError:
        return None


def validate_interpretation_payload(
    payload: InterpretationPayload,
    *,
    evaluation: ClassificationEvaluationRecord,
    ruleset: RulesetRecord,
) -> ValidatedInterpretation:
    """Validate one engine payload against the evaluation and the pinned ruleset."""
    findings: list[InterpretationFinding] = []
    digest = payload_digest(payload)

    def blocking(code: str, message: str, **detail: Any) -> ValidatedInterpretation:
        findings.append(
            InterpretationFinding(
                code=code,
                message=message,
                severity=ValidationSeverity.BLOCKING,
                detail=detail or None,
            )
        )
        return ValidatedInterpretation(
            criteria=(), classification=None, findings=tuple(findings), payload_digest=digest
        )

    if payload.contract_version not in ACCEPTED_INTERPRETATION_CONTRACT_VERSIONS:
        return blocking(
            "contract_version_unsupported",
            "the payload uses an interpretation contract version this platform "
            "does not read",
            contract_version=payload.contract_version,
        )
    if payload.evaluation_id != evaluation.id:
        return blocking(
            "evaluation_mismatch",
            "the payload answers a different evaluation",
            claimed=payload.evaluation_id,
            expected=evaluation.id,
        )
    if not payload.ruleset.is_identified:
        return blocking(
            "ruleset_unidentified",
            "the payload does not name the ruleset version it was produced under",
        )
    if (
        payload.ruleset.ruleset_key != ruleset.ruleset_key
        or payload.ruleset.ruleset_version != ruleset.version
    ):
        # Reattributing a result to the requested ruleset would be a silent
        # scientific error, so this is a refusal rather than a correction.
        return blocking(
            "ruleset_mismatch",
            "the payload names a different ruleset version than the evaluation "
            "pinned",
            claimed=f"{payload.ruleset.ruleset_key}@{payload.ruleset.ruleset_version}",
            expected=f"{ruleset.ruleset_key}@{ruleset.version}",
        )
    if (
        payload.ruleset.configuration_digest
        and ruleset.configuration_digest
        and payload.ruleset.configuration_digest != ruleset.configuration_digest
    ):
        return blocking(
            "ruleset_configuration_mismatch",
            "the engine evaluated a different configuration of this ruleset version",
            claimed=payload.ruleset.configuration_digest,
            expected=ruleset.configuration_digest,
        )
    if len(payload.criteria) > MAX_INLINE_CRITERION_EVALUATIONS:
        return blocking(
            "payload_too_large",
            "the payload declares more criterion evaluations than one evaluation "
            "may carry",
            count=len(payload.criteria),
            limit=MAX_INLINE_CRITERION_EVALUATIONS,
        )

    authorized_evidence = set(evaluation.evidence_ids)
    accepted: list[CriterionEvaluationClaim] = []
    seen: set[str] = set()

    for claim in payload.criteria:
        definition = ruleset.criterion(claim.criterion_key)
        if definition is None:
            findings.append(
                InterpretationFinding(
                    code="criterion_unknown",
                    message="this ruleset version declares no such criterion",
                    criterion_key=claim.criterion_key,
                )
            )
            continue
        if claim.criterion_key in seen:
            findings.append(
                InterpretationFinding(
                    code="criterion_duplicated",
                    message="the payload evaluates the same criterion twice",
                    criterion_key=claim.criterion_key,
                )
            )
            continue
        strength = _enum_or_none(CriterionStrength, claim.strength)
        if strength is None:
            findings.append(
                InterpretationFinding(
                    code="strength_unknown",
                    message="the claimed strength is not a strength the platform knows",
                    criterion_key=claim.criterion_key,
                    detail={"strength": claim.strength},
                )
            )
            continue
        if claim.applied and not definition.permits(strength):
            # A modified strength must be one the ruleset version itself permits;
            # otherwise the result is not the version it claims to be.
            findings.append(
                InterpretationFinding(
                    code="strength_not_permitted",
                    message="this ruleset version does not permit that criterion at "
                    "that strength",
                    criterion_key=claim.criterion_key,
                    detail={
                        "strength": strength.value,
                        "permitted": [
                            item.value for item in definition.allowed_strengths
                        ],
                    },
                )
            )
            continue
        direction = _enum_or_none(CriterionDirection, claim.direction) or definition.direction
        if claim.applied and direction is not definition.direction:
            findings.append(
                InterpretationFinding(
                    code="direction_mismatch",
                    message="the claimed direction contradicts the criterion definition",
                    criterion_key=claim.criterion_key,
                    detail={
                        "claimed": direction.value,
                        "declared": definition.direction.value,
                    },
                )
            )
            continue
        unauthorized = [
            evidence_id
            for evidence_id in claim.evidence_ids
            if evidence_id not in authorized_evidence
        ]
        if unauthorized:
            findings.append(
                InterpretationFinding(
                    code="evidence_not_authorized",
                    message="the criterion cites evidence that was not part of this "
                    "evaluation's selection",
                    criterion_key=claim.criterion_key,
                    detail={"evidence_ids": unauthorized},
                )
            )
            continue
        if claim.applied and definition.requires_evidence and not claim.evidence_ids:
            findings.append(
                InterpretationFinding(
                    code="evidence_missing",
                    message="this criterion may not be applied without citing evidence",
                    criterion_key=claim.criterion_key,
                )
            )
            continue
        accepted.append(claim)
        seen.add(claim.criterion_key)

    classification = payload.classification
    if classification is not None:
        value = _enum_or_none(Classification, classification.classification)
        if value is None:
            return blocking(
                "classification_unknown",
                "the suggested classification is not a classification the platform "
                "knows",
                classification=classification.classification,
            )
        if classification.combination_rule_key is not None and (
            ruleset.combination_rule(classification.combination_rule_key) is None
        ):
            return blocking(
                "combination_rule_unknown",
                "the suggestion names a combination rule this ruleset version does "
                "not declare",
                combination_rule_key=classification.combination_rule_key,
            )
        if ruleset.declared_classifications and value not in ruleset.declared_classifications:
            return blocking(
                "classification_not_declared",
                "this ruleset version declares no combination rule producing that "
                "classification",
                classification=value.value,
            )
        unknown_applied = [
            key for key in classification.applied_criterion_keys if key not in seen
        ]
        if unknown_applied:
            findings.append(
                InterpretationFinding(
                    code="classification_criteria_unresolved",
                    message="the suggestion cites criteria that were not stored",
                    severity=ValidationSeverity.WARNING,
                    detail={"criterion_keys": unknown_applied},
                )
            )

    return ValidatedInterpretation(
        criteria=tuple(accepted),
        classification=classification,
        findings=tuple(findings),
        payload_digest=digest,
    )


__all__ = [
    "ACCEPTED_INTERPRETATION_CONTRACT_VERSIONS",
    "InterpretationFinding",
    "ValidatedInterpretation",
    "payload_digest",
    "validate_interpretation_payload",
]
