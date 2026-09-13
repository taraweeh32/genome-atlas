"""Upload sessions and import column mappings.

Two tables that Package 2 deliberately did not anticipate as normalized state:

* ``upload_sessions`` — the server-issued permission to transfer bytes, and the
  gate that decides whether those bytes may become a scientific input. Modelling
  it as a row (rather than as flags on ``file_artifacts``) is what allows an
  upload to be refused, expired, quarantined or cancelled while the artifact
  metadata and its lifecycle stay separately auditable.
* ``dataset_column_mappings`` — one row per source column of a tabular import.
  ``import_sessions.mapping_metadata`` keeps the confirmed configuration verbatim
  for provenance; these rows make "which column meant what, and who decided it"
  queryable, so a suggested mapping is never indistinguishable from a human
  decision.

Foreign keys point one way only (session → artifact), so there is no circular
dependency between the two tables and no ambiguity about which row owns the
storage reference.
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
    ChecksumAlgorithm,
    DuplicateRelation,
    FieldConcept,
    InputFormat,
    MappingOrigin,
    MappingStatus,
    UploadSessionState,
    ValueSemantics,
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


class UploadSession(Base, TimestampMixin, ConcurrencyMixin):
    __tablename__ = "upload_sessions"
    __table_args__ = (
        #: One session owns one storage location, so two sessions can never race
        #: for the same object.
        UniqueConstraint("storage_key", name="uq_upload_sessions_storage_key"),
        state_check("state", UploadSessionState, "state_valid"),
        state_check("declared_format", InputFormat, "declared_format_valid"),
        state_check(
            "declared_checksum_algorithm", ChecksumAlgorithm, "checksum_algorithm_valid"
        ),
        state_check("duplicate_relation", DuplicateRelation, "duplicate_relation_valid"),
        Index("ix_upload_sessions_workspace_id_state", "workspace_id", "state"),
        Index("ix_upload_sessions_expires_at", "expires_at"),
        Index("ix_upload_sessions_correlation_id", "correlation_id"),
    )

    id: Mapped[str] = id_column()
    #: Tenancy scope, authoritative for authorization.
    workspace_id: Mapped[str] = fk_column("app.workspaces.id")
    project_id: Mapped[str | None] = fk_column("app.projects.id", nullable=True)
    dataset_id: Mapped[str] = fk_column("app.datasets.id")
    dataset_version_id: Mapped[str] = fk_column("app.dataset_versions.id")
    file_artifact_id: Mapped[str] = fk_column("app.file_artifacts.id")
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=UploadSessionState.CREATED.value
    )
    initiated_by: Mapped[str] = fk_column("app.users.id")
    #: Derived from server-generated identifiers only; never client supplied.
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    #: The submitter's claims, recorded before any byte is accepted so that the
    #: stored object can be checked against them instead of being trusted.
    declared_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    declared_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    declared_format: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=InputFormat.UNKNOWN.value
    )
    declared_checksum_algorithm: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ChecksumAlgorithm.SHA256.value
    )
    declared_checksum_value: Mapped[str | None] = mapped_column(String(256), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Duplicate detection is reported, never auto-resolved: an identical upload
    #: may be legitimate, and silently reusing an artifact would rewrite lineage.
    duplicate_relation: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=DuplicateRelation.NONE.value
    )
    duplicate_of_file_artifact_id: Mapped[str | None] = fk_column(
        "app.file_artifacts.id", nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[dict | None] = json_column()


class DatasetColumnMapping(Base, TimestampMixin):
    __tablename__ = "dataset_column_mappings"
    __table_args__ = (
        UniqueConstraint(
            "import_session_id",
            "source_column_index",
            name="uq_dataset_column_mappings_session_column_index",
        ),
        state_check("status", MappingStatus, "status_valid"),
        state_check("origin", MappingOrigin, "origin_valid"),
        state_check("target_concept", FieldConcept, "target_concept_valid"),
        state_check("sample_value_semantics", ValueSemantics, "value_semantics_valid"),
        Index(
            "ix_dataset_column_mappings_import_session_id_status",
            "import_session_id",
            "status",
        ),
    )

    id: Mapped[str] = id_column()
    import_session_id: Mapped[str] = fk_column("app.import_sessions.id")
    source_column_name: Mapped[str] = mapped_column(String(512), nullable=False)
    source_column_index: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=MappingStatus.UNMAPPED.value
    )
    #: Whether a human chose this mapping or merely accepted a suggestion.
    origin: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=MappingOrigin.SYSTEM_SUGGESTED.value
    )
    target_concept: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=FieldConcept.IGNORED.value
    )
    declared_unit: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Shape metadata about the column's sampled values, never the values.
    sample_value_semantics: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ValueSemantics.PRESENT.value
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


__all__ = ["DatasetColumnMapping", "UploadSession"]
