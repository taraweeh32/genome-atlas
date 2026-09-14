"""Domain records for the evidence layer.

Versioning rule, stated once: an evidence record is versioned per
``(variant, source key, evidence key)``. A newer delivery from the *same* source
about the *same* evidence key creates a new version and marks the previous one
superseded — the superseded row stays readable, so an interpretation that cited
it remains reproducible. Evidence from a *different* source is never superseded
by another source: that is disagreement, and disagreement is retained.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from app.domain.errors import ConflictError, ValidationError
from app.domain.resource_lifecycle import (
    USABLE_RESOURCE_STATES,
    check_resource_transition,
)
from app.domain.value_objects.enums import (
    CriterionDirection,
    DataOrigin,
    EvidenceApplicability,
    EvidenceCategory,
    EvidenceConflictKind,
    EvidenceIngestionState,
    EvidenceRecordState,
    EvidenceSourceCategory,
    EvidenceStrength,
    ScientificResourceState,
    ValidationSeverity,
)

#: Origins that mean "a human stated this", as opposed to a source delivering it.
HUMAN_ORIGINS: frozenset[DataOrigin] = frozenset(
    {DataOrigin.HUMAN_ENTERED, DataOrigin.HUMAN_EVALUATED}
)


def content_digest(payload: dict[str, Any]) -> str:
    """Stable digest of one evidence claim, used for idempotent ingestion."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class EvidenceSourceRecord:
    """One registered version of one evidence source.

    Identity is ``(source_key, version)``. The category says what role the source
    plays; it never privileges a particular database. Registering a correction
    means registering a new version.
    """

    id: str
    source_key: str
    version: str
    display_name: str
    category: EvidenceSourceCategory
    state: ScientificResourceState = ScientificResourceState.REGISTERED
    provider: str | None = None
    description: str | None = None
    #: The source's own release identity, distinct from the platform's version
    #: string: two platform registrations may both point at release "2024-05".
    release_label: str | None = None
    released_at: datetime | None = None
    #: When the platform retrieved this release. Retrieval time is not release
    #: time and the two are never conflated.
    retrieved_at: datetime | None = None
    schema_version: str | None = None
    genome_assembly: str | None = None
    checksum_algorithm: str | None = None
    checksum_value: str | None = None
    size_bytes: int | None = None
    #: Evidence categories this source is declared to supply. Ingestion refuses a
    #: record whose category the source never declared.
    supplies: tuple[EvidenceCategory, ...] = ()
    #: Whether records from this source may carry a strength value at all. A
    #: population resource supplies frequencies, not strengths.
    supplies_strength: bool = False
    provenance: dict[str, Any] = field(default_factory=dict)
    licensing: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    registered_by: str | None = None
    activated_at: datetime | None = None
    deprecated_at: datetime | None = None
    retired_at: datetime | None = None
    invalidated_at: datetime | None = None
    invalidation_reason: str | None = None
    created_at: datetime | None = None
    record_version: int = 1

    def __post_init__(self) -> None:
        if not self.source_key.strip():
            raise ValidationError(
                "an evidence source requires a key", details={"field": "source_key"}
            )
        if not self.version.strip():
            raise ValidationError(
                "an evidence source requires a version", details={"field": "version"}
            )

    @property
    def is_usable(self) -> bool:
        return self.state in USABLE_RESOURCE_STATES

    def supplies_category(self, category: EvidenceCategory) -> bool:
        return not self.supplies or category in self.supplies

    def transition_to(
        self, state: ScientificResourceState, *, at: datetime, reason: str | None = None
    ) -> EvidenceSourceRecord:
        if state is self.state:
            return self
        check_resource_transition(
            current=self.state, target=state, resource_kind="evidence source"
        )
        stamps: dict[str, Any] = {}
        if state is ScientificResourceState.ACTIVE:
            stamps["activated_at"] = at
        elif state is ScientificResourceState.DEPRECATED:
            stamps["deprecated_at"] = at
        elif state is ScientificResourceState.RETIRED:
            stamps["retired_at"] = at
        elif state is ScientificResourceState.INVALIDATED:
            stamps["invalidated_at"] = at
            stamps["invalidation_reason"] = reason
        return replace(self, state=state, **stamps)


@dataclass(frozen=True, slots=True)
class EvidenceContext:
    """The scientific context an evidence record applies to.

    Optional on purpose: population evidence has no disease context, and claiming
    one would be an invention.
    """

    gene_symbol: str | None = None
    gene_identifier: str | None = None
    transcript_identifier: str | None = None
    condition_identifier: str | None = None
    condition_term: str | None = None
    inheritance: str | None = None

    def key_part(self) -> str:
        return "|".join(
            part or ""
            for part in (
                self.gene_symbol,
                self.gene_identifier,
                self.condition_identifier,
                self.inheritance,
            )
        )


