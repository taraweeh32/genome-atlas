"""Request/response schemas for datasets, uploads, imports and validation.

Conventions carried over from the tenancy schemas:

* Every resource response carries the caller's ``capabilities`` for that resource
  so the UI can render only usable controls. The list is derived server-side and
  is never accepted as input.
* Responses carry the row's ``version`` where a concurrent edit is possible, so a
  client can detect that what it displayed is stale. The optimistic check itself
  happens in persistence, never in the request body.

Two shapes exist specifically so the frontend cannot become authoritative:

* ``acceptance_blocked_reason`` — the server's own answer to "could this version
  be accepted right now, and if not, why". The UI displays it; the accept
  endpoint re-derives it and refuses regardless of what the UI showed.
* ``submission_blocked_reason`` — the same idea for an import's mapping.

Storage keys are never exposed. A download is requested and answered with a
short-lived URL, which is the only way bytes leave the platform.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.v1.schemas.common import ApiModel
from app.api.v1.schemas.tenancy import PageMeta

# --------------------------------------------------------------------------- #
# Datasets                                                                    #
# --------------------------------------------------------------------------- #


class DatasetCreatePayload(ApiModel):
    workspace_id: str | None = Field(
        default=None,
        description="Required unless project_id is given, in which case the "
        "project's own workspace is used.",
    )
    project_id: str | None = None
    name: str = Field(min_length=2, max_length=200)
    kind: str = Field(description="Dataset kind, e.g. variant_calls.")
    description: str | None = Field(default=None, max_length=2000)
    reference_build_declared: str = Field(
        default="unspecified",
        description="The genome build the submitter declares. A declaration, "
        "never a verification.",
    )


class DatasetUpdatePayload(ApiModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class DatasetLifecyclePayload(ApiModel):
    target_state: str = Field(description="Requested dataset state, e.g. archived.")
    reason: str | None = Field(default=None, max_length=500)


class DatasetDeletePayload(ApiModel):
    reason: str | None = Field(default=None, max_length=500)


class DatasetResponse(ApiModel):
    id: str
    workspace_id: str
    project_id: str | None
    name: str
    kind: str
    state: str
    description: str | None
    created_by: str
    owner_user_id: str | None
    reference_build_declared: str
    current_version_id: str | None
    deletion_state: str
    retention_expires_at: datetime | None
    version_count: int
    capabilities: list[str]
    created_at: datetime | None
    version: int


class DatasetCollection(ApiModel):
    items: list[DatasetResponse]
    page: PageMeta


# --------------------------------------------------------------------------- #
# Versions and artifacts                                                      #
# --------------------------------------------------------------------------- #


class DatasetVersionCreatePayload(ApiModel):
    notes: str | None = Field(default=None, max_length=2000)
    reference_build_declared: str | None = None


class DatasetVersionDecisionPayload(ApiModel):
    accept: bool
    reason: str | None = Field(
        default=None,
        max_length=1000,
        description="Required when rejecting. Retained with the version forever.",
    )


class FileArtifactResponse(ApiModel):
    id: str
    filename: str
    original_filename: str | None
    size_bytes: int | None
    content_type: str | None
    upload_state: str
    validation_state: str
    scan_state: str
    scan_detail: str | None
    declared_format: str
    detected_format: str
    compression: str
    checksum_algorithm: str
    checksum_value: str | None
    is_retrievable: bool
    quarantined_at: datetime | None
    uploaded_at: datetime | None


class ValidationRunSummary(ApiModel):
    id: str
    state: str
    validator_name: str
    validator_version: str
    blocking_issue_count: int
    error_issue_count: int
    warning_issue_count: int
    info_issue_count: int
    started_at: datetime | None
    completed_at: datetime | None
    summary: dict[str, object]


class DatasetVersionResponse(ApiModel):
    id: str
    dataset_id: str
    version_number: int
    state: str
    created_by: str
    declared_format: str
    detected_format: str
    compression: str
    reference_build_declared: str
    checksum_algorithm: str
    checksum_value: str | None
    source_representation: dict[str, object]
    validated_at: datetime | None
    accepted_at: datetime | None
    accepted_by: str | None
    rejected_at: datetime | None
    rejection_reason: str | None
    superseded_by_version_id: str | None
    artifacts: list[FileArtifactResponse]
    latest_validation: ValidationRunSummary | None
    acceptance_blocked_reason: str | None
    created_at: datetime | None


class DatasetVersionCollection(ApiModel):
    items: list[DatasetVersionResponse]
    page: PageMeta


# --------------------------------------------------------------------------- #
# Uploads                                                                     #
# --------------------------------------------------------------------------- #


class UploadSessionCreatePayload(ApiModel):
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    declared_format: str | None = Field(
        default=None, description="Omitted means: derive the claim from the filename."
    )
    checksum_algorithm: str = "sha256"
    checksum_value: str | None = Field(
        default=None,
        max_length=256,
        description="Optional client-computed digest. Verified against the stored "
        "bytes before the upload can be used.",
    )
    content_type: str | None = Field(default=None, max_length=255)


class UploadSessionResponse(ApiModel):
    id: str
    state: str
    dataset_id: str
    dataset_version_id: str
    file_artifact_id: str
    declared_filename: str
    declared_size_bytes: int
    declared_format: str
    expires_at: datetime | None
    completed_at: datetime | None
    failure_reason: str | None
    duplicate_relation: str
    duplicate_of_file_artifact_id: str | None
    artifact: FileArtifactResponse
    latest_validation: ValidationRunSummary | None


class UploadTicketResponse(ApiModel):
    session: UploadSessionResponse
    upload_url: str = Field(
        description="Short-lived transfer grant. Holding it does not make the "
        "artifact usable."
    )
    expires_at: datetime


class UploadCancelPayload(ApiModel):
    reason: str | None = Field(default=None, max_length=500)


class DownloadGrantResponse(ApiModel):
    file_artifact_id: str
    filename: str
    download_url: str
    expires_in_seconds: int


# --------------------------------------------------------------------------- #
# Imports                                                                     #
# --------------------------------------------------------------------------- #


class ImportSessionCreatePayload(ApiModel):
    file_artifact_id: str
    idempotency_key: str | None = Field(
        default=None,
        max_length=128,
        description="A retried request re-uses the existing import instead of "
        "opening a second one.",
    )


class ColumnMappingResponse(ApiModel):
    id: str
    source_column_name: str
    source_column_index: int
    status: str
    origin: str = Field(
        description="Whether a person chose this mapping or the platform suggested it."
    )
    target_concept: str
    declared_unit: str | None
    sample_value_semantics: str
    notes: str | None


class ColumnMappingDecisionPayload(ApiModel):
    source_column_index: int = Field(ge=0)
    source_column_name: str = Field(min_length=1, max_length=512)
    target_concept: str
    declared_unit: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=1000)


class ColumnMappingConfirmPayload(ApiModel):
    mappings: list[ColumnMappingDecisionPayload] = Field(min_length=1)


class ImportSessionResponse(ApiModel):
    id: str
    state: str
    dataset_id: str | None
    dataset_version_id: str | None
    file_artifact_id: str | None
    declared_format: str
    detected_format: str
    reference_build_declared: str
    importer_version: str | None
    mapping_confirmed_at: datetime | None
    submitted_at: datetime | None
    decided_at: datetime | None
    rejection_reason: str | None
    import_provenance: dict[str, object]
    mappings: list[ColumnMappingResponse]
    latest_validation: ValidationRunSummary | None
    submission_blocked_reason: str | None
    created_at: datetime | None
    version: int


class ImportSessionSummary(ApiModel):
    id: str
    state: str
    dataset_version_id: str | None
    file_artifact_id: str | None
    detected_format: str
    mapping_confirmed_at: datetime | None
    submitted_at: datetime | None
    decided_at: datetime | None
    rejection_reason: str | None
    created_at: datetime | None


class ImportSessionCollection(ApiModel):
    items: list[ImportSessionSummary]
    page: PageMeta


class ImportAbandonPayload(ApiModel):
    reason: str | None = Field(default=None, max_length=500)


# --------------------------------------------------------------------------- #
# Validation                                                                  #
# --------------------------------------------------------------------------- #


class ValidationIssueResponse(ApiModel):
    id: str
    severity: str
    category: str
    code: str
    message: str
    validation_rule_id: str | None
    locator: dict[str, object]
    value_semantics: str = Field(
        description="Explicit semantics of the observed value: missing, empty, "
        "na, unknown, not_applicable, zero, false or present. Never conflated."
    )
    observed_value: str | None
    details: dict[str, object]


class ValidationRunResponse(ApiModel):
    run: ValidationRunSummary
    subject: dict[str, str | None]
    issues: list[ValidationIssueResponse]
    issue_total: int


class ValidationRunCollection(ApiModel):
    items: list[ValidationRunSummary]
    page: PageMeta


__all__ = [
    "ColumnMappingConfirmPayload",
    "ColumnMappingDecisionPayload",
    "ColumnMappingResponse",
    "DatasetCollection",
    "DatasetCreatePayload",
    "DatasetDeletePayload",
    "DatasetLifecyclePayload",
    "DatasetResponse",
    "DatasetUpdatePayload",
    "DatasetVersionCollection",
    "DatasetVersionCreatePayload",
    "DatasetVersionDecisionPayload",
    "DatasetVersionResponse",
    "DownloadGrantResponse",
    "FileArtifactResponse",
    "ImportAbandonPayload",
    "ImportSessionCollection",
    "ImportSessionCreatePayload",
    "ImportSessionResponse",
    "ImportSessionSummary",
    "UploadCancelPayload",
    "UploadSessionCreatePayload",
    "UploadSessionResponse",
    "UploadTicketResponse",
    "ValidationIssueResponse",
    "ValidationRunCollection",
    "ValidationRunResponse",
    "ValidationRunSummary",
]
