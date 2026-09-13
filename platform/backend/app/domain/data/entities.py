"""Domain entities for datasets, artifacts, uploads, imports and validation.

Immutable dataclasses: a use case reads an entity, derives a new value with
``dataclasses.replace`` and asks a repository to persist it under the version it
read. Nothing here talks to a database, a queue or object storage.

Two invariants are expressed structurally rather than by convention:

* An accepted dataset version carries no mutable scientific payload — the only
  fields that ever change after acceptance are the supersession pointers, which
  record that a *newer* version now supersedes it.
* A file artifact separates "bytes arrived" (``upload_state``) from "may be
  used" (``validation_state``, ``scan_state``). No single flag can make an
  unscanned or unvalidated object usable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.domain.value_objects.enums import (
    ChecksumAlgorithm,
    CompressionKind,
    DatasetKind,
    DatasetState,
    DatasetVersionState,
    DeletionState,
    DuplicateRelation,
    FieldConcept,
    FileUploadState,
    FileValidationState,
    ImportSessionState,
    InputFormat,
    MalwareScanState,
    MappingOrigin,
    MappingStatus,
    ReferenceBuildDeclaration,
    UploadSessionState,
    ValidationCategory,
    ValidationRunState,
    ValidationSeverity,
    ValueSemantics,
)


@dataclass(frozen=True, slots=True)
class Dataset:
    """The mutable, named resource. Tenancy is authoritative on this row.

    ``workspace_id`` is always present; ``project_id`` is optional because a
    dataset may live directly in a workspace. Authorization is evaluated against
    whichever scope the dataset actually declares, never against a scope the
    caller supplies.
    """

    id: str
    workspace_id: str
    project_id: str | None
    name: str
    kind: DatasetKind
    state: DatasetState
    created_by: str
    #: The creator is not automatically the owner: ownership is assigned, and a
    #: creator leaving an organization must not orphan the dataset.
    owner_user_id: str | None
    description: str | None = None
    current_version_id: str | None = None
    reference_build_declared: ReferenceBuildDeclaration = (
        ReferenceBuildDeclaration.UNSPECIFIED
    )
    source_metadata: dict[str, Any] = field(default_factory=dict)
    scientific_metadata: dict[str, Any] = field(default_factory=dict)
    deletion_state: DeletionState = DeletionState.ACTIVE
    deleted_at: datetime | None = None
    deleted_by: str | None = None
    retention_expires_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    version: int = 1

    @property
    def is_active(self) -> bool:
        return self.deletion_state is DeletionState.ACTIVE

    @property
    def scope_project_id(self) -> str | None:
        return self.project_id


@dataclass(frozen=True, slots=True)
class DatasetVersion:
    """An immutable scientific input.

    A correction never rewrites this row; it creates the next version and marks
    this one superseded, so any historical result keeps pointing at exactly the
    bytes and metadata it was produced from.
    """

    id: str
    dataset_id: str
    version_number: int
    state: DatasetVersionState
    created_by: str
    checksum_algorithm: ChecksumAlgorithm = ChecksumAlgorithm.SHA256
    checksum_value: str | None = None
    declared_format: InputFormat = InputFormat.UNKNOWN
    detected_format: InputFormat = InputFormat.UNKNOWN
    compression: CompressionKind = CompressionKind.UNKNOWN
    reference_build_declared: ReferenceBuildDeclaration = (
        ReferenceBuildDeclaration.UNSPECIFIED
    )
    #: Verbatim source representation metadata. Never rewritten, never inferred.
    source_representation: dict[str, Any] = field(default_factory=dict)
    version_metadata: dict[str, Any] = field(default_factory=dict)
    scientific_metadata: dict[str, Any] = field(default_factory=dict)
    derived_from_version_id: str | None = None
    processing_lineage: dict[str, Any] = field(default_factory=dict)
    validated_at: datetime | None = None
    accepted_at: datetime | None = None
    accepted_by: str | None = None
    rejected_at: datetime | None = None
    rejection_reason: str | None = None
    superseded_by_version_id: str | None = None
    deletion_state: DeletionState = DeletionState.ACTIVE
    created_at: datetime | None = None

    @property
    def is_immutable_history(self) -> bool:
        """True once the version has reached a recorded scientific outcome."""
        return self.state in (
            DatasetVersionState.ACCEPTED,
            DatasetVersionState.REJECTED,
            DatasetVersionState.SUPERSEDED,
        )


@dataclass(frozen=True, slots=True)
class FileArtifact:
    """Authoritative metadata for one object-storage object.

    The bytes live in S3-compatible storage; PostgreSQL owns the reference, the
    checksum and the lifecycle. A storage key is never a URL and is never
    accepted from a client.
    """

    id: str
    workspace_id: str
    storage_provider: str
    storage_bucket: str
    storage_key: str
    filename: str
    uploaded_by: str
    dataset_id: str | None = None
    dataset_version_id: str | None = None
    upload_session_id: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    checksum_algorithm: ChecksumAlgorithm = ChecksumAlgorithm.SHA256
    checksum_value: str | None = None
    upload_state: FileUploadState = FileUploadState.PENDING
    validation_state: FileValidationState = FileValidationState.NOT_VALIDATED
    scan_state: MalwareScanState = MalwareScanState.NOT_SCANNED
    scan_detail: str | None = None
    declared_format: InputFormat = InputFormat.UNKNOWN
    detected_format: InputFormat = InputFormat.UNKNOWN
    compression: CompressionKind = CompressionKind.UNKNOWN
    original_filename: str | None = None
    quarantined_at: datetime | None = None
    quarantine_reason: str | None = None
    uploaded_at: datetime | None = None
    metadata_json: dict[str, Any] = field(default_factory=dict)
    deletion_state: DeletionState = DeletionState.ACTIVE
    created_at: datetime | None = None
    version: int = 1

    @property
    def is_retrievable(self) -> bool:
        """Bytes may only be handed out once every gate has actually passed."""
        return (
            self.deletion_state is DeletionState.ACTIVE
            and self.upload_state is FileUploadState.UPLOADED
            and self.scan_state is MalwareScanState.CLEAN
            and self.validation_state
            in (FileValidationState.VALID, FileValidationState.INVALID)
        )


@dataclass(frozen=True, slots=True)
class UploadSession:
    """Server-issued permission to transfer bytes for one artifact.

    Holding the presigned URL is not the same as holding the right to make the
    artifact usable: the session records the declared size, checksum and format
    up front, and completion is only accepted when the stored object matches.
    """

    id: str
    workspace_id: str
    dataset_id: str
    dataset_version_id: str
    file_artifact_id: str
    state: UploadSessionState
    initiated_by: str
    storage_key: str
    declared_filename: str
    declared_size_bytes: int
    declared_format: InputFormat
    declared_checksum_algorithm: ChecksumAlgorithm
    declared_checksum_value: str | None
    project_id: str | None = None
    expires_at: datetime | None = None
    completed_at: datetime | None = None
    failure_reason: str | None = None
    duplicate_relation: DuplicateRelation = DuplicateRelation.NONE
    duplicate_of_file_artifact_id: str | None = None
    correlation_id: str | None = None
    created_at: datetime | None = None
    version: int = 1


@dataclass(frozen=True, slots=True)
class ColumnMapping:
    """One source column and the platform concept it was mapped to.

    Kept as rows rather than an opaque blob so that "which column meant what" is
    queryable per import, and so a suggested mapping never becomes
    indistinguishable from a human decision.
    """

    id: str
    import_session_id: str
    source_column_name: str
    source_column_index: int
    status: MappingStatus
    origin: MappingOrigin
    target_concept: FieldConcept = FieldConcept.IGNORED
    declared_unit: str | None = None
    #: Sample values are metadata about shape, never a copy of the dataset.
    sample_value_semantics: ValueSemantics = ValueSemantics.PRESENT
    notes: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ImportSession:
    """One attempt to turn an uploaded artifact into an accepted version.

    Rejection is retained with its reason. An accepted import is never edited;
    re-importing opens a new session.
    """

    id: str
    workspace_id: str
    state: ImportSessionState
    initiated_by: str
    project_id: str | None = None
    dataset_id: str | None = None
    dataset_version_id: str | None = None
    file_artifact_id: str | None = None
    declared_format: InputFormat = InputFormat.UNKNOWN
    detected_format: InputFormat = InputFormat.UNKNOWN
    reference_build_declared: ReferenceBuildDeclaration = (
        ReferenceBuildDeclaration.UNSPECIFIED
    )
    #: The import configuration exactly as decided, kept for provenance.
    mapping_metadata: dict[str, Any] = field(default_factory=dict)
    import_provenance: dict[str, Any] = field(default_factory=dict)
    importer_version: str | None = None
    idempotency_key: str | None = None
    mapping_confirmed_at: datetime | None = None
    submitted_at: datetime | None = None
    decided_at: datetime | None = None
    decided_by: str | None = None
    rejection_reason: str | None = None
    correlation_id: str | None = None
    created_at: datetime | None = None
    version: int = 1


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """One finding. Severity and category are explicit and never merged."""

    id: str
    validation_run_id: str
    severity: ValidationSeverity
    category: ValidationCategory
    code: str
    message: str
    validation_rule_id: str | None = None
    locator: dict[str, Any] = field(default_factory=dict)
    value_semantics: ValueSemantics = ValueSemantics.PRESENT
    #: Only ever a short, non-sensitive excerpt — never genomic content in bulk.
    observed_value: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ValidationRun:
    """One recorded validation execution over an artifact or version.

    Terminal outcomes are facts: re-validation creates a new run rather than
    rewriting this one, so a history of what was known when is preserved.
    """

    id: str
    state: ValidationRunState
    validator_name: str
    validator_version: str
    import_session_id: str | None = None
    dataset_version_id: str | None = None
    file_artifact_id: str | None = None
    requested_by: str | None = None
    correlation_id: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    blocking_issue_count: int = 0
    error_issue_count: int = 0
    warning_issue_count: int = 0
    info_issue_count: int = 0
    summary: dict[str, Any] = field(default_factory=dict)
    created_at: datetime | None = None

    @property
    def blocks_acceptance(self) -> bool:
        return (
            self.blocking_issue_count > 0
            or self.error_issue_count > 0
            or self.state
            in (ValidationRunState.FAILED, ValidationRunState.ERRORED)
        )


def outcome_for(
    *, blocking: int, errors: int, warnings: int
) -> ValidationRunState:
    """Map issue counts to a run outcome.

    Warnings never silently pass as a clean result: ``passed_with_warnings`` is a
    distinct outcome so a reviewer can see that something was flagged.
    """
    if blocking or errors:
        return ValidationRunState.FAILED
    if warnings:
        return ValidationRunState.PASSED_WITH_WARNINGS
    return ValidationRunState.PASSED


__all__ = [
    "ColumnMapping",
    "Dataset",
    "DatasetVersion",
    "FileArtifact",
    "ImportSession",
    "UploadSession",
    "ValidationIssue",
    "ValidationRun",
    "outcome_for",
]
