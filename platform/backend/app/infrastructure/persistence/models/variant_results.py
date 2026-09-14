"""Package 6 tables: representation history, membership, artifacts, ingestion.

Four tables, each earning its place rather than being folded into a JSONB blob on
an existing row:

``variant_representations``
    The normalization history. One row per attempt, including failed and
    unavailable attempts, so "why has this record no canonical form?" is
    answerable from the database instead of from a log file.
``dataset_version_variants``
    Membership of a canonical variant in an immutable dataset version. Carries
    ``workspace_id`` so a membership read is authorizable without joining
    observations, and so tenant isolation does not depend on the variant table —
    canonical variants are shared reference data and have no tenant of their own.
``result_artifacts``
    One stored object per result set, with its checksum and column contract.
    Result rows themselves never enter PostgreSQL.
``result_ingestion_requests``
    The ingestion workflow, separate from the result surface it produces, with
    the idempotency key that makes engine redelivery safe.

Existing Package 2 tables (``variants``, ``variant_source_representations``,
``variant_observations``, ``variant_annotations``, ``population_frequency_observations``,
``clinical_assertions``, ``result_sets``) are extended by migration 0006 rather
than redefined here; the columns added there appear on those models directly.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import (
    ChecksumAlgorithm,
    DataOrigin,
    NormalizationState,
    ResultArtifactFormat,
    ResultArtifactKind,
    ResultArtifactState,
    ResultCompleteness,
    ResultIngestionState,
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


class VariantRepresentation(Base, TimestampMixin):
    """One normalization/representation attempt. Append-only."""

    __tablename__ = "variant_representations"
    __table_args__ = (
        # An engine version produces at most one representation per source record.
        # Re-running the *same* version is idempotent; a new version is a new row.
        UniqueConstraint(
            "source_representation_id",
            "normalization_version",
            name="uq_variant_representations_source_representation_id_version",
        ),
        state_check("normalization_state", NormalizationState, "normalization_state_valid"),
        state_check("origin", DataOrigin, "origin_valid"),
    )

    id: Mapped[str] = id_column()
    #: Null when the attempt produced no canonical variant. That is the point.
    variant_id: Mapped[str | None] = fk_column("app.variants.id", nullable=True)
    source_representation_id: Mapped[str | None] = fk_column(
        "app.variant_source_representations.id", nullable=True
    )
    reference_genome_resource_id: Mapped[str] = fk_column("app.scientific_resources.id")
    contig: Mapped[str] = mapped_column(String(64), nullable=False)
    source_contig: Mapped[str | None] = mapped_column(String(64), nullable=True)
    position: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    end_position: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reference_allele: Mapped[str | None] = mapped_column(Text, nullable=True)
    alternate_allele: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalization_state: Mapped[str] = mapped_column(String(64), nullable=False)
    normalization_version: Mapped[str] = mapped_column(String(128), nullable=False)
    normalization_engine_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    scientific_execution_id: Mapped[str | None] = fk_column(
        "app.scientific_executions.id", nullable=True
    )
    origin: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=DataOrigin.GENERATED.value
    )
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict | None] = json_column()
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DatasetVersionVariant(Base, TimestampMixin):
    """Membership of a canonical variant in an immutable dataset version."""

    __tablename__ = "dataset_version_variants"
    __table_args__ = (
        UniqueConstraint(
            "dataset_version_id",
            "variant_id",
            name="uq_dataset_version_variants_dataset_version_id_variant_id",
        ),
    )

    id: Mapped[str] = id_column()
    dataset_version_id: Mapped[str] = fk_column("app.dataset_versions.id")
    variant_id: Mapped[str] = fk_column("app.variants.id")
    #: Denormalized tenant anchor: authorization must never depend on the
    #: (tenant-less) variant row.
    workspace_id: Mapped[str] = fk_column("app.workspaces.id")
    source_representation_id: Mapped[str | None] = fk_column(
        "app.variant_source_representations.id", nullable=True
    )


class ResultArtifact(Base, TimestampMixin, ConcurrencyMixin):
    """One stored artifact belonging to a result set."""

    __tablename__ = "result_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "result_set_id", "artifact_key", name="uq_result_artifacts_result_set_id_artifact_key"
        ),
        state_check("state", ResultArtifactState, "state_valid"),
        state_check("kind", ResultArtifactKind, "kind_valid"),
        state_check("artifact_format", ResultArtifactFormat, "artifact_format_valid"),
        state_check("checksum_algorithm", ChecksumAlgorithm, "checksum_algorithm_valid"),
        Index("ix_result_artifacts_state", "state"),
    )

    id: Mapped[str] = id_column()
    result_set_id: Mapped[str] = fk_column("app.result_sets.id")
    artifact_key: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_format: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ResultArtifactState.REGISTERED.value
    )
    storage_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_artifact_id: Mapped[str | None] = fk_column("app.file_artifacts.id", nullable=True)
    analytical_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    scientific_artifact_id: Mapped[str | None] = fk_column(
        "app.scientific_artifacts.id", nullable=True
    )
    media_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum_algorithm: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checksum_value: Mapped[str | None] = mapped_column(String(256), nullable=True)
    row_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    column_schema: Mapped[dict | None] = json_column()
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict | None] = json_column()
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ResultIngestionRequest(Base, TimestampMixin, ConcurrencyMixin):
    """One attempt to bring an engine's output into the platform."""

    __tablename__ = "result_ingestion_requests"
    __table_args__ = (
        # The idempotency guarantee. A redelivered payload resolves to this row
        # instead of creating a second result set.
        UniqueConstraint(
            "idempotency_key", name="uq_result_ingestion_requests_idempotency_key"
        ),
        state_check("state", ResultIngestionState, "state_valid"),
        state_check("declared_completeness", ResultCompleteness, "declared_completeness_valid"),
        Index("ix_result_ingestion_requests_workspace_id_state", "workspace_id", "state"),
        Index("ix_result_ingestion_requests_correlation_id", "correlation_id"),
    )

    id: Mapped[str] = id_column()
    workspace_id: Mapped[str] = fk_column("app.workspaces.id")
    project_id: Mapped[str] = fk_column("app.projects.id")
    analysis_execution_id: Mapped[str] = fk_column("app.analysis_executions.id")
    scientific_execution_id: Mapped[str | None] = fk_column(
        "app.scientific_executions.id", nullable=True
    )
    result_set_id: Mapped[str | None] = fk_column("app.result_sets.id", nullable=True)
    result_key: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ResultIngestionState.RECEIVED.value
    )
    declared_completeness: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ResultCompleteness.UNKNOWN.value
    )
    declared_row_count: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    artifact_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    engine_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    engine_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: Who offered the payload: a human actor, or a service account acting for the
    #: scientific subsystem. Kept apart so an automated ingestion is never
    #: attributed to a person.
    submitted_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    service_account_id: Mapped[str | None] = fk_column(
        "app.service_accounts.id", nullable=True
    )
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_development_payload: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    findings: Mapped[dict | None] = json_column()
    rejection_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    rejection_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "DatasetVersionVariant",
    "ResultArtifact",
    "ResultIngestionRequest",
    "VariantRepresentation",
]
