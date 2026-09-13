"""Datasets and dataset versions.

Rules the backend owns here:

* A dataset lives in exactly one scope (a workspace, optionally narrowed to a
  project) and that scope is read from the dataset row, never from the request.
* A dataset is mutable metadata; a **version** is an immutable scientific input.
  Correcting an input never rewrites a version — it creates the next one and
  marks the previous one superseded, so results keep pointing at what produced
  them.
* Acceptance is a gate, not a formality: a version may only be accepted when its
  artifacts actually arrived, were scanned clean and carry a validation outcome
  that does not block acceptance.
* Archiving and soft deletion are separate lifecycles from the operational state,
  and neither destroys anything.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.data.dependencies import (
    CREATE,
    DELETE,
    READ,
    WRITE,
    DataServices,
    dataset_capabilities,
    require_dataset_access,
    resolve_scope,
)
from app.domain.authorization.context import ActorContext
from app.domain.authorization.permissions import Permission
from app.domain.data.entities import Dataset, DatasetVersion, FileArtifact, ValidationRun
from app.domain.errors import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.domain.events import EventType
from app.domain.lifecycle import require_transition
from app.domain.value_objects.enums import (
    AuditOutcome,
    DatasetKind,
    DatasetState,
    DatasetVersionState,
    DeletionState,
    FileValidationState,
    MalwareScanState,
    ReferenceBuildDeclaration,
)
from app.infrastructure.persistence.repositories.base import new_id

MAX_DATASET_NAME_LENGTH = 200


def clean_dataset_name(raw: str) -> str:
    name = " ".join((raw or "").split())
    if len(name) < 2:
        raise ValidationError(
            "a dataset name must be at least 2 characters", details={"field": "name"}
        )
    if len(name) > MAX_DATASET_NAME_LENGTH:
        raise ValidationError(
            f"a dataset name may be at most {MAX_DATASET_NAME_LENGTH} characters",
            details={"field": "name"},
        )
    return name


@dataclass(frozen=True, slots=True)
class DatasetView:
    dataset: Dataset
    capabilities: tuple[str, ...]
    version_count: int = 0


@dataclass(frozen=True, slots=True)
class DatasetVersionView:
    version: DatasetVersion
    artifacts: tuple[FileArtifact, ...]
    latest_validation: ValidationRun | None
    #: Server's answer to "could this be accepted right now, and if not why".
    acceptance_blocked_reason: str | None = None


def _acceptance_blocker(
    version: DatasetVersion,
    artifacts: tuple[FileArtifact, ...],
    validation: ValidationRun | None,
) -> str | None:
    """Why this version may not be accepted yet, or ``None`` when it may.

    Fails closed: an unscanned artifact, a missing validation run and an
    unavailable scanner all block acceptance. "Not checked" is never "fine".
    """
    if not artifacts:
        return "no_artifacts"
    for artifact in artifacts:
        if not artifact.is_retrievable:
            if artifact.scan_state is not MalwareScanState.CLEAN:
                return "scan_not_clean"
            return "upload_incomplete"
        if artifact.validation_state is FileValidationState.QUARANTINED:
            return "quarantined"
    if validation is None:
        return "not_validated"
    if validation.blocks_acceptance:
        return "validation_failed"
    if version.state not in (
        DatasetVersionState.VALIDATED,
        DatasetVersionState.VALIDATING,
    ):
        return "version_state_not_ready"
    return None


# --------------------------------------------------------------------------- #
# Dataset commands                                                            #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CreateDatasetCommand:
    actor: ActorContext
    workspace_id: str
    project_id: str | None
    name: str
    kind: DatasetKind
    description: str | None
    reference_build_declared: ReferenceBuildDeclaration
    request: RequestContext


class CreateDataset:
    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, command: CreateDatasetCommand) -> DatasetView:
        name = clean_dataset_name(command.name)
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            workspace_id = command.workspace_id
            project_id = command.project_id
            if project_id is not None:
                project = await repositories.projects.get(project_id)
                if project is None:
                    raise NotFoundError("project", project_id)
                # The dataset's workspace is the project's workspace, whatever the
                # client claimed: a caller cannot place a project's data into a
                # workspace it merely names.
                workspace_id = project.workspace_id
            scope = await resolve_scope(
                self._services,
                repositories,
                command.actor,
                workspace_id=workspace_id,
                project_id=project_id,
                action=CREATE,
                recorder=recorder,
                occurred_at=now,
            )
            workspace = await repositories.workspaces.get(workspace_id)
            if workspace is None:
                raise NotFoundError("workspace", workspace_id)
            if not workspace.is_usable:
                raise ConflictError("this workspace is not currently usable")
            if await repositories.datasets.name_exists(
                workspace_id=workspace_id, project_id=project_id, name=name
            ):
                raise ConflictError("a dataset with this name already exists in this scope")

            actor_id = scope.actor.actor_id
            if actor_id is None:  # pragma: no cover - permission check precedes
                raise AuthorizationError("authentication is required")

            dataset = await repositories.datasets.add(
                Dataset(
                    id=new_id("dst"),
                    workspace_id=workspace_id,
                    project_id=project_id,
                    name=name,
                    kind=command.kind,
                    state=DatasetState.DRAFT,
                    created_by=actor_id,
                    owner_user_id=actor_id,
                    description=command.description or None,
                    reference_build_declared=command.reference_build_declared,
                )
            )
            await recorder.audit(
                action="dataset.created",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=actor_id,
                resource_type="dataset",
                resource_id=dataset.id,
                organization_id=workspace.organization_id,
                workspace_id=workspace_id,
                project_id=project_id,
                new_state=dataset.state.value,
                detail={
                    "kind": dataset.kind.value,
                    "reference_build_declared": dataset.reference_build_declared.value,
                },
            )
            await recorder.event(
                event_type=EventType.DATASET_CREATED,
                aggregate_type="dataset",
                aggregate_id=dataset.id,
                occurred_at=now,
                workspace_id=workspace_id,
                idempotency_suffix=dataset.id,
            )
        return DatasetView(dataset=dataset, capabilities=dataset_capabilities(scope.actor, dataset))


@dataclass(frozen=True, slots=True)
class ListDatasetsQuery:
    actor: ActorContext
    page: Page
    request: RequestContext
    workspace_id: str | None = None
    project_id: str | None = None
    query: str | None = None
    include_archived: bool = False


class ListDatasets:
    """Lists only datasets in scopes the actor may actually read."""

    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, query: ListDatasetsQuery) -> Paged[DatasetView]:
        actor = query.actor
        readable = tuple(
            workspace_id
            for workspace_id in actor.workspaces
            if Permission.WORKSPACE_DATA_READ in actor.workspace_capabilities(workspace_id)
            and (query.workspace_id is None or workspace_id == query.workspace_id)
        )
        # Project data permissions are independent of workspace ones, so include
        # the workspaces reachable purely through a project membership too.
        project_workspaces = tuple(
            grant.workspace_id
            for project_id, grant in actor.projects.items()
            if Permission.PROJECT_DATA_READ in actor.project_capabilities(project_id)
            and (query.workspace_id is None or grant.workspace_id == query.workspace_id)
        )
        scope = tuple(dict.fromkeys(readable + project_workspaces))
        if not scope:
            return Paged(items=(), total=0, page=query.page)
        async with self._services.unit_of_work.begin() as repositories:
            page = await repositories.datasets.list_for_scope(
                workspace_ids=scope,
                page=query.page,
                project_id=query.project_id,
                query=query.query,
                include_archived=query.include_archived,
            )
        views = tuple(
            DatasetView(dataset=dataset, capabilities=dataset_capabilities(actor, dataset))
            for dataset in page.items
            if "read" in dataset_capabilities(actor, dataset)
        )
        return Paged(items=views, total=page.total, page=page.page)


@dataclass(frozen=True, slots=True)
class GetDatasetQuery:
    actor: ActorContext
    dataset_id: str
    request: RequestContext


class GetDataset:
    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, query: GetDatasetQuery) -> DatasetView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            dataset = await repositories.datasets.get(query.dataset_id)
            if dataset is None or not dataset.is_active:
                # Existence is not disclosed before authorization: an unknown id
                # and an unauthorized id are answered the same way.
                raise NotFoundError("dataset", query.dataset_id)
            scope = await require_dataset_access(
                self._services,
                repositories,
                query.actor,
                dataset,
                action=READ,
                recorder=recorder,
                occurred_at=now,
            )
            versions = await repositories.dataset_versions.list_for_dataset(
                dataset.id, page=Page(number=1, size=1)
            )
        return DatasetView(
            dataset=dataset,
            capabilities=dataset_capabilities(scope.actor, dataset),
            version_count=versions.total,
        )


@dataclass(frozen=True, slots=True)
class UpdateDatasetCommand:
    actor: ActorContext
    dataset_id: str
    name: str | None
    description: str | None
    request: RequestContext


class UpdateDataset:
    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, command: UpdateDatasetCommand) -> DatasetView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            dataset = await repositories.datasets.get(command.dataset_id)
            if dataset is None or not dataset.is_active:
                raise NotFoundError("dataset", command.dataset_id)
            scope = await require_dataset_access(
                self._services,
                repositories,
                command.actor,
                dataset,
                action=WRITE,
                recorder=recorder,
                occurred_at=now,
            )
            if dataset.state is DatasetState.ARCHIVED:
                raise ConflictError("an archived dataset cannot be edited")
            name = (
                clean_dataset_name(command.name) if command.name is not None else dataset.name
            )
            if name.lower() != dataset.name.lower() and await repositories.datasets.name_exists(
                workspace_id=dataset.workspace_id,
                project_id=dataset.project_id,
                name=name,
            ):
                raise ConflictError("a dataset with this name already exists in this scope")
            dataset = await repositories.datasets.save(
                replace(
                    dataset,
                    name=name,
                    description=(
                        command.description
                        if command.description is not None
                        else dataset.description
                    ),
                )
            )
            await recorder.audit(
                action="dataset.updated",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=scope.actor.actor_id,
                resource_type="dataset",
                resource_id=dataset.id,
                workspace_id=dataset.workspace_id,
                project_id=dataset.project_id,
            )
            await recorder.event(
                event_type=EventType.DATASET_UPDATED,
                aggregate_type="dataset",
                aggregate_id=dataset.id,
                occurred_at=now,
                workspace_id=dataset.workspace_id,
            )
        return DatasetView(dataset=dataset, capabilities=dataset_capabilities(scope.actor, dataset))


@dataclass(frozen=True, slots=True)
class ChangeDatasetStateCommand:
    actor: ActorContext
    dataset_id: str
    target_state: DatasetState
    reason: str | None
    request: RequestContext


class ChangeDatasetState:
    """Archive or restore a dataset.

    A rejected transition is a 409 from the domain's transition table, so the
    frontend can only ever *request* a move.
    """

    _EVENTS = {
        DatasetState.ARCHIVED: EventType.DATASET_ARCHIVED,
        DatasetState.READY: EventType.DATASET_RESTORED,
        DatasetState.DRAFT: EventType.DATASET_RESTORED,
    }

    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, command: ChangeDatasetStateCommand) -> DatasetView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            dataset = await repositories.datasets.get(command.dataset_id)
            if dataset is None or not dataset.is_active:
                raise NotFoundError("dataset", command.dataset_id)
            scope = await require_dataset_access(
                self._services,
                repositories,
                command.actor,
                dataset,
                action=WRITE,
                recorder=recorder,
                occurred_at=now,
            )
            previous = dataset.state
            target = require_transition("dataset", previous, command.target_state)
            dataset = await repositories.datasets.save(replace(dataset, state=target))
            await recorder.audit(
                action="dataset.state_changed",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=scope.actor.actor_id,
                resource_type="dataset",
                resource_id=dataset.id,
                workspace_id=dataset.workspace_id,
                project_id=dataset.project_id,
                previous_state=previous.value,
                new_state=dataset.state.value,
                reason=command.reason,
            )
            event_type = self._EVENTS.get(dataset.state)
            if event_type is not None:
                await recorder.event(
                    event_type=event_type,
                    aggregate_type="dataset",
                    aggregate_id=dataset.id,
                    occurred_at=now,
                    workspace_id=dataset.workspace_id,
                )
        return DatasetView(dataset=dataset, capabilities=dataset_capabilities(scope.actor, dataset))


@dataclass(frozen=True, slots=True)
class SoftDeleteDatasetCommand:
    actor: ActorContext
    dataset_id: str
    reason: str | None
    request: RequestContext


class SoftDeleteDataset:
    """Move a dataset into the retention lifecycle.

    Soft deletion is deliberately *not* physical deletion: objects stay in
    storage, versions stay immutable and lineage stays intact. Permanent deletion
    is a retention operation of its own, with its own authorization.
    """

    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, command: SoftDeleteDatasetCommand) -> None:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            dataset = await repositories.datasets.get(command.dataset_id)
            if dataset is None or not dataset.is_active:
                raise NotFoundError("dataset", command.dataset_id)
            scope = await require_dataset_access(
                self._services,
                repositories,
                command.actor,
                dataset,
                action=DELETE,
                recorder=recorder,
                occurred_at=now,
            )
            accepted = await repositories.dataset_versions.list_accepted(dataset.id)
            deletion_state = require_transition(
                "deletion", dataset.deletion_state, DeletionState.SOFT_DELETED
            )
            retention_days = self._services.config.application.default_result_retention_days
            await repositories.datasets.save(
                replace(
                    dataset,
                    deletion_state=deletion_state,
                    deleted_at=now,
                    deleted_by=scope.actor.actor_id,
                    retention_expires_at=now.replace(microsecond=0)
                    + _days(retention_days),
                )
            )
            await recorder.audit(
                action="dataset.soft_deleted",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=scope.actor.actor_id,
                resource_type="dataset",
                resource_id=dataset.id,
                workspace_id=dataset.workspace_id,
                project_id=dataset.project_id,
                previous_state=dataset.deletion_state.value,
                new_state=deletion_state.value,
                reason=command.reason,
                # Recorded because deleting a dataset that historical results
                # depend on is a governance-relevant fact, not a detail.
                detail={"accepted_version_count": len(accepted)},
            )
            await recorder.event(
                event_type=EventType.DATASET_SOFT_DELETED,
                aggregate_type="dataset",
                aggregate_id=dataset.id,
                occurred_at=now,
                workspace_id=dataset.workspace_id,
            )


def _days(count: int):  # noqa: ANN202 - tiny helper, timedelta import kept local
    from datetime import timedelta

    return timedelta(days=count)


# --------------------------------------------------------------------------- #
# Dataset versions                                                            #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class CreateDatasetVersionCommand:
    actor: ActorContext
    dataset_id: str
    notes: str | None
    reference_build_declared: ReferenceBuildDeclaration | None
    request: RequestContext


class CreateDatasetVersion:
    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, command: CreateDatasetVersionCommand) -> DatasetVersionView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            dataset = await repositories.datasets.get(command.dataset_id)
            if dataset is None or not dataset.is_active:
                raise NotFoundError("dataset", command.dataset_id)
            scope = await require_dataset_access(
                self._services,
                repositories,
                command.actor,
                dataset,
                action=WRITE,
                recorder=recorder,
                occurred_at=now,
            )
            if dataset.state is DatasetState.ARCHIVED:
                raise ConflictError("an archived dataset cannot receive new versions")
            actor_id = scope.actor.actor_id
            if actor_id is None:  # pragma: no cover
                raise AuthorizationError("authentication is required")
            number = await repositories.dataset_versions.next_version_number(dataset.id)
            version = await repositories.dataset_versions.add(
                DatasetVersion(
                    id=new_id("dsv"),
                    dataset_id=dataset.id,
                    version_number=number,
                    state=DatasetVersionState.CREATED,
                    created_by=actor_id,
                    reference_build_declared=(
                        command.reference_build_declared or dataset.reference_build_declared
                    ),
                    version_metadata={"notes": command.notes} if command.notes else {},
                )
            )
            await recorder.audit(
                action="dataset_version.created",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=actor_id,
                resource_type="dataset_version",
                resource_id=version.id,
                workspace_id=dataset.workspace_id,
                project_id=dataset.project_id,
                new_state=version.state.value,
                detail={"version_number": number},
            )
            await recorder.event(
                event_type=EventType.DATASET_VERSION_CREATED,
                aggregate_type="dataset_version",
                aggregate_id=version.id,
                occurred_at=now,
                workspace_id=dataset.workspace_id,
                idempotency_suffix=version.id,
            )
        return DatasetVersionView(version=version, artifacts=(), latest_validation=None,
                                  acceptance_blocked_reason="no_artifacts")


@dataclass(frozen=True, slots=True)
class ListDatasetVersionsQuery:
    actor: ActorContext
    dataset_id: str
    page: Page
    request: RequestContext


class ListDatasetVersions:
    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, query: ListDatasetVersionsQuery) -> Paged[DatasetVersionView]:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            dataset = await repositories.datasets.get(query.dataset_id)
            if dataset is None or not dataset.is_active:
                raise NotFoundError("dataset", query.dataset_id)
            await require_dataset_access(
                self._services,
                repositories,
                query.actor,
                dataset,
                action=READ,
                recorder=recorder,
                occurred_at=now,
            )
            page = await repositories.dataset_versions.list_for_dataset(
                dataset.id, page=query.page
            )
            views: list[DatasetVersionView] = []
            for version in page.items:
                artifacts = await repositories.file_artifacts.list_for_version(version.id)
                validation = await repositories.validation_runs.latest_for_subject(
                    subject_type="dataset_version", subject_id=version.id
                )
                views.append(
                    DatasetVersionView(
                        version=version,
                        artifacts=artifacts,
                        latest_validation=validation,
                        acceptance_blocked_reason=_acceptance_blocker(
                            version, artifacts, validation
                        ),
                    )
                )
        return Paged(items=tuple(views), total=page.total, page=page.page)


@dataclass(frozen=True, slots=True)
class GetDatasetVersionQuery:
    actor: ActorContext
    version_id: str
    request: RequestContext


class GetDatasetVersion:
    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, query: GetDatasetVersionQuery) -> DatasetVersionView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            version = await repositories.dataset_versions.get(query.version_id)
            if version is None:
                raise NotFoundError("dataset_version", query.version_id)
            dataset = await repositories.datasets.get(version.dataset_id)
            if dataset is None or not dataset.is_active:
                raise NotFoundError("dataset_version", query.version_id)
            await require_dataset_access(
                self._services,
                repositories,
                query.actor,
                dataset,
                action=READ,
                recorder=recorder,
                occurred_at=now,
            )
            artifacts = await repositories.file_artifacts.list_for_version(version.id)
            validation = await repositories.validation_runs.latest_for_subject(
                subject_type="dataset_version", subject_id=version.id
            )
        return DatasetVersionView(
            version=version,
            artifacts=artifacts,
            latest_validation=validation,
            acceptance_blocked_reason=_acceptance_blocker(version, artifacts, validation),
        )


@dataclass(frozen=True, slots=True)
class DecideDatasetVersionCommand:
    actor: ActorContext
    version_id: str
    accept: bool
    reason: str | None
    request: RequestContext


class DecideDatasetVersion:
    """Accept or reject a dataset version.

    Acceptance is what makes bytes usable as a scientific input, so it is
    re-checked here against the artifacts and the validation outcome rather than
    trusting whatever the UI displayed. Accepting a version supersedes the
    previously accepted one instead of mutating it.
    """

    def __init__(self, services: DataServices) -> None:
        self._services = services

    async def execute(self, command: DecideDatasetVersionCommand) -> DatasetVersionView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            version = await repositories.dataset_versions.get(command.version_id)
            if version is None:
                raise NotFoundError("dataset_version", command.version_id)
            dataset = await repositories.datasets.get(version.dataset_id)
            if dataset is None or not dataset.is_active:
                raise NotFoundError("dataset_version", command.version_id)
            scope = await require_dataset_access(
                self._services,
                repositories,
                command.actor,
                dataset,
                action=WRITE,
                recorder=recorder,
                occurred_at=now,
            )
            artifacts = await repositories.file_artifacts.list_for_version(version.id)
            validation = await repositories.validation_runs.latest_for_subject(
                subject_type="dataset_version", subject_id=version.id
            )
            previous_state = version.state

            if command.accept:
                blocker = _acceptance_blocker(version, artifacts, validation)
                if blocker is not None:
                    raise ConflictError(
                        "this version cannot be accepted yet",
                        details={"reason": blocker},
                    )
                state = require_transition(
                    "dataset_version", previous_state, DatasetVersionState.ACCEPTED
                )
                version = await repositories.dataset_versions.save(
                    replace(
                        version,
                        state=state,
                        accepted_at=now,
                        accepted_by=scope.actor.actor_id,
                    )
                )
                # Supersede the previously current version rather than editing it.
                for other in await repositories.dataset_versions.list_accepted(dataset.id):
                    if other.id == version.id:
                        continue
                    superseded = require_transition(
                        "dataset_version", other.state, DatasetVersionState.SUPERSEDED
                    )
                    await repositories.dataset_versions.save(
                        replace(
                            other,
                            state=superseded,
                            superseded_by_version_id=version.id,
                        )
                    )
                    await recorder.event(
                        event_type=EventType.DATASET_VERSION_SUPERSEDED,
                        aggregate_type="dataset_version",
                        aggregate_id=other.id,
                        occurred_at=now,
                        workspace_id=dataset.workspace_id,
                        payload={"superseded_by_version_id": version.id},
                        idempotency_suffix=version.id,
                    )
                dataset_state = (
                    require_transition("dataset", dataset.state, DatasetState.READY)
                    if dataset.state is not DatasetState.READY
                    else DatasetState.READY
                )
                await repositories.datasets.save(
                    replace(dataset, state=dataset_state, current_version_id=version.id)
                )
                event_type = EventType.DATASET_VERSION_ACCEPTED
                action = "dataset_version.accepted"
            else:
                if not command.reason:
                    raise ValidationError(
                        "a rejection reason is required", details={"field": "reason"}
                    )
                state = require_transition(
                    "dataset_version", previous_state, DatasetVersionState.REJECTED
                )
                version = await repositories.dataset_versions.save(
                    replace(
                        version,
                        state=state,
                        rejected_at=now,
                        rejection_reason=command.reason,
                    )
                )
                event_type = EventType.DATASET_VERSION_REJECTED
                action = "dataset_version.rejected"

            await recorder.audit(
                action=action,
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=scope.actor.actor_id,
                resource_type="dataset_version",
                resource_id=version.id,
                workspace_id=dataset.workspace_id,
                project_id=dataset.project_id,
                previous_state=previous_state.value,
                new_state=version.state.value,
                reason=command.reason,
                detail={
                    "validation_run_id": validation.id if validation else None,
                    "artifact_count": len(artifacts),
                },
            )
            await recorder.event(
                event_type=event_type,
                aggregate_type="dataset_version",
                aggregate_id=version.id,
                occurred_at=now,
                workspace_id=dataset.workspace_id,
                idempotency_suffix=version.state.value,
            )
        return DatasetVersionView(
            version=version,
            artifacts=artifacts,
            latest_validation=validation,
            acceptance_blocked_reason=None,
        )


__all__ = [
    "ChangeDatasetState",
    "ChangeDatasetStateCommand",
    "CreateDataset",
    "CreateDatasetCommand",
    "CreateDatasetVersion",
    "CreateDatasetVersionCommand",
    "DatasetVersionView",
    "DatasetView",
    "DecideDatasetVersion",
    "DecideDatasetVersionCommand",
    "GetDataset",
    "GetDatasetQuery",
    "GetDatasetVersion",
    "GetDatasetVersionQuery",
    "ListDatasetVersions",
    "ListDatasetVersionsQuery",
    "ListDatasets",
    "ListDatasetsQuery",
    "SoftDeleteDataset",
    "SoftDeleteDatasetCommand",
    "UpdateDataset",
    "UpdateDatasetCommand",
    "clean_dataset_name",
]
