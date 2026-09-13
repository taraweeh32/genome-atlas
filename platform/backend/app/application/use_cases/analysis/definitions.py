"""Analysis definitions.

Rules the backend owns here:

* An analysis lives in exactly one scope, read from its own row, never from the
  request.
* A definition carries no execution state. Running it does not change it; its
  ``state`` describes readiness to be run, not progress.
* A definition becomes ``ready`` only when it actually has a current
  configuration, so "runnable" is never merely asserted.
* Deletion is soft, retention-bounded and never destroys execution history.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.analysis.dependencies import (
    CREATE,
    DELETE,
    READ,
    UPDATE,
    AnalysisServices,
    analysis_capabilities,
    readable_workspace_scope,
    require_analysis_access,
    resolve_scope,
)
from app.domain.analysis.entities import AnalysisDefinition
from app.domain.authorization.context import ActorContext
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.events import EventType
from app.domain.value_objects.enums import AnalysisKind, AnalysisState, AuditOutcome
from app.infrastructure.persistence.repositories.base import new_id

MAX_ANALYSIS_NAME_LENGTH = 200


def clean_analysis_name(raw: str) -> str:
    name = " ".join((raw or "").split())
    if len(name) < 2:
        raise ValidationError(
            "an analysis name must be at least 2 characters", details={"field": "name"}
        )
    if len(name) > MAX_ANALYSIS_NAME_LENGTH:
        raise ValidationError(
            f"an analysis name may be at most {MAX_ANALYSIS_NAME_LENGTH} characters",
            details={"field": "name"},
        )
    return name


@dataclass(frozen=True, slots=True)
class AnalysisView:
    analysis: AnalysisDefinition
    capabilities: tuple[str, ...]
    configuration_count: int = 0
    active_execution_count: int = 0


@dataclass(frozen=True, slots=True)
class CreateAnalysisCommand:
    actor: ActorContext
    workspace_id: str
    project_id: str
    name: str
    kind: AnalysisKind
    description: str | None
    capability_key: str | None
    request: RequestContext


class CreateAnalysis:
    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, command: CreateAnalysisCommand) -> AnalysisView:
        name = clean_analysis_name(command.name)
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            project = await repositories.projects.get(command.project_id)
            if project is None or (
                command.workspace_id and project.workspace_id != command.workspace_id
            ):
                raise NotFoundError("project", command.project_id)
            # The owning workspace is read from the stored project, never taken
            # from the request: a caller cannot place an analysis elsewhere.
            scope = await resolve_scope(
                self._services,
                repositories,
                command.actor,
                workspace_id=project.workspace_id,
                project_id=command.project_id,
                action=CREATE,
                recorder=recorder,
                occurred_at=now,
            )
            if await repositories.analyses.name_exists(
                project_id=command.project_id, name=name
            ):
                raise ConflictError(
                    "an analysis with this name already exists in the project",
                    details={"field": "name"},
                )
            analysis = AnalysisDefinition(
                id=new_id("anl"),
                workspace_id=scope.workspace_id,
                project_id=command.project_id,
                name=name,
                kind=command.kind,
                state=AnalysisState.DRAFT,
                created_by=scope.actor.actor_id,
                # Creator and owner are separate facts; the creator is recorded
                # as the initial owner but the two never collapse into one field.
                owner_user_id=scope.actor.actor_id,
                capability_key=command.capability_key,
                description=command.description,
            )
            stored = await repositories.analyses.add(analysis)
            await recorder.audit(
                action="analysis.created",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=scope.actor.actor_id,
                resource_type="analysis",
                resource_id=stored.id,
                workspace_id=stored.workspace_id,
                project_id=stored.project_id,
                new_state=stored.state.value,
            )
            await recorder.event(
                event_type=EventType.ANALYSIS_CREATED,
                aggregate_type="analysis",
                aggregate_id=stored.id,
                occurred_at=now,
                workspace_id=stored.workspace_id,
                payload={"kind": stored.kind.value, "project_id": stored.project_id},
            )
        return AnalysisView(
            analysis=stored, capabilities=analysis_capabilities(scope.actor, stored)
        )


@dataclass(frozen=True, slots=True)
class UpdateAnalysisCommand:
    actor: ActorContext
    analysis_id: str
    request: RequestContext
    name: str | None = None
    description: str | None = None
    capability_key: str | None = None
    execution_defaults: dict | None = None


class UpdateAnalysis:
    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, command: UpdateAnalysisCommand) -> AnalysisView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            analysis = await repositories.analyses.get(command.analysis_id)
            if analysis is None or not analysis.is_active:
                raise NotFoundError("analysis", command.analysis_id)
            scope = await require_analysis_access(
                self._services,
                repositories,
                command.actor,
                analysis,
                action=UPDATE,
                recorder=recorder,
                occurred_at=now,
            )
            updated = analysis
            if command.name is not None:
                name = clean_analysis_name(command.name)
                if name != analysis.name and await repositories.analyses.name_exists(
                    project_id=analysis.project_id, name=name
                ):
                    raise ConflictError(
                        "an analysis with this name already exists in the project",
                        details={"field": "name"},
                    )
                updated = updated.rename(
                    name=name,
                    description=command.description
                    if command.description is not None
                    else analysis.description,
                )
            elif command.description is not None:
                updated = updated.rename(name=analysis.name, description=command.description)
            if command.capability_key is not None:
                updated = replace(updated, capability_key=command.capability_key)
            if command.execution_defaults is not None:
                updated = updated.with_execution_defaults(command.execution_defaults)
            stored = await repositories.analyses.save(updated)
            await recorder.audit(
                action="analysis.updated",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=scope.actor.actor_id,
                resource_type="analysis",
                resource_id=stored.id,
                workspace_id=stored.workspace_id,
                project_id=stored.project_id,
            )
            await recorder.event(
                event_type=EventType.ANALYSIS_UPDATED,
                aggregate_type="analysis",
                aggregate_id=stored.id,
                occurred_at=now,
                workspace_id=stored.workspace_id,
            )
        return AnalysisView(
            analysis=stored, capabilities=analysis_capabilities(scope.actor, stored)
        )


@dataclass(frozen=True, slots=True)
class ChangeAnalysisStateCommand:
    actor: ActorContext
    analysis_id: str
    target: AnalysisState
    request: RequestContext


class ChangeAnalysisState:
    """Requests a definition-lifecycle transition; the server decides validity."""

    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, command: ChangeAnalysisStateCommand) -> AnalysisView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            analysis = await repositories.analyses.get(command.analysis_id)
            if analysis is None or not analysis.is_active:
                raise NotFoundError("analysis", command.analysis_id)
            scope = await require_analysis_access(
                self._services,
                repositories,
                command.actor,
                analysis,
                action=UPDATE,
                recorder=recorder,
                occurred_at=now,
            )
            if (
                command.target in (AnalysisState.READY, AnalysisState.ACTIVE)
                and analysis.current_configuration_id is None
            ):
                # Readiness is a fact about the definition, not a claim: without
                # a current configuration there is nothing to execute.
                raise ValidationError(
                    "an analysis needs a current configuration before it is ready",
                    details={"field": "state"},
                )
            stored = await repositories.analyses.save(analysis.with_state(command.target))
            await recorder.audit(
                action="analysis.state_changed",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=scope.actor.actor_id,
                resource_type="analysis",
                resource_id=stored.id,
                workspace_id=stored.workspace_id,
                project_id=stored.project_id,
                previous_state=analysis.state.value,
                new_state=stored.state.value,
            )
            if stored.state is AnalysisState.ARCHIVED:
                await recorder.event(
                    event_type=EventType.ANALYSIS_ARCHIVED,
                    aggregate_type="analysis",
                    aggregate_id=stored.id,
                    occurred_at=now,
                    workspace_id=stored.workspace_id,
                )
        return AnalysisView(
            analysis=stored, capabilities=analysis_capabilities(scope.actor, stored)
        )


@dataclass(frozen=True, slots=True)
class DeleteAnalysisCommand:
    actor: ActorContext
    analysis_id: str
    reason: str | None
    request: RequestContext


class DeleteAnalysis:
    """Soft deletion only.

    Execution history and its provenance are immutable scientific lineage: they
    are never removed with the definition, and a recoverable window is kept.
    """

    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, command: DeleteAnalysisCommand) -> None:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            analysis = await repositories.analyses.get(command.analysis_id)
            if analysis is None or not analysis.is_active:
                raise NotFoundError("analysis", command.analysis_id)
            scope = await require_analysis_access(
                self._services,
                repositories,
                command.actor,
                analysis,
                action=DELETE,
                recorder=recorder,
                occurred_at=now,
            )
            active = await repositories.analysis_executions.count_active_for_analysis(analysis.id)
            if active:
                raise ConflictError(
                    "this analysis still has executions in flight",
                    details={"active_executions": active},
                )
            deleted = analysis.soft_deleted(
                at=now,
                by=scope.actor.actor_id,
                retention_expires_at=now + timedelta(days=self._services.retention_days),
            )
            await repositories.analyses.save(deleted)
            await recorder.audit(
                action="analysis.soft_deleted",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=scope.actor.actor_id,
                resource_type="analysis",
                resource_id=analysis.id,
                workspace_id=analysis.workspace_id,
                project_id=analysis.project_id,
                reason=command.reason,
                new_state=deleted.deletion_state.value,
            )
            await recorder.event(
                event_type=EventType.ANALYSIS_SOFT_DELETED,
                aggregate_type="analysis",
                aggregate_id=analysis.id,
                occurred_at=now,
                workspace_id=analysis.workspace_id,
            )


@dataclass(frozen=True, slots=True)
class ListAnalysesQuery:
    actor: ActorContext
    page: Page
    request: RequestContext
    workspace_id: str | None = None
    project_id: str | None = None
    states: tuple[AnalysisState, ...] = ()
    query: str | None = None


class ListAnalyses:
    """Lists only analyses in scopes the actor may actually read."""

    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, query: ListAnalysesQuery) -> Paged[AnalysisView]:
        actor = query.actor
        scope = readable_workspace_scope(actor, workspace_id=query.workspace_id)
        if not scope:
            return Paged(items=(), total=0, page=query.page)
        async with self._services.unit_of_work.begin() as repositories:
            page = await repositories.analyses.list_for_scope(
                workspace_ids=scope,
                page=query.page,
                project_id=query.project_id,
                states=query.states,
                query=query.query,
            )
        views = tuple(
            AnalysisView(analysis=analysis, capabilities=analysis_capabilities(actor, analysis))
            for analysis in page.items
            if "read" in analysis_capabilities(actor, analysis)
        )
        return Paged(items=views, total=page.total, page=page.page)


@dataclass(frozen=True, slots=True)
class GetAnalysisQuery:
    actor: ActorContext
    analysis_id: str
    request: RequestContext


class GetAnalysis:
    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, query: GetAnalysisQuery) -> AnalysisView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            analysis = await repositories.analyses.get(query.analysis_id)
            if analysis is None or not analysis.is_active:
                # An unknown id and an unauthorized id are answered identically.
                raise NotFoundError("analysis", query.analysis_id)
            scope = await require_analysis_access(
                self._services,
                repositories,
                query.actor,
                analysis,
                action=READ,
                recorder=recorder,
                occurred_at=now,
            )
            configurations = await repositories.analysis_configurations.list_for_analysis(
                analysis.id, page=Page(number=1, size=1)
            )
            active = await repositories.analysis_executions.count_active_for_analysis(analysis.id)
        return AnalysisView(
            analysis=analysis,
            capabilities=analysis_capabilities(scope.actor, analysis),
            configuration_count=configurations.total,
            active_execution_count=active,
        )


__all__ = [
    "AnalysisView",
    "ChangeAnalysisState",
    "ChangeAnalysisStateCommand",
    "CreateAnalysis",
    "CreateAnalysisCommand",
    "DeleteAnalysis",
    "DeleteAnalysisCommand",
    "GetAnalysis",
    "GetAnalysisQuery",
    "ListAnalyses",
    "ListAnalysesQuery",
    "UpdateAnalysis",
    "UpdateAnalysisCommand",
    "clean_analysis_name",
]
