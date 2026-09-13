"""Response shaping for dataset, upload, import and validation resources.

Split from ``mapping.py`` to keep each module reviewable rather than growing one
file that shapes every resource on the platform. The rules are the same:

* transport types never leak into the application layer;
* enums are serialized by value, so the API contract does not depend on Python
  member names;
* storage keys, bucket names and provider details are never serialized — a
  client learns *that* an artifact exists, never where its bytes live.
"""

from __future__ import annotations

from app.api.v1.mapping import page_meta
from app.api.v1.schemas.data import (
    ColumnMappingResponse,
    DatasetCollection,
    DatasetResponse,
    DatasetVersionCollection,
    DatasetVersionResponse,
    DownloadGrantResponse,
    FileArtifactResponse,
    ImportSessionCollection,
    ImportSessionResponse,
    ImportSessionSummary,
    UploadSessionResponse,
    UploadTicketResponse,
    ValidationIssueResponse,
    ValidationRunCollection,
    ValidationRunResponse,
    ValidationRunSummary,
)
from app.application.repositories import Paged
from app.domain.data.entities import (
    ColumnMapping,
    FileArtifact,
    ImportSession,
    ValidationIssue,
    ValidationRun,
)


def artifact_response(artifact: FileArtifact) -> FileArtifactResponse:
    return FileArtifactResponse(
        id=artifact.id,
        filename=artifact.filename,
        original_filename=artifact.original_filename,
        size_bytes=artifact.size_bytes,
        content_type=artifact.content_type,
        upload_state=artifact.upload_state.value,
        validation_state=artifact.validation_state.value,
        scan_state=artifact.scan_state.value,
        scan_detail=artifact.scan_detail,
        declared_format=artifact.declared_format.value,
        detected_format=artifact.detected_format.value,
        compression=artifact.compression.value,
        checksum_algorithm=artifact.checksum_algorithm.value,
        checksum_value=artifact.checksum_value,
        is_retrievable=artifact.is_retrievable,
        quarantined_at=artifact.quarantined_at,
        uploaded_at=artifact.uploaded_at,
    )


def validation_run_summary(run: ValidationRun) -> ValidationRunSummary:
    return ValidationRunSummary(
        id=run.id,
        state=run.state.value,
        validator_name=run.validator_name,
        validator_version=run.validator_version,
        blocking_issue_count=run.blocking_issue_count,
        error_issue_count=run.error_issue_count,
        warning_issue_count=run.warning_issue_count,
        info_issue_count=run.info_issue_count,
        started_at=run.started_at,
        completed_at=run.completed_at,
        summary=dict(run.summary),
    )


def validation_issue_response(issue: ValidationIssue) -> ValidationIssueResponse:
    return ValidationIssueResponse(
        id=issue.id,
        severity=issue.severity.value,
        category=issue.category.value,
        code=issue.code,
        message=issue.message,
        validation_rule_id=issue.validation_rule_id,
        locator=dict(issue.locator),
        value_semantics=issue.value_semantics.value,
        observed_value=issue.observed_value,
        details=dict(issue.details),
    )


def validation_run_response(view) -> ValidationRunResponse:
    run = view.run
    return ValidationRunResponse(
        run=validation_run_summary(run),
        subject={
            "file_artifact_id": run.file_artifact_id,
            "dataset_version_id": run.dataset_version_id,
            "import_session_id": run.import_session_id,
        },
        issues=[validation_issue_response(issue) for issue in view.issues],
        issue_total=view.issue_total,
    )


def validation_run_collection(paged: Paged) -> ValidationRunCollection:
    return ValidationRunCollection(
        items=[validation_run_summary(run) for run in paged.items],
        page=page_meta(paged),
    )


def dataset_response(view) -> DatasetResponse:
    dataset = view.dataset
    return DatasetResponse(
        id=dataset.id,
        workspace_id=dataset.workspace_id,
        project_id=dataset.project_id,
        name=dataset.name,
        kind=dataset.kind.value,
        state=dataset.state.value,
        description=dataset.description,
        created_by=dataset.created_by,
        owner_user_id=dataset.owner_user_id,
        reference_build_declared=dataset.reference_build_declared.value,
        current_version_id=dataset.current_version_id,
        deletion_state=dataset.deletion_state.value,
        retention_expires_at=dataset.retention_expires_at,
        version_count=view.version_count,
        capabilities=list(view.capabilities),
        created_at=dataset.created_at,
        version=dataset.version,
    )


def dataset_collection(paged: Paged) -> DatasetCollection:
    return DatasetCollection(
        items=[dataset_response(view) for view in paged.items],
        page=page_meta(paged),
    )


def dataset_version_response(view) -> DatasetVersionResponse:
    version = view.version
    return DatasetVersionResponse(
        id=version.id,
        dataset_id=version.dataset_id,
        version_number=version.version_number,
        state=version.state.value,
        created_by=version.created_by,
        declared_format=version.declared_format.value,
        detected_format=version.detected_format.value,
        compression=version.compression.value,
        reference_build_declared=version.reference_build_declared.value,
        checksum_algorithm=version.checksum_algorithm.value,
        checksum_value=version.checksum_value,
        source_representation=dict(version.source_representation),
        validated_at=version.validated_at,
        accepted_at=version.accepted_at,
        accepted_by=version.accepted_by,
        rejected_at=version.rejected_at,
        rejection_reason=version.rejection_reason,
        superseded_by_version_id=version.superseded_by_version_id,
        artifacts=[artifact_response(artifact) for artifact in view.artifacts],
        latest_validation=(
            validation_run_summary(view.latest_validation) if view.latest_validation else None
        ),
        acceptance_blocked_reason=view.acceptance_blocked_reason,
        created_at=version.created_at,
    )


