"""Scientific resource registry and scientific execution persistence.

This module stores *identities and governance metadata only*. No scientific
algorithm, reference data, annotation resource content or ruleset logic exists
here or anywhere else in the application tree — the compute subsystem is
independently deployable and is not implemented inside the normal application
domain.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import (
    ChecksumAlgorithm,
    ScientificExecutionState,
    ScientificResourceKind,
    ScientificResourceState,
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


class ScientificResource(Base, TimestampMixin, ConcurrencyMixin):
    """A registered, versioned scientific resource (genome, engine, ruleset, ...)."""

    __tablename__ = "scientific_resources"
    __table_args__ = (
        UniqueConstraint(
            "kind", "resource_key", "version",
            name="uq_scientific_resources_kind_resource_key_version",
        ),
        state_check("kind", ScientificResourceKind, "kind_valid"),
        state_check("state", ScientificResourceState, "state_valid"),
        state_check("checksum_algorithm", ChecksumAlgorithm, "checksum_algorithm_valid"),
        Index("ix_scientific_resources_kind_state", "kind", "state"),
    )

    id: Mapped[str] = id_column()
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Stable identity within its kind, e.g. ``GRCh38`` or ``acmg-2015``.
    resource_key: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ScientificResourceState.REGISTERED.value
    )
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deprecated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    checksum_algorithm: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checksum_value: Mapped[str | None] = mapped_column(String(256), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    #: Provenance of the resource itself: upstream source, build, retrieval.
    provenance: Mapped[dict | None] = json_column()
    licensing: Mapped[dict | None] = json_column()
    #: Compatibility declarations against other registered resources.
    compatibility: Mapped[dict | None] = json_column()
    metadata_json: Mapped[dict | None] = json_column()
    registered_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)


class ScientificResourceCompatibility(Base, TimestampMixin):
    """Explicit pairwise compatibility between registered resources."""

    __tablename__ = "scientific_resource_compatibility"
    __table_args__ = (
        UniqueConstraint(
            "resource_id", "compatible_resource_id",
            name="uq_scientific_resource_compatibility_resource_id_compatible",
        ),
    )

    id: Mapped[str] = id_column()
    resource_id: Mapped[str] = fk_column("app.scientific_resources.id", ondelete="CASCADE")
    compatible_resource_id: Mapped[str] = fk_column("app.scientific_resources.id")
    #: ``required`` | ``compatible`` | ``incompatible``.
    relation: Mapped[str] = mapped_column(String(64), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ScientificExecution(Base, TimestampMixin):
    """Immutable record of one execution inside the scientific subsystem."""

    __tablename__ = "scientific_executions"
    __table_args__ = (
        state_check("state", ScientificExecutionState, "state_valid"),
        Index("ix_scientific_executions_analysis_execution_id", "analysis_execution_id"),
        Index("ix_scientific_executions_correlation_id", "correlation_id"),
        Index("ix_scientific_executions_state_submitted_at", "state", "submitted_at"),
    )

    id: Mapped[str] = id_column()
    analysis_execution_id: Mapped[str | None] = fk_column(
        "app.analysis_executions.id", nullable=True
    )
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Identity assigned by the scientific subsystem.
    external_execution_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    capability_key: Mapped[str] = mapped_column(String(128), nullable=False)
    capability_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    engine_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    engine_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    environment_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    environment_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    container_image_digest: Mapped[str | None] = mapped_column(String(255), nullable=True)
    node_identity: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reference_genome_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    ruleset_resource_id: Mapped[str | None] = fk_column(
        "app.scientific_resources.id", nullable=True
    )
    #: Every other resource the execution consumed.
    resource_identities: Mapped[dict | None] = json_column()
    parameters: Mapped[dict | None] = json_column()
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ScientificExecutionState.SUBMITTED.value
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance_manifest_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_details: Mapped[dict | None] = json_column()


class ScientificArtifact(Base, TimestampMixin):
    """Reference to an artifact produced by a scientific execution.

    The artifact bytes (and any Parquet result matrix) live in object storage;
    PostgreSQL stores the reference, checksum and provenance link.
    """

    __tablename__ = "scientific_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "scientific_execution_id", "artifact_key",
            name="uq_scientific_artifacts_scientific_execution_id_artifact_key",
        ),
        state_check("checksum_algorithm", ChecksumAlgorithm, "checksum_algorithm_valid"),
        Index("ix_scientific_artifacts_artifact_kind", "artifact_kind"),
    )

    id: Mapped[str] = id_column()
    scientific_execution_id: Mapped[str] = fk_column("app.scientific_executions.id")
    artifact_key: Mapped[str] = mapped_column(String(255), nullable=False)
    #: ``variant_table`` | ``annotation_table`` | ``log`` | ``manifest`` | ...
    artifact_kind: Mapped[str] = mapped_column(String(64), nullable=False)
    file_artifact_id: Mapped[str | None] = fk_column("app.file_artifacts.id", nullable=True)
    #: Analytical dataset location (Parquet root/partition) when applicable.
    analytical_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum_algorithm: Mapped[str | None] = mapped_column(String(64), nullable=True)
    checksum_value: Mapped[str | None] = mapped_column(String(256), nullable=True)
    metadata_json: Mapped[dict | None] = json_column()
