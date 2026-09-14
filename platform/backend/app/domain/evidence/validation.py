"""Validating evidence claims and reporting disagreement.

Pure functions. Two responsibilities, kept apart:

* **Validation** — does this claim carry the identity, source agreement and
  context it needs to be stored and later reproduced? A claim that fails is
  refused with a finding; it is never silently repaired and its scientific values
  are never adjusted.
* **Conflict reporting** — which retained records disagree? Computed on read from
  stored rows, so nothing is overwritten and no source wins.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.domain.evidence.entities import (
    HUMAN_ORIGINS,
    EvidenceConflict,
    EvidenceRecord,
    EvidenceSourceRecord,
)
from app.domain.value_objects.enums import (
    CriterionDirection,
    DataOrigin,
    EvidenceApplicability,
    EvidenceConflictKind,
    EvidenceStrength,
    ValidationSeverity,
)
from app.scientific.evidence import EvidenceClaim, EvidencePayload

#: Directions that actually assert something opposed to one another.
_OPPOSED = (CriterionDirection.PATHOGENIC, CriterionDirection.BENIGN)


@dataclass(frozen=True, slots=True)
class ClaimIssue:
    """One reason a claim cannot be stored as delivered."""

    code: str
    message: str
    severity: ValidationSeverity = ValidationSeverity.ERROR
    record_index: int | None = None
    detail: dict[str, object] | None = None

    @property
    def blocks_record(self) -> bool:
        return self.severity in {ValidationSeverity.ERROR, ValidationSeverity.BLOCKING}


def validate_payload_identity(
    payload: EvidencePayload, source: EvidenceSourceRecord
) -> tuple[ClaimIssue, ...]:
    """Whole-payload checks: contract, source identity, usability, volume.

    A mismatch here invalidates the delivery rather than individual records: if
    the platform cannot agree with the sender about which source release this is,
    nothing in it can be trusted to a version.
    """
    issues: list[ClaimIssue] = []
    if payload.contract_version != "1":
        issues.append(
            ClaimIssue(
                code="evidence.contract_version_unsupported",
                message="this evidence contract version is not supported",
                severity=ValidationSeverity.BLOCKING,
                detail={"contract_version": payload.contract_version},
            )
        )
    if payload.source.source_key != source.source_key:
        issues.append(
            ClaimIssue(
                code="evidence.source_mismatch",
                message="the payload names a different evidence source",
                severity=ValidationSeverity.BLOCKING,
                detail={"expected": source.source_key, "received": payload.source.source_key},
            )
        )
    if payload.source.version != source.version:
        issues.append(
            ClaimIssue(
                code="evidence.source_version_mismatch",
                message="the payload names a different source version",
                severity=ValidationSeverity.BLOCKING,
                detail={"expected": source.version, "received": payload.source.version},
            )
        )
    if not source.is_usable:
        issues.append(
            ClaimIssue(
                code="evidence.source_not_usable",
                message="this evidence source version may not be used",
                severity=ValidationSeverity.BLOCKING,
                detail={"state": source.state.value},
            )
        )
    if payload.origin not in HUMAN_ORIGINS and payload.retrieved_at is None:
        issues.append(
            ClaimIssue(
                code="evidence.retrieval_time_missing",
                message="a retrieved or imported delivery must state when it was retrieved",
                severity=ValidationSeverity.BLOCKING,
            )
        )
    if not payload.claims and payload.artifact is None:
        issues.append(
            ClaimIssue(
                code="evidence.payload_empty",
                message="the delivery contains neither claims nor an artifact",
                severity=ValidationSeverity.BLOCKING,
            )
        )
    return tuple(issues)


def validate_claim(
    claim: EvidenceClaim,
    *,
    source: EvidenceSourceRecord,
    index: int,
    origin: DataOrigin,
) -> tuple[ClaimIssue, ...]:
    """Per-claim checks. Linkage resolution itself happens in the use case."""
    issues: list[ClaimIssue] = []
    if not (claim.variant_id or claim.variant_identifier):
        issues.append(
            ClaimIssue(
                code="evidence.variant_linkage_missing",
                message="a claim must identify the variant it is about",
                record_index=index,
            )
        )
    if not source.supplies_category(claim.category):
        issues.append(
            ClaimIssue(
                code="evidence.category_not_declared",
                message="this source is not registered as supplying that evidence category",
                record_index=index,
                detail={"category": claim.category.value},
            )
        )
    if (
        claim.strength is not EvidenceStrength.NOT_APPLICABLE
        and not source.supplies_strength
        and origin not in HUMAN_ORIGINS
    ):
        # A source that was never registered as stating strength must not have a
        # strength attributed to it; that would be the platform inventing weight.
        issues.append(
            ClaimIssue(
                code="evidence.strength_not_supplied_by_source",
                message="this source is not registered as stating evidence strength",
                record_index=index,
                detail={"strength": claim.strength.value},
            )
        )
    if origin not in HUMAN_ORIGINS and not (
        claim.source_identifier or claim.evidence_key
    ):
        issues.append(
            ClaimIssue(
                code="evidence.source_identifier_missing",
                message="evidence from a source must carry the source's own identifier",
                severity=ValidationSeverity.WARNING,
                record_index=index,
            )
        )
    return tuple(issues)


def detect_conflicts(
    records: Iterable[EvidenceRecord],
) -> tuple[EvidenceConflict, ...]:
    """Group current records by the question they answer and report disagreement.

    Only records that are still current participate: a superseded version is
    history, not a live disagreement. Records from the same source *and* the same
    lineage never conflict with themselves.
    """
    groups: dict[str, list[EvidenceRecord]] = defaultdict(list)
    for record in records:
        if record.is_current:
            groups[record.conflict_group_key].append(record)

    conflicts: list[EvidenceConflict] = []
    for group_key, members in sorted(groups.items()):
        if len(members) < 2:
            continue
        conflicts.extend(_group_conflicts(group_key, members))
    return tuple(conflicts)


def _group_conflicts(
    group_key: str, members: Sequence[EvidenceRecord]
) -> tuple[EvidenceConflict, ...]:
    found: list[EvidenceConflict] = []
    first = members[0]
    directions = {member.direction for member in members if member.direction in _OPPOSED}
    if len(directions) > 1:
        found.append(
            EvidenceConflict(
                group_key=group_key,
                variant_id=first.variant_id,
                category=first.category,
                kind=EvidenceConflictKind.DIRECTION,
                evidence_ids=tuple(member.id for member in members),
                source_keys=tuple(
                    sorted({member.source_key or "human" for member in members})
                ),
                detail={"directions": sorted(item.value for item in directions)},
            )
        )
    strengths = {
        member.strength
        for member in members
        if member.strength is not EvidenceStrength.NOT_APPLICABLE
    }
    if len(strengths) > 1:
        found.append(
            EvidenceConflict(
                group_key=group_key,
                variant_id=first.variant_id,
                category=first.category,
                kind=EvidenceConflictKind.STRENGTH,
                evidence_ids=tuple(member.id for member in members),
                source_keys=tuple(
                    sorted({member.source_key or "human" for member in members})
                ),
                detail={"strengths": sorted(item.value for item in strengths)},
            )
        )
    applicability = {
        member.applicability
        for member in members
        if member.applicability is not EvidenceApplicability.UNDETERMINED
    }
    if len(applicability) > 1:
        found.append(
            EvidenceConflict(
                group_key=group_key,
                variant_id=first.variant_id,
                category=first.category,
                kind=EvidenceConflictKind.APPLICABILITY,
                evidence_ids=tuple(member.id for member in members),
                source_keys=tuple(
                    sorted({member.source_key or "human" for member in members})
                ),
                detail={"applicability": sorted(item.value for item in applicability)},
            )
        )
    return tuple(found)


__all__ = ["ClaimIssue", "detect_conflicts", "validate_claim", "validate_payload_identity"]