def dataset_version_collection(paged: Paged) -> DatasetVersionCollection:
    return DatasetVersionCollection(
        items=[dataset_version_response(view) for view in paged.items],
        page=page_meta(paged),
    )


def upload_session_response(view) -> UploadSessionResponse:
    session = view.session
    return UploadSessionResponse(
        id=session.id,
        state=session.state.value,
        dataset_id=session.dataset_id,
        dataset_version_id=session.dataset_version_id,
        file_artifact_id=session.file_artifact_id,
        declared_filename=session.declared_filename,
        declared_size_bytes=session.declared_size_bytes,
        declared_format=session.declared_format.value,
        expires_at=session.expires_at,
        completed_at=session.completed_at,
        failure_reason=session.failure_reason,
        duplicate_relation=session.duplicate_relation.value,
        duplicate_of_file_artifact_id=session.duplicate_of_file_artifact_id,
        artifact=artifact_response(view.artifact),
        latest_validation=(
            validation_run_summary(view.latest_validation) if view.latest_validation else None
        ),
    )


def upload_ticket_response(ticket) -> UploadTicketResponse:
    session = UploadSessionResponse(
        id=ticket.session.id,
        state=ticket.session.state.value,
        dataset_id=ticket.session.dataset_id,
        dataset_version_id=ticket.session.dataset_version_id,
        file_artifact_id=ticket.session.file_artifact_id,
        declared_filename=ticket.session.declared_filename,
        declared_size_bytes=ticket.session.declared_size_bytes,
        declared_format=ticket.session.declared_format.value,
        expires_at=ticket.session.expires_at,
        completed_at=ticket.session.completed_at,
        failure_reason=ticket.session.failure_reason,
        duplicate_relation=ticket.duplicate_relation.value,
        duplicate_of_file_artifact_id=ticket.duplicate_of_file_artifact_id,
        artifact=artifact_response(ticket.artifact),
        latest_validation=None,
    )
    return UploadTicketResponse(
        session=session, upload_url=ticket.upload_url, expires_at=ticket.expires_at
    )


def download_grant_response(grant) -> DownloadGrantResponse:
    return DownloadGrantResponse(
        file_artifact_id=grant.artifact.id,
        filename=grant.artifact.filename,
        download_url=grant.download_url,
        expires_in_seconds=grant.expires_in_seconds,
    )


def column_mapping_response(mapping: ColumnMapping) -> ColumnMappingResponse:
    return ColumnMappingResponse(
        id=mapping.id,
        source_column_name=mapping.source_column_name,
        source_column_index=mapping.source_column_index,
        status=mapping.status.value,
        origin=mapping.origin.value,
        target_concept=mapping.target_concept.value,
        declared_unit=mapping.declared_unit,
        sample_value_semantics=mapping.sample_value_semantics.value,
        notes=mapping.notes,
    )


def import_session_response(view) -> ImportSessionResponse:
    session = view.session
    return ImportSessionResponse(
        id=session.id,
        state=session.state.value,
        dataset_id=session.dataset_id,
        dataset_version_id=session.dataset_version_id,
        file_artifact_id=session.file_artifact_id,
        declared_format=session.declared_format.value,
        detected_format=session.detected_format.value,
        reference_build_declared=session.reference_build_declared.value,
        importer_version=session.importer_version,
        mapping_confirmed_at=session.mapping_confirmed_at,
        submitted_at=session.submitted_at,
        decided_at=session.decided_at,
        rejection_reason=session.rejection_reason,
        import_provenance=dict(session.import_provenance),
        mappings=[column_mapping_response(mapping) for mapping in view.mappings],
        latest_validation=(
            validation_run_summary(view.latest_validation) if view.latest_validation else None
        ),
        submission_blocked_reason=view.submission_blocked_reason,
        created_at=session.created_at,
        version=session.version,
    )


def import_session_summary(session: ImportSession) -> ImportSessionSummary:
    return ImportSessionSummary(
        id=session.id,
        state=session.state.value,
        dataset_version_id=session.dataset_version_id,
        file_artifact_id=session.file_artifact_id,
        detected_format=session.detected_format.value,
        mapping_confirmed_at=session.mapping_confirmed_at,
        submitted_at=session.submitted_at,
        decided_at=session.decided_at,
        rejection_reason=session.rejection_reason,
        created_at=session.created_at,
    )


def import_session_collection(paged: Paged) -> ImportSessionCollection:
    return ImportSessionCollection(
        items=[import_session_summary(session) for session in paged.items],
        page=page_meta(paged),
    )


__all__ = [
    "artifact_response",
    "column_mapping_response",
    "dataset_collection",
    "dataset_response",
    "dataset_version_collection",
    "dataset_version_response",
    "download_grant_response",
    "import_session_collection",
    "import_session_response",
    "import_session_summary",
    "upload_session_response",
    "upload_ticket_response",
    "validation_issue_response",
    "validation_run_collection",
    "validation_run_response",
    "validation_run_summary",
]
