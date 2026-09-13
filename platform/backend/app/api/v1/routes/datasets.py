"""Dataset, version, upload, import and validation endpoints.

Every handler here is thin on purpose: it parses transport input, hands an
explicit command to a use case, and shapes the result. It never decides access,
never decides a state transition, and never trusts a client-supplied scope — the
use case resolves the owning workspace/project from the stored resource and
requires the permission *there*. A caller who knows an identifier therefore
learns nothing they are not entitled to.

Two boundaries are visible in the route layout:

* Bytes never pass through the API. An upload is a session plus a short-lived
  transfer grant, and a download is an explicitly authorized grant. This keeps
  large genomic files on object storage and keeps the API able to refuse an
  artifact after its bytes exist.
* Validation is not acceptance. Completing an upload queues verification; making
  a version the dataset's current input stays a separate, explicit human decision
  with its own permission.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.authentication import CallerDep, RequestContextDep
from app.api.dependencies import ContainerDep
from app.api.v1.data_mapping import (
    dataset_collection,
    dataset_response,
    dataset_version_collection,
    dataset_version_response,
    download_grant_response,
    import_session_collection,
    import_session_response,
    upload_session_response,
    upload_ticket_response,
    validation_run_collection,
    validation_run_response,
)
from app.api.v1.mapping import PageDep, parse_enum
from app.api.v1.schemas.common import ERROR_RESPONSES
from app.api.v1.schemas.data import (
    ColumnMappingConfirmPayload,
    DatasetCollection,
    DatasetCreatePayload,
    DatasetDeletePayload,
    DatasetLifecyclePayload,
    DatasetResponse,
    DatasetUpdatePayload,
    DatasetVersionCollection,
    DatasetVersionCreatePayload,
    DatasetVersionDecisionPayload,
    DatasetVersionResponse,
    DownloadGrantResponse,
    ImportAbandonPayload,
    ImportSessionCollection,
    ImportSessionCreatePayload,
    ImportSessionResponse,
    UploadCancelPayload,
    UploadSessionCreatePayload,
    UploadSessionResponse,
    UploadTicketResponse,
    ValidationRunCollection,
    ValidationRunResponse,
)
from app.application.use_cases.data.datasets import (
    ChangeDatasetState,
    ChangeDatasetStateCommand,
    CreateDataset,
    CreateDatasetCommand,
    CreateDatasetVersion,
    CreateDatasetVersionCommand,
    DecideDatasetVersion,
    DecideDatasetVersionCommand,
    GetDataset,
    GetDatasetQuery,
    GetDatasetVersion,
    GetDatasetVersionQuery,
    ListDatasets,
    ListDatasetsQuery,
    ListDatasetVersions,
    ListDatasetVersionsQuery,
    SoftDeleteDataset,
    SoftDeleteDatasetCommand,
    UpdateDataset,
    UpdateDatasetCommand,
)
from app.application.use_cases.data.imports import (
    AbandonImportSession,
    AbandonImportSessionCommand,
    ColumnMappingRequest,
    ConfirmColumnMapping,
    ConfirmColumnMappingCommand,
    GetImportSession,
    GetImportSessionQuery,
    ListImportSessions,
    ListImportSessionsQuery,
    OpenImportSession,
    OpenImportSessionCommand,
    SubmitImport,
    SubmitImportCommand,
)
from app.application.use_cases.data.uploads import (
    CancelUploadSession,
    CancelUploadSessionCommand,
    CompleteUpload,
    CompleteUploadCommand,
    IssueArtifactDownload,
    IssueArtifactDownloadCommand,
    OpenUploadSession,
    OpenUploadSessionCommand,
)
from app.application.use_cases.data.validation import (
    SUBJECT_TYPES,
    GetValidationRun,
    GetValidationRunQuery,
    ListValidationRuns,
    ListValidationRunsQuery,
)
from app.domain.errors import ValidationError
from app.domain.value_objects.enums import (
    ChecksumAlgorithm,
    DatasetKind,
    DatasetState,
    FieldConcept,
    InputFormat,
    ReferenceBuildDeclaration,
)

router = APIRouter(prefix="/datasets", tags=["datasets"])
uploads_router = APIRouter(prefix="/uploads", tags=["uploads"])
imports_router = APIRouter(prefix="/imports", tags=["imports"])
artifacts_router = APIRouter(prefix="/file-artifacts", tags=["files"])
validation_router = APIRouter(prefix="/validation", tags=["validation"])
versions_router = APIRouter(prefix="/dataset-versions", tags=["datasets"])


# --------------------------------------------------------------------------- #
# Datasets                                                                    #
# --------------------------------------------------------------------------- #


@router.post(
    "",
    response_model=DatasetResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a dataset",
    responses=ERROR_RESPONSES,
)
async def create_dataset(
    payload: DatasetCreatePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> DatasetResponse:
    if payload.workspace_id is None and payload.project_id is None:
        raise ValidationError(
            "a dataset must be created in a workspace or a project",
            details={"field": "workspace_id"},
        )
    view = await CreateDataset(container.data_services()).execute(
        CreateDatasetCommand(
            actor=caller.actor,
            workspace_id=payload.workspace_id or "",
            project_id=payload.project_id,
            name=payload.name,
            kind=parse_enum(DatasetKind, payload.kind, field="kind"),
            description=payload.description,
            reference_build_declared=parse_enum(
                ReferenceBuildDeclaration,
                payload.reference_build_declared,
                field="reference_build_declared",
            ),
            request=context,
        )
    )
    return dataset_response(view)


@router.get(
    "",
    response_model=DatasetCollection,
    summary="List datasets in a workspace or project",
    responses=ERROR_RESPONSES,
)
async def list_datasets(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
    workspace_id: Annotated[str | None, Query()] = None,
    project_id: Annotated[str | None, Query()] = None,
    query: Annotated[str | None, Query(max_length=200)] = None,
    include_archived: Annotated[bool, Query()] = False,
) -> DatasetCollection:
    paged = await ListDatasets(container.data_services()).execute(
        ListDatasetsQuery(
            actor=caller.actor,
            page=page,
            request=context,
            workspace_id=workspace_id,
            project_id=project_id,
            query=query,
            include_archived=include_archived,
        )
    )
    return dataset_collection(paged)


@router.get(
    "/{dataset_id}",
    response_model=DatasetResponse,
    summary="Get a dataset",
    responses=ERROR_RESPONSES,
)
async def get_dataset(
    dataset_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> DatasetResponse:
    view = await GetDataset(container.data_services()).execute(
        GetDatasetQuery(actor=caller.actor, dataset_id=dataset_id, request=context)
    )
    return dataset_response(view)


@router.patch(
    "/{dataset_id}",
    response_model=DatasetResponse,
    summary="Update dataset descriptive metadata",
    responses=ERROR_RESPONSES,
)
async def update_dataset(
    dataset_id: str,
    payload: DatasetUpdatePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> DatasetResponse:
    view = await UpdateDataset(container.data_services()).execute(
        UpdateDatasetCommand(
            actor=caller.actor,
            dataset_id=dataset_id,
            name=payload.name,
            description=payload.description,
            request=context,
        )
    )
    return dataset_response(view)


@router.post(
    "/{dataset_id}/state",
    response_model=DatasetResponse,
    summary="Request a dataset lifecycle transition",
    responses=ERROR_RESPONSES,
)
async def change_dataset_state(
    dataset_id: str,
    payload: DatasetLifecyclePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> DatasetResponse:
    view = await ChangeDatasetState(container.data_services()).execute(
        ChangeDatasetStateCommand(
            actor=caller.actor,
            dataset_id=dataset_id,
            target_state=parse_enum(DatasetState, payload.target_state, field="target_state"),
            reason=payload.reason,
            request=context,
        )
    )
    return dataset_response(view)


@router.delete(
    "/{dataset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a dataset into its retention window",
    responses=ERROR_RESPONSES,
)
async def soft_delete_dataset(
    dataset_id: str,
    payload: DatasetDeletePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> None:
    await SoftDeleteDataset(container.data_services()).execute(
        SoftDeleteDatasetCommand(
            actor=caller.actor,
            dataset_id=dataset_id,
            reason=payload.reason,
            request=context,
        )
    )


# --------------------------------------------------------------------------- #
# Versions                                                                    #
# --------------------------------------------------------------------------- #


@router.post(
    "/{dataset_id}/versions",
    response_model=DatasetVersionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Open a new dataset version",
    responses=ERROR_RESPONSES,
)
async def create_dataset_version(
    dataset_id: str,
    payload: DatasetVersionCreatePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> DatasetVersionResponse:
    view = await CreateDatasetVersion(container.data_services()).execute(
        CreateDatasetVersionCommand(
            actor=caller.actor,
            dataset_id=dataset_id,
            notes=payload.notes,
            reference_build_declared=(
                parse_enum(
                    ReferenceBuildDeclaration,
                    payload.reference_build_declared,
                    field="reference_build_declared",
                )
                if payload.reference_build_declared
                else None
            ),
            request=context,
        )
    )
    return dataset_version_response(view)


@router.get(
    "/{dataset_id}/versions",
    response_model=DatasetVersionCollection,
    summary="List dataset versions",
    responses=ERROR_RESPONSES,
)
async def list_dataset_versions(
    dataset_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
) -> DatasetVersionCollection:
    paged = await ListDatasetVersions(container.data_services()).execute(
        ListDatasetVersionsQuery(
            actor=caller.actor, dataset_id=dataset_id, page=page, request=context
        )
    )
    return dataset_version_collection(paged)


@router.get(
    "/{dataset_id}/imports",
    response_model=ImportSessionCollection,
    summary="List import sessions for a dataset",
    responses=ERROR_RESPONSES,
)
async def list_dataset_imports(
    dataset_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
) -> ImportSessionCollection:
    paged = await ListImportSessions(container.data_services()).execute(
        ListImportSessionsQuery(
            actor=caller.actor, dataset_id=dataset_id, page=page, request=context
        )
    )
    return import_session_collection(paged)


@versions_router.get(
    "/{version_id}",
    response_model=DatasetVersionResponse,
    summary="Get a dataset version",
    responses=ERROR_RESPONSES,
)
async def get_dataset_version(
    version_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> DatasetVersionResponse:
    view = await GetDatasetVersion(container.data_services()).execute(
        GetDatasetVersionQuery(actor=caller.actor, version_id=version_id, request=context)
    )
    return dataset_version_response(view)


@versions_router.post(
    "/{version_id}/decision",
    response_model=DatasetVersionResponse,
    summary="Accept or reject a validated dataset version",
    responses=ERROR_RESPONSES,
)
async def decide_dataset_version(
    version_id: str,
    payload: DatasetVersionDecisionPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> DatasetVersionResponse:
    view = await DecideDatasetVersion(container.data_services()).execute(
        DecideDatasetVersionCommand(
            actor=caller.actor,
            version_id=version_id,
            accept=payload.accept,
            reason=payload.reason,
            request=context,
        )
    )
    return dataset_version_response(view)


# --------------------------------------------------------------------------- #
# Uploads                                                                     #
# --------------------------------------------------------------------------- #


@versions_router.post(
    "/{version_id}/uploads",
    response_model=UploadTicketResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Open an upload session and receive a short-lived transfer grant",
    responses=ERROR_RESPONSES,
)
async def open_upload_session(
    version_id: str,
    payload: UploadSessionCreatePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> UploadTicketResponse:
    ticket = await OpenUploadSession(container.data_services()).execute(
        OpenUploadSessionCommand(
            actor=caller.actor,
            version_id=version_id,
            filename=payload.filename,
            size_bytes=payload.size_bytes,
            declared_format=(
                parse_enum(InputFormat, payload.declared_format, field="declared_format")
                if payload.declared_format
                else None
            ),
            checksum_algorithm=parse_enum(
                ChecksumAlgorithm, payload.checksum_algorithm, field="checksum_algorithm"
            ),
            checksum_value=payload.checksum_value,
            content_type=payload.content_type,
            request=context,
        )
    )
    return upload_ticket_response(ticket)


@uploads_router.post(
    "/{session_id}/complete",
    response_model=UploadSessionResponse,
    summary="Declare the transfer finished; queues verification",
    responses=ERROR_RESPONSES,
)
async def complete_upload(
    session_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> UploadSessionResponse:
    view = await CompleteUpload(container.data_services()).execute(
        CompleteUploadCommand(actor=caller.actor, session_id=session_id, request=context)
    )
    return upload_session_response(view)


@uploads_router.post(
    "/{session_id}/cancel",
    response_model=UploadSessionResponse,
    summary="Cancel an upload session",
    responses=ERROR_RESPONSES,
)
async def cancel_upload(
    session_id: str,
    payload: UploadCancelPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> UploadSessionResponse:
    view = await CancelUploadSession(container.data_services()).execute(
        CancelUploadSessionCommand(
            actor=caller.actor,
            session_id=session_id,
            reason=payload.reason,
            request=context,
        )
    )
    return upload_session_response(view)


@artifacts_router.post(
    "/{artifact_id}/download",
    response_model=DownloadGrantResponse,
    summary="Request a short-lived download grant for a verified artifact",
    responses=ERROR_RESPONSES,
)
async def request_artifact_download(
    artifact_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> DownloadGrantResponse:
    grant = await IssueArtifactDownload(container.data_services()).execute(
        IssueArtifactDownloadCommand(
            actor=caller.actor, artifact_id=artifact_id, request=context
        )
    )
    return download_grant_response(grant)


# --------------------------------------------------------------------------- #
# Imports                                                                     #
# --------------------------------------------------------------------------- #


@artifacts_router.post(
    "/{artifact_id}/imports",
    response_model=ImportSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Open an import session for a verified artifact",
    responses=ERROR_RESPONSES,
)
async def open_import_session(
    artifact_id: str,
    payload: ImportSessionCreatePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ImportSessionResponse:
    if payload.file_artifact_id != artifact_id:
        raise ValidationError(
            "the artifact in the path and the body must match",
            details={"field": "file_artifact_id"},
        )
    view = await OpenImportSession(container.data_services()).execute(
        OpenImportSessionCommand(
            actor=caller.actor,
            artifact_id=artifact_id,
            idempotency_key=payload.idempotency_key,
            request=context,
        )
    )
    return import_session_response(view)


@imports_router.get(
    "/{session_id}",
    response_model=ImportSessionResponse,
    summary="Get an import session with its column mappings",
    responses=ERROR_RESPONSES,
)
async def get_import_session(
    session_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ImportSessionResponse:
    view = await GetImportSession(container.data_services()).execute(
        GetImportSessionQuery(actor=caller.actor, session_id=session_id, request=context)
    )
    return import_session_response(view)


@imports_router.put(
    "/{session_id}/mapping",
    response_model=ImportSessionResponse,
    summary="Confirm the column mapping for an import",
    responses=ERROR_RESPONSES,
)
async def confirm_column_mapping(
    session_id: str,
    payload: ColumnMappingConfirmPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ImportSessionResponse:
    decisions = tuple(
        ColumnMappingRequest(
            source_column_index=item.source_column_index,
            source_column_name=item.source_column_name,
            target_concept=parse_enum(
                FieldConcept, item.target_concept, field="target_concept"
            ),
            declared_unit=item.declared_unit,
            notes=item.notes,
        )
        for item in payload.mappings
    )
    view = await ConfirmColumnMapping(container.data_services()).execute(
        ConfirmColumnMappingCommand(
            actor=caller.actor,
            session_id=session_id,
            decisions=decisions,
            request=context,
        )
    )
    return import_session_response(view)


@imports_router.post(
    "/{session_id}/submit",
    response_model=ImportSessionResponse,
    summary="Submit a confirmed import for durable execution",
    responses=ERROR_RESPONSES,
)
async def submit_import(
    session_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ImportSessionResponse:
    view = await SubmitImport(container.data_services()).execute(
        SubmitImportCommand(actor=caller.actor, session_id=session_id, request=context)
    )
    return import_session_response(view)


@imports_router.post(
    "/{session_id}/abandon",
    response_model=ImportSessionResponse,
    summary="Abandon an import session",
    responses=ERROR_RESPONSES,
)
async def abandon_import(
    session_id: str,
    payload: ImportAbandonPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ImportSessionResponse:
    view = await AbandonImportSession(container.data_services()).execute(
        AbandonImportSessionCommand(
            actor=caller.actor,
            session_id=session_id,
            reason=payload.reason,
            request=context,
        )
    )
    return import_session_response(view)


# --------------------------------------------------------------------------- #
# Validation                                                                  #
# --------------------------------------------------------------------------- #


@validation_router.get(
    "/runs",
    response_model=ValidationRunCollection,
    summary="List validation runs for a subject",
    responses=ERROR_RESPONSES,
)
async def list_validation_runs(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
    subject_type: Annotated[str, Query(description=f"One of: {sorted(SUBJECT_TYPES)}")],
    subject_id: Annotated[str, Query()],
) -> ValidationRunCollection:
    paged = await ListValidationRuns(container.data_services()).execute(
        ListValidationRunsQuery(
            actor=caller.actor,
            subject_type=subject_type,
            subject_id=subject_id,
            page=page,
            request=context,
        )
    )
    return validation_run_collection(paged)


@validation_router.get(
    "/runs/{run_id}",
    response_model=ValidationRunResponse,
    summary="Get a validation run with a page of its issues",
    responses=ERROR_RESPONSES,
)
async def get_validation_run(
    run_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
) -> ValidationRunResponse:
    view = await GetValidationRun(container.data_services()).execute(
        GetValidationRunQuery(actor=caller.actor, run_id=run_id, page=page, request=context)
    )
    return validation_run_response(view)


__all__ = [
    "artifacts_router",
    "imports_router",
    "router",
    "uploads_router",
    "validation_router",
    "versions_router",
]
