"""The evidence payload contract.

Evidence reaches the platform either from an external retrieval performed behind
the existing scientific boundary, from an import, or from a human curator. In
every case it arrives as this structured payload: a source identity, a retrieval
context and a list of claims. The platform validates and stores the claims; it
never computes, scores, or classifies them, and it never accepts a command line,
script or arbitrary parameter set as part of a payload.

Volume rule: an inline payload is capped. A larger delivery references an
artifact in object storage, exactly like annotation payloads, so evidence never
travels as millions of rows inside an API request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.domain.value_objects.enums import (
    ChecksumAlgorithm,
    CriterionDirection,
    DataOrigin,
    EvidenceApplicability,
    EvidenceCategory,
    EvidenceStrength,
)

EVIDENCE_CONTRACT_VERSION = "1"

#: Above this, a delivery must be artifact-backed.
MAX_INLINE_EVIDENCE_RECORDS = 5_000


@dataclass(frozen=True, slots=True)
class EvidenceSourceIdentity:
    """Which registered source version produced a payload."""

    source_key: str
    version: str
    release_label: str | None = None
    released_at: datetime | None = None
    schema_version: str | None = None
    checksum_algorithm: ChecksumAlgorithm | None = None
    checksum_value: str | None = None


@dataclass(frozen=True, slots=True)
class EvidenceClaim:
    """One claimed piece of evidence, before the platform has validated it.

    Variant linkage is stated by identity, not by position: either the platform's
    own variant id, or a registered external identifier the platform can resolve.
    A claim the platform cannot link is recorded as a finding, never guessed.
    """

    category: EvidenceCategory
    variant_id: str | None = None
    variant_identifier: str | None = None
    variant_identifier_kind: str | None = None
    #: The source's own identifier for this statement (accession, PMID, record id).
    source_identifier: str | None = None
    #: Stable key for "the same statement" within the source across releases.
    evidence_key: str | None = None
    direction: CriterionDirection = CriterionDirection.NEUTRAL
    strength: EvidenceStrength = EvidenceStrength.NOT_APPLICABLE
    applicability: EvidenceApplicability = EvidenceApplicability.UNDETERMINED
    summary: str | None = None
    rationale: str | None = None
    method: str | None = None
    external_reference: str | None = None
    gene_symbol: str | None = None
    gene_identifier: str | None = None
    transcript_identifier: str | None = None
    condition_identifier: str | None = None
    condition_term: str | None = None
    inheritance: str | None = None
    source_released_at: datetime | None = None
    retrieved_at: datetime | None = None
    #: Values exactly as the source stated them. Preserved verbatim: the platform
    #: never normalizes, rounds or repairs a scientific value.
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EvidenceArtifactClaim:
    """A stored object holding a delivery too large to inline."""

    storage_key: str
    media_type: str | None = None
    record_count: int | None = None
    size_bytes: int | None = None
    checksum_algorithm: ChecksumAlgorithm | None = None
    checksum_value: str | None = None


@dataclass(frozen=True, slots=True)
class EvidencePayload:
    """A complete evidence delivery."""

    source: EvidenceSourceIdentity
    contract_version: str = EVIDENCE_CONTRACT_VERSION
    origin: DataOrigin = DataOrigin.RETRIEVED
    retrieved_at: datetime | None = None
    claims: tuple[EvidenceClaim, ...] = ()
    artifact: EvidenceArtifactClaim | None = None
    scientific_execution_id: str | None = None
    correlation_id: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    #: Set by the development adapter only; surfaced in the UI so a development
    #: payload can never be mistaken for real evidence.
    is_development_payload: bool = False


__all__ = [
    "EVIDENCE_CONTRACT_VERSION",
    "MAX_INLINE_EVIDENCE_RECORDS",
    "EvidenceArtifactClaim",
    "EvidenceClaim",
    "EvidencePayload",
    "EvidenceSourceIdentity",
]
