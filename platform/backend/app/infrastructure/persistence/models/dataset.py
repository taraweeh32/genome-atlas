"""Dataset, dataset version and file artifact persistence.

Three distinct concepts, deliberately not merged:

* **Dataset** — the mutable, named resource users manage.
* **Dataset version** — an immutable scientific input. Corrections create a new
  version; an accepted version is never mutated in place.
* **File artifact** — object-storage metadata. PostgreSQL stores the reference,
  checksum and lifecycle; the bytes live in S3-compatible storage.
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
    CompressionKind,
    DatasetKind,
    DatasetState,
    DatasetVersionState,
    DeletionState,
    FileUploadState,
    FileValidationState,
    InputFormat,
    MalwareScanState,
    ReferenceBuildDeclaration,
)
from app.infrastructure.persistence.base import (
    Base,
    ConcurrencyMixin,
    RetentionMixin,
    TimestampMixin,
    fk_column,
    id_column,
    json_column,
    state_check,
)


class Dataset(Base, TimestampMixin, ConcurrencyMixin, RetentionMixin):
    __tablename__ = "datasets"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", name="uq_datasets_workspace_id_name"),
        state_check("kind", DatasetKind, "kind_valid"),
        state_check("state", DatasetState, "state_valid"),
        state_check("deletion_state", DeletionState, "deletion_state_valid"),
        state_check(
            "reference_build_declared", ReferenceBuildDeclaration, "reference_build_valid"
        ),
        Index("ix_datasets_project_id_state", "project_id", "state"),
    )

    id: Mapped[str] = id_column()
    #: Tenancy scope: authoritative for authorization in later packages.
    workspace_id: Mapped[str] = fk_column("app.workspaces.id")
    #: A dataset may be workspace-scoped without belonging to a project.
    project_id: Mapped[str | None] = fk_column("app.projects.id", nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=DatasetState.DRAFT.value
    )
    created_by: Mapped[str] = fk_column("app.users.id")
    owner_user_id: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    #: Pointer to the current accepted version; history stays intact.
    current_version_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: A *declared* build, never a verified one. Confirming that coordinates are
    #: consistent with a build is scientific work performed outside this layer.
    reference_build_declared: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ReferenceBuildDeclaration.UNSPECIFIED.value
    )
    source_metadata: Mapped[dict | None] = json_column()
    scientific_metadata: Mapped[dict | None] = json_column()


class DatasetVersion(Base, TimestampMixin, RetentionMixin):
    """Immutable scientific input.

    Deliberately has no ``ConcurrencyMixin``: the row is not an editable
    resource. Mutable review bookkeeping lives on the acceptance columns, which
    transition once, and any scientific correction produces a new version.
    """

    __tablename__ = "dataset_versions"
    __table_args__ = (
        UniqueConstraint(
            "dataset_id", "version_number", name="uq_dataset_versions_dataset_id_version_number"
        ),
        state_check("state", DatasetVersionState, "state_valid"),
        state_check("checksum_algorithm", ChecksumAlgorithm, "checksum_algorithm_valid"),
        state_check("deletion_state", DeletionState, "deletion_state_valid"),
        state_check("declared_format", InputFormat, "declared_format_valid"),
        state_check("detected_format", InputFormat, "detected_format_valid"),
        state_check("compression", CompressionKind, "compression_valid"),
        state_check(
            "reference_build_declared", ReferenceBuildDeclaration, "reference_build_valid"
        ),
        Index("ix_dataset_versions_dataset_id_state", "dataset_id", "state"),
    )

    id: Mapped[str] = id_column()
    dataset_id: Mapped[str] = fk_column("app.datasets.id")
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=DatasetVersionState.CREATED.value
    )
    created_by: Mapped[str] = fk_column("app.users.id")
    #: Content checksum over the version's canonical file set.
    checksum_algorithm: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ChecksumAlgorithm.SHA256.value
    )
    checksum_value: Mapped[str | None] = mapped_column(String(256), nullable=True)
    #: What the submitter claimed, and what the bytes actually looked like. Kept
    #: as two columns so a contradiction stays visible instead of being resolved.
    declared_format: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=InputFormat.UNKNOWN.value
    )
    detected_format: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=InputFormat.UNKNOWN.value
    )
    compression: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=CompressionKind.UNKNOWN.value
    )
    reference_build_declared: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ReferenceBuildDeclaration.UNSPECIFIED.value
    )
    #: Verbatim source representation metadata; never rewritten.
    source_representation: Mapped[dict | None] = json_column()
    version_metadata: Mapped[dict | None] = json_column()
    scientific_metadata: Mapped[dict | None] = json_column()
    #: Lineage: the version this one was derived from, when applicable.
    derived_from_version_id: Mapped[str | None] = fk_column(
        "app.dataset_versions.id", nullable=True
    )
    processing_lineage: Mapped[dict | None] = json_column()
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    superseded_by_version_id: Mapped[str | None] = fk_column(
        "app.dataset_versions.id", nullable=True
    )


class FileArtifact(Base, TimestampMixin, ConcurrencyMixin, RetentionMixin):
    """Authoritative metadata for one object-storage object."""

    __tablename__ = "file_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "storage_provider",
            "storage_bucket",
            "storage_key",
            name="uq_file_artifacts_storage_provider_storage_bucket_storage_key",
        ),
        state_check("upload_state", FileUploadState, "upload_state_valid"),
        state_check("validation_state", FileValidationState, "validation_state_valid"),
        state_check("scan_state", MalwareScanState, "scan_state_valid"),
        state_check("declared_format", InputFormat, "declared_format_valid"),
        state_check("detected_format", InputFormat, "detected_format_valid"),
        state_check("compression", CompressionKind, "compression_valid"),
        state_check("checksum_algorithm", ChecksumAlgorithm, "checksum_algorithm_valid"),
        state_check("deletion_state", DeletionState, "deletion_state_valid"),
        Index("ix_file_artifacts_dataset_version_id_upload_state", "dataset_version_id",
              "upload_state"),
    )

    id: Mapped[str] = id_column()
    workspace_id: Mapped[str] = fk_column("app.workspaces.id")
    dataset_id: Mapped[str | None] = fk_column("app.datasets.id", nullable=True)
    dataset_version_id: Mapped[str | None] = fk_column("app.dataset_versions.id", nullable=True)
    #: Storage abstraction: provider + bucket + key, never a raw URL.
    storage_provider: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_bucket: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum_algorithm: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ChecksumAlgorithm.SHA256.value
    )
    checksum_value: Mapped[str | None] = mapped_column(String(256), nullable=True)
    upload_state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=FileUploadState.PENDING.value
    )
    validation_state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=FileValidationState.NOT_VALIDATED.value
    )
    #: Scanning is a separate gate from validation, and it fails closed: an
    #: artifact that could not be scanned is never treated as safe.
    scan_state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=MalwareScanState.NOT_SCANNED.value
    )
    scan_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    declared_format: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=InputFormat.UNKNOWN.value
    )
    detected_format: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=InputFormat.UNKNOWN.value
    )
    compression: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=CompressionKind.UNKNOWN.value
    )
    #: The name exactly as submitted, preserved as source metadata. ``filename``
    #: holds the sanitised name used for display and download.
    original_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    quarantined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quarantine_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[str] = fk_column("app.users.id")
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict | None] = json_column()
