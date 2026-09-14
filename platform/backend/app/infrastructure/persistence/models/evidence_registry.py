"""Evidence ingestion bookkeeping.

Deliberately *not* here:

* the evidence sources themselves — a registered evidence source version is a row
  in ``scientific_resources`` (kind ``evidence_resource``), governed by the same
  lifecycle as genomes, engines, annotation resources and rulesets;
* the evidence records — those are ``evidence_items`` rows from Package 2, widened
  by this package rather than replaced. No second evidence model exists.

What is added is the delivery record — one validated batch, idempotent by payload
digest — and the findings that explain why individual claims were refused.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import (
    DataOrigin,
    EvidenceIngestionState,
    ValidationSeverity,
)
from app.infrastructure.persistence.base import (
    Base,
    ConcurrencyMixin,
    TimestampMixin,
    fk_column,
    id_column,
    json_column,
    state_check,
)


class EvidenceIngestionBatchRow(Base, TimestampMixin, ConcurrencyMixin):
    """One validated delivery of evidence records.

    ``uq_evidence_ingestion_batches_source_key_payload_digest`` is what makes
    ingestion idempotent: redelivering an identical payload finds the original
    batch instead of writing the evidence a second time.
    """

    __tablename__ = "evidence_ingestion_batches"
    __table_args__ = (
        UniqueConstraint(
            "source_key",
            "payload_digest",
            name="uq_evidence_ingestion_batches_source_key_payload_digest",
        ),
        state_check("state", EvidenceIngestionState, "state_valid"),
        state_check("origin", DataOrigin, "origin_valid"),
        Index("ix_evidence_ingestion_batches_workspace_id_state", "workspace_id", "state"),
        Index("ix_evidence_ingestion_batches_source_key_version", "source_key", "source_version"),
    )

    id: Mapped[str] = id_column()
    source_key: Mapped[str] = mapped_column(String(255), nullable=False)
    source_version: Mapped[str] = mapped_column(String(128), nullable=False)
    source_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    payload_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=EvidenceIngestionState.REQUESTED.value
    )
    #: Imported / retrieved / generated / human entered stays distinguishable.
    origin: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=DataOrigin.RETRIEVED.value
    )
    #: Tenancy of the delivery. Platform-wide evidence leaves both null.
    workspace_id: Mapped[str | None] = fk_column("app.workspaces.id", nullable=True)
    project_id: Mapped[str | None] = fk_column("app.projects.id", nullable=True)
    #: Set when the delivery was artifact-backed rather than inline.
    file_artifact_id: Mapped[str | None] = fk_column("app.file_artifacts.id", nullable=True)
    claimed_record_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    stored_record_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    superseded_record_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    duplicate_record_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    rejected_record_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: Retrieval time and the source's own release time are separate facts.
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    requested_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    service_account_id: Mapped[str | None] = fk_column("app.service_accounts.id", nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provenance: Mapped[dict | None] = json_column()
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvidenceValidationFindingRow(Base, TimestampMixin):
    """Why one claim in a batch was refused, downgraded or flagged.

    Findings are kept even for a fully rejected delivery: a refusal must stay
    explainable, and a silent drop would be indistinguishable from evidence that
    never existed.
    """

    __tablename__ = "evidence_validation_findings"
    __table_args__ = (
        state_check("severity", ValidationSeverity, "severity_valid"),
        Index("ix_evidence_validation_findings_code", "code"),
    )

    id: Mapped[str] = id_column()
    ingestion_batch_id: Mapped[str] = fk_column(
        "app.evidence_ingestion_batches.id", ondelete="CASCADE"
    )
    code: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ValidationSeverity.ERROR.value
    )
    evidence_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    variant_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    record_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    detail: Mapped[dict | None] = json_column()


__all__ = ["EvidenceIngestionBatchRow", "EvidenceValidationFindingRow"]
