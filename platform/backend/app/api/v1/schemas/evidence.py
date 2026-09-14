"""Transport schemas for evidence sources, records, deliveries and conflicts.

Conventions carried over from the other schema modules: request payloads forbid
unknown fields, responses expose enum *values*, and nothing internal is serialized
to a tenant client.

Three things specific to this surface:

* **Identity always travels with its version and its two timestamps.** A record
  names its source key, source version, source release and the moment the platform
  retrieved it. Release time and retrieval time are separate fields and are never
  conflated.
* **Origin is explicit.** Every record says whether it was imported, retrieved,
  generated, entered by a person or evaluated by a person, so a curated note can
  never be read as something a database stated.
* **Disagreement is data.** Conflicts are returned as their own objects listing the
  records and sources that disagree. Nothing in this surface resolves them, and no
  field on a record says whether it satisfies an interpretation criterion — that is
  not this
  package's decision to represent.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.v1.schemas.common import ApiModel, Collection
from app.api.v1.schemas.tenancy import PageMeta

# --------------------------------------------------------------------------- #
# Sources                                                                     #
# --------------------------------------------------------------------------- #


class RegisterEvidenceSourcePayload(ApiModel):
    """Register one version of one evidence source."""

    source_key: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=255)
    category: str = Field(
        description=(
            "clinical_database | literature | population | functional | segregation"
            " | computational | curated_knowledge | internal_curation | other"
        )
    )
    provider: str | None = Field(default=None, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    release_label: str | None = Field(
        default=None,
        max_length=128,
        description="The source's own release identity, e.g. a monthly release name.",
    )
    released_at: datetime | None = None
    retrieved_at: datetime | None = None
    schema_version: str | None = Field(default=None, max_length=64)
    genome_assembly: str | None = Field(default=None, max_length=64)
    checksum_algorithm: str | None = Field(default=None, max_length=64)
    checksum_value: str | None = Field(default=None, max_length=256)
    size_bytes: int | None = Field(default=None, ge=0)
    supplies: list[str] = Field(
        min_length=1,
        description=(
            "Evidence categories this source is declared to supply. Ingestion"
            " refuses a record whose category the source never declared."
        ),
    )
    supplies_strength: bool = Field(
        default=False,
        description=(
            "Whether this source states evidence strength itself. When false, a"
            " delivered strength is refused rather than attributed to the source."
        ),
    )
    provenance: dict[str, object] | None = None
    licensing: dict[str, object] | None = None
    metadata: dict[str, object] | None = None


class TransitionEvidenceSourcePayload(ApiModel):
    state: str = Field(description="active | deprecated | retired | invalidated")
    reason: str | None = Field(default=None, max_length=1000)


class EvidenceSourceResponse(ApiModel):
    id: str
    source_key: str
    version: str
    display_name: str
    category: str
    state: str
    usable: bool
    provider: str | None
    description: str | None
    release_label: str | None
    released_at: datetime | None
    retrieved_at: datetime | None
    schema_version: str | None
    genome_assembly: str | None
    checksum_algorithm: str | None
    checksum_value: str | None
    size_bytes: int | None
    supplies: list[str]
    supplies_strength: bool
    licensing: dict[str, object]
    provenance: dict[str, object]
    registered_by: str | None
    activated_at: datetime | None
    deprecated_at: datetime | None
    retired_at: datetime | None
    invalidated_at: datetime | None
    invalidation_reason: str | None
    created_at: datetime | None


class EvidenceSourceCollection(Collection[EvidenceSourceResponse]):
    page: PageMeta


# --------------------------------------------------------------------------- #
# Records                                                                     #
# --------------------------------------------------------------------------- #


class EvidenceContextResponse(ApiModel):
    """Optional on purpose: population evidence has no disease context."""

    gene_symbol: str | None
    gene_identifier: str | None
    transcript_identifier: str | None
    condition_identifier: str | None
    condition_term: str | None
    inheritance: str | None


class EvidenceRecordResponse(ApiModel):
    id: str
    variant_id: str
    category: str
    origin: str
    state: str
    current: bool
    source_key: str | None
    source_version: str | None
    source_identifier: str | None
    source_released_at: datetime | None
    retrieved_at: datetime | None
    workspace_id: str | None
    project_id: str | None
    context: EvidenceContextResponse
    direction: str
    strength: str
    applicability: str
    summary: str | None
    rationale: str | None
    external_reference: str | None
    method: str | None
    evidence_key: str | None
    version_number: int
    supersedes_id: str | None
    superseded_by_id: str | None
    ingestion_batch_id: str | None
    scientific_execution_id: str | None
    #: The source's own values, verbatim. The platform does not reshape them.
    values: dict[str, object]
    provenance: dict[str, object]
    recorded_at: datetime | None
    created_by: str | None
    created_at: datetime | None


class EvidenceRecordCollection(Collection[EvidenceRecordResponse]):
    page: PageMeta


class EvidenceHistoryResponse(ApiModel):
    """Every version about one variant, superseded ones included."""

    variant_id: str
    records: list[EvidenceRecordResponse]


class EvidenceConflictResponse(ApiModel):
    """Reported disagreement. The platform states it and resolves nothing."""

    group_key: str
    variant_id: str
    category: str
    kind: str = Field(description="direction | strength | applicability")
    evidence_ids: list[str]
    source_keys: list[str]
    detail: dict[str, object]


class EvidenceConflictCollection(ApiModel):
    variant_id: str
    conflicts: list[EvidenceConflictResponse]


class RecordEvidencePayload(ApiModel):
    """Evidence a person is stating themselves."""

    variant_id: str = Field(min_length=1)
    category: str
    source_key: str = Field(min_length=1, max_length=128)
    source_version: str = Field(min_length=1, max_length=64)
    workspace_id: str | None = None
    project_id: str | None = None
    direction: str | None = None
    strength: str | None = None
    applicability: str | None = None
    summary: str | None = Field(default=None, max_length=4000)
    rationale: str | None = Field(default=None, max_length=8000)
    method: str | None = Field(default=None, max_length=255)
    external_reference: str | None = Field(default=None, max_length=1000)
    gene_symbol: str | None = Field(default=None, max_length=64)
    condition_identifier: str | None = Field(default=None, max_length=128)
    condition_term: str | None = Field(default=None, max_length=255)
    inheritance: str | None = Field(default=None, max_length=64)
    values: dict[str, object] | None = None


class WithdrawEvidencePayload(ApiModel):
    reason: str | None = Field(default=None, max_length=1000)


# --------------------------------------------------------------------------- #
# Deliveries                                                                  #
# --------------------------------------------------------------------------- #


class EvidenceClaimBody(ApiModel):
    """One evidence claim as delivered.

    Either ``variant_id`` or ``variant_identifier`` (the platform's canonical
    variant key) identifies the variant. Nothing is inferred from coordinates: the
    platform does not normalize, because normalization is a scientific operation
    that lives behind the scientific boundary.
    """

    category: str
    variant_id: str | None = None
    variant_identifier: str | None = None
    direction: str | None = None
    strength: str | None = None
    applicability: str | None = None
    source_identifier: str | None = Field(default=None, max_length=255)
    evidence_key: str | None = Field(
        default=None,
        max_length=255,
        description=(
            "Stable key for the same statement inside this source. A later"
            " delivery with the same key becomes a new version of that record."
        ),
    )
    summary: str | None = Field(default=None, max_length=4000)
    rationale: str | None = Field(default=None, max_length=8000)
    method: str | None = Field(default=None, max_length=255)
    external_reference: str | None = Field(default=None, max_length=1000)
    gene_symbol: str | None = Field(default=None, max_length=64)
    gene_identifier: str | None = Field(default=None, max_length=128)
    transcript_identifier: str | None = Field(default=None, max_length=128)
    condition_identifier: str | None = Field(default=None, max_length=128)
    condition_term: str | None = Field(default=None, max_length=255)
    inheritance: str | None = Field(default=None, max_length=64)
    source_released_at: datetime | None = None
    retrieved_at: datetime | None = None
    values: dict[str, object] | None = None


class EvidenceArtifactBody(ApiModel):
    """A delivery too large to inline, located in object storage."""

    storage_key: str = Field(min_length=1)
    record_count: int | None = Field(default=None, ge=0)
    checksum_algorithm: str | None = None
    checksum_value: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    format: str | None = None


class IngestEvidencePayloadBody(ApiModel):
    source_key: str = Field(min_length=1, max_length=128)
    source_version: str = Field(min_length=1, max_length=64)
    origin: str | None = Field(
        default=None, description="imported | retrieved | generated | human_entered"
    )
    contract_version: str = "1"
    release_label: str | None = None
    source_released_at: datetime | None = None
    retrieved_at: datetime | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    scientific_execution_id: str | None = None
    correlation_id: str | None = None
    is_development_payload: bool = False
    claims: list[EvidenceClaimBody] = Field(default_factory=list)
    artifact: EvidenceArtifactBody | None = None
    provenance: dict[str, object] | None = None


class EvidenceValidationFindingResponse(ApiModel):
    id: str
    code: str
    message: str
    severity: str
    evidence_id: str | None
    variant_id: str | None
    record_index: int | None
    detail: dict[str, object]
    created_at: datetime | None


class EvidenceValidationFindingCollection(Collection[EvidenceValidationFindingResponse]):
    page: PageMeta


class EvidenceIngestionBatchResponse(ApiModel):
    id: str
    source_key: str
    source_version: str
    state: str
    origin: str
    workspace_id: str | None
    project_id: str | None
    claimed_record_count: int
    stored_record_count: int
    superseded_record_count: int
    duplicate_record_count: int
    rejected_record_count: int
    retrieved_at: datetime | None
    source_released_at: datetime | None
    requested_by: str | None
    job_id: str | None
    correlation_id: str | None
    provenance: dict[str, object]
    failure_code: str | None
    failure_message: str | None
    completed_at: datetime | None
    created_at: datetime | None


class EvidenceIngestionBatchCollection(Collection[EvidenceIngestionBatchResponse]):
    page: PageMeta


class EvidenceIngestionResponse(ApiModel):
    batch: EvidenceIngestionBatchResponse
    #: True when this delivery had already been ingested and nothing was rewritten.
    redelivery: bool
    stored: list[EvidenceRecordResponse]
    superseded_evidence_ids: list[str]
    findings: list[EvidenceValidationFindingResponse]


__all__ = [
    "EvidenceArtifactBody",
    "EvidenceClaimBody",
    "EvidenceConflictCollection",
    "EvidenceConflictResponse",
    "EvidenceContextResponse",
    "EvidenceHistoryResponse",
    "EvidenceIngestionBatchCollection",
    "EvidenceIngestionBatchResponse",
    "EvidenceIngestionResponse",
    "EvidenceRecordCollection",
    "EvidenceRecordResponse",
    "EvidenceSourceCollection",
    "EvidenceSourceResponse",
    "EvidenceValidationFindingCollection",
    "EvidenceValidationFindingResponse",
    "IngestEvidencePayloadBody",
    "RecordEvidencePayload",
    "RegisterEvidenceSourcePayload",
    "TransitionEvidenceSourcePayload",
    "WithdrawEvidencePayload",
]