@dataclass(frozen=True, slots=True)
class EvidenceRecord:
    """One discrete piece of evidence about one variant."""

    id: str
    variant_id: str
    category: EvidenceCategory
    origin: DataOrigin
    #: Identity of what supplied it. A source key and version are mandatory for
    #: anything not entered by a human, because evidence whose release is unknown
    #: cannot be reproduced.
    source_key: str | None = None
    source_version: str | None = None
    source_resource_id: str | None = None
    source_identifier: str | None = None
    source_released_at: datetime | None = None
    retrieved_at: datetime | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    context: EvidenceContext = field(default_factory=EvidenceContext)
    direction: CriterionDirection = CriterionDirection.NEUTRAL
    strength: EvidenceStrength = EvidenceStrength.NOT_APPLICABLE
    applicability: EvidenceApplicability = EvidenceApplicability.UNDETERMINED
    state: EvidenceRecordState = EvidenceRecordState.RECORDED
    summary: str | None = None
    rationale: str | None = None
    external_reference: str | None = None
    #: How the value was obtained (assay, curation protocol, computation name).
    #: Free text supplied by the source or curator; never inferred.
    method: str | None = None
    #: Stable key for "the same statement" inside one source, which is what makes
    #: a later delivery a new version instead of a duplicate.
    evidence_key: str | None = None
    version_number: int = 1
    supersedes_id: str | None = None
    superseded_by_id: str | None = None
    ingestion_batch_id: str | None = None
    payload_digest: str | None = None
    clinical_assertion_id: str | None = None
    scientific_execution_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    recorded_at: datetime | None = None
    created_by: str | None = None
    created_at: datetime | None = None
    record_version: int = 1

    def __post_init__(self) -> None:
        if self.origin not in HUMAN_ORIGINS and not (self.source_key or "").strip():
            raise ValidationError(
                "evidence that was not entered by a person must name its source",
                details={"field": "source_key", "origin": self.origin.value},
            )
        if self.origin not in HUMAN_ORIGINS and not (self.source_version or "").strip():
            raise ValidationError(
                "evidence must name the source version it came from",
                details={"field": "source_version"},
            )

    @property
    def is_current(self) -> bool:
        return self.state in {
            EvidenceRecordState.RECORDED,
            EvidenceRecordState.AVAILABLE,
        }

    @property
    def lineage_key(self) -> str:
        """What a new version of *this* statement would replace."""
        return "::".join(
            (
                self.variant_id,
                self.source_key or f"human:{self.created_by or 'unknown'}",
                self.evidence_key or self.source_identifier or self.payload_digest or self.id,
            )
        )

    @property
    def conflict_group_key(self) -> str:
        """Records that speak to the same question, whoever supplied them."""
        return f"{self.variant_id}::{self.category.value}::{self.context.key_part()}"

    def supersede(self, *, by_id: str, at: datetime) -> EvidenceRecord:
        if self.state is EvidenceRecordState.REJECTED:
            raise ConflictError(
                "rejected evidence cannot be superseded",
                details={"evidence_id": self.id},
            )
        return replace(
            self,
            state=EvidenceRecordState.SUPERSEDED,
            superseded_by_id=by_id,
            recorded_at=self.recorded_at or at,
        )

    def withdraw(self, *, at: datetime, reason: str | None = None) -> EvidenceRecord:
        """Mark evidence withdrawn by its source or curator. Nothing is deleted."""
        if self.state is EvidenceRecordState.WITHDRAWN:
            return self
        provenance = dict(self.provenance)
        provenance["withdrawn_at"] = at
        if reason:
            provenance["withdrawal_reason"] = reason
        return replace(
            self, state=EvidenceRecordState.WITHDRAWN, provenance=provenance
        )

    def make_available(self) -> EvidenceRecord:
        if self.state is not EvidenceRecordState.RECORDED:
            return self
        return replace(self, state=EvidenceRecordState.AVAILABLE)


@dataclass(frozen=True, slots=True)
class EvidenceConflict:
    """Disagreement between retained evidence records.

    Reported, never resolved: the platform states that two sources disagree and
    leaves the scientific judgement to the interpretation layer and to people.
    """

    group_key: str
    variant_id: str
    category: EvidenceCategory
    kind: EvidenceConflictKind
    evidence_ids: tuple[str, ...]
    source_keys: tuple[str, ...]
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvidenceValidationFinding:
    """Why one claim in a batch was refused, downgraded or flagged."""

    id: str
    ingestion_batch_id: str
    code: str
    message: str
    severity: ValidationSeverity = ValidationSeverity.ERROR
    evidence_id: str | None = None
    variant_id: str | None = None
    record_index: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EvidenceIngestionBatch:
    """One validated delivery of evidence records.

    The batch is the unit of idempotency: redelivering the same payload digest
    returns the original batch instead of writing the evidence twice.
    """

    id: str
    source_key: str
    source_version: str
    payload_digest: str
    state: EvidenceIngestionState = EvidenceIngestionState.REQUESTED
    source_resource_id: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    origin: DataOrigin = DataOrigin.RETRIEVED
    #: Where the delivery came from, when it is artifact-backed rather than inline.
    file_artifact_id: str | None = None
    claimed_record_count: int = 0
    stored_record_count: int = 0
    superseded_record_count: int = 0
    duplicate_record_count: int = 0
    rejected_record_count: int = 0
    retrieved_at: datetime | None = None
    source_released_at: datetime | None = None
    requested_by: str | None = None
    service_account_id: str | None = None
    job_id: str | None = None
    correlation_id: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    failure_code: str | None = None
    failure_message: str | None = None
    completed_at: datetime | None = None
    created_at: datetime | None = None
    record_version: int = 1

    def completed(
        self,
        *,
        state: EvidenceIngestionState,
        at: datetime,
        stored: int,
        superseded: int,
        duplicates: int,
        rejected: int,
    ) -> EvidenceIngestionBatch:
        return replace(
            self,
            state=state,
            stored_record_count=stored,
            superseded_record_count=superseded,
            duplicate_record_count=duplicates,
            rejected_record_count=rejected,
            completed_at=at,
        )


__all__ = [
    "HUMAN_ORIGINS",
    "EvidenceConflict",
    "EvidenceContext",
    "EvidenceIngestionBatch",
    "EvidenceRecord",
    "EvidenceSourceRecord",
    "EvidenceValidationFinding",
    "content_digest",
]
