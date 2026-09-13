"""Scheduled (recurring) analyses.

Rules the backend owns here:

* A schedule is a *request for future work*, never a running thing. Each firing
  creates a normal execution that goes through the same authorization, the same
  configuration snapshot and the same durable job as a manual run.
* The recurrence expression is validated up front against a small, total grammar
  and stored with its IANA time zone; every stored instant stays UTC.
* Enabling, disabling and archiving are audited transitions. Archiving is
  terminal; it never deletes the schedule's firing history.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.analysis.dependencies import (
    READ,
    SCHEDULE,
    AnalysisServices,
    readable_workspace_scope,
    require_analysis_access,
)
from app.domain.analysis.entities import AnalysisSchedule, ScheduleTrigger, clamp_priority
from app.domain.analysis.schedule import ScheduleExpression, resolve_timezone
from app.domain.authorization.context import ActorContext
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.events import EventType
from app.domain.value_objects.enums import (
    AuditOutcome,
    JobKind,
    JobQueue,
    MissedSchedulePolicy,
    ScheduleConcurrencyPolicy,
    ScheduleState,
)
from app.infrastructure.persistence.repositories.base import new_id

MAX_CATCH_UP = 5


@dataclass(frozen=True, slots=True)
class ScheduleView:
    schedule: AnalysisSchedule
    can_manage: bool = False


@dataclass(frozen=True, slots=True)
class CreateScheduleCommand:
    actor: ActorContext
    analysis_id: str
    name: str
    schedule_expression: str
    timezone_name: str
    request: RequestContext
    description: str | None = None
    configuration_id: str | None = None
    concurrency_policy: ScheduleConcurrencyPolicy = ScheduleConcurrencyPolicy.SKIP_IF_RUNNING
    missed_policy: MissedSchedulePolicy = MissedSchedulePolicy.SKIP
    queue: JobQueue | None = None
    priority: int | None = None
    catch_up_limit: int = 1
    enabled: bool = True


class CreateSchedule:
    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, command: CreateScheduleCommand) -> ScheduleView:
        name = " ".join((command.name or "").split())
        if len(name) < 2:
            raise ValidationError(
                "a schedule name must be at least 2 characters", details={"field": "name"}
            )
        if not 1 <= command.catch_up_limit <= MAX_CATCH_UP:
            raise ValidationError(
                f"catch_up_limit must be between 1 and {MAX_CATCH_UP}",
                details={"field": "catch_up_limit"},
            )
        expression = ScheduleExpression.parse(command.schedule_expression)
        # Validate the zone up front so a schedule can never be stored with a
        # time zone the platform cannot resolve later.
        resolve_timezone(command.timezone_name)
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
                action=SCHEDULE,
                recorder=recorder,
                occurred_at=now,
            )
            configuration_id = command.configuration_id or analysis.current_configuration_id
            if configuration_id is None:
                raise ValidationError(
                    "the analysis needs a configuration before it can be scheduled",
                    details={"field": "configuration_id"},
                )
            configuration = await repositories.analysis_configurations.get(configuration_id)
            if configuration is None or configuration.analysis_id != analysis.id:
                raise NotFoundError("analysis_configuration", configuration_id)
            if await repositories.schedules.name_exists(
                owner_scope="project", owner_id=analysis.project_id, name=name
            ):
                raise ConflictError(
                    "a schedule with this name already exists in the project",
                    details={"field": "name"},
                )
            state = ScheduleState.ENABLED if command.enabled else ScheduleState.DISABLED
            schedule = AnalysisSchedule(
                id=new_id("sch"),
                name=name,
                owner_scope="project",
                owner_id=analysis.project_id,
                job_kind=JobKind.ANALYSIS_EXECUTION,
                state=state,
                schedule_kind=expression.kind,
                schedule_expression=expression.raw,
                timezone_name=command.timezone_name,
                concurrency_policy=command.concurrency_policy,
                missed_policy=command.missed_policy,
                analysis_id=analysis.id,
                analysis_configuration_id=configuration.id,
                workspace_id=analysis.workspace_id,
                project_id=analysis.project_id,
                description=command.description,
                queue=command.queue or JobQueue.DEFAULT,
                priority=clamp_priority(command.priority),
                catch_up_limit=command.catch_up_limit,
                schedule_configuration={"expression": expression.raw},
                next_execution_at=(
                    expression.next_after(now, timezone_name=command.timezone_name)
                    if state is ScheduleState.ENABLED
                    else None
                ),
                created_by=scope.actor.actor_id,
                updated_by=scope.actor.actor_id,
            )
            stored = await repositories.schedules.add(schedule)
            await recorder.audit(
                action="schedule.created",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=scope.actor.actor_id,
                resource_type="schedule",
                resource_id=stored.id,
                workspace_id=stored.workspace_id,
                project_id=stored.project_id,
                new_state=stored.state.value,
                detail={
                    "analysis_id": analysis.id,
                    "expression": stored.schedule_expression,
                    "timezone": stored.timezone_name,
                },
            )
            await recorder.event(
                event_type=EventType.SCHEDULE_CREATED,
                aggregate_type="schedule",
                aggregate_id=stored.id,
                occurred_at=now,
                workspace_id=stored.workspace_id,
                payload={"analysis_id": analysis.id},
            )
        return ScheduleView(schedule=stored, can_manage=True)


@dataclass(frozen=True, slots=True)
class UpdateScheduleCommand:
    actor: ActorContext
    schedule_id: str
    request: RequestContext
    schedule_expression: str | None = None
    timezone_name: str | None = None
    priority: int | None = None
    catch_up_limit: int | None = None
    concurrency_policy: ScheduleConcurrencyPolicy | None = None
    missed_policy: MissedSchedulePolicy | None = None
    description: str | None = None


class UpdateSchedule:
    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, command: UpdateScheduleCommand) -> ScheduleView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            schedule, _analysis = await _load_manageable(
                self._services, repositories, command.actor, command.schedule_id, recorder, now
            )
            if schedule.state is ScheduleState.ARCHIVED:
                raise ConflictError("an archived schedule cannot be changed")
            updated = schedule
            if command.schedule_expression is not None or command.timezone_name is not None:
                expression = ScheduleExpression.parse(
                    command.schedule_expression or schedule.schedule_expression
                )
                timezone_name = command.timezone_name or schedule.timezone_name
                resolve_timezone(timezone_name)
                updated = replace(
                    updated,
                    schedule_kind=expression.kind,
                    schedule_expression=expression.raw,
                    timezone_name=timezone_name,
                    schedule_configuration={"expression": expression.raw},
                    next_execution_at=(
                        expression.next_after(now, timezone_name=timezone_name)
                        if updated.state is ScheduleState.ENABLED
                        else None
                    ),
                )
            if command.priority is not None:
                updated = replace(updated, priority=clamp_priority(command.priority))
            if command.catch_up_limit is not None:
                if not 1 <= command.catch_up_limit <= MAX_CATCH_UP:
                    raise ValidationError(
                        f"catch_up_limit must be between 1 and {MAX_CATCH_UP}",
                        details={"field": "catch_up_limit"},
                    )
                updated = replace(updated, catch_up_limit=command.catch_up_limit)
            if command.concurrency_policy is not None:
                updated = replace(updated, concurrency_policy=command.concurrency_policy)
            if command.missed_policy is not None:
                updated = replace(updated, missed_policy=command.missed_policy)
            if command.description is not None:
                updated = replace(updated, description=command.description)
            updated = replace(updated, updated_by=command.actor.actor_id)
            stored = await repositories.schedules.save(updated)
            await recorder.audit(
                action="schedule.updated",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="schedule",
                resource_id=stored.id,
                workspace_id=stored.workspace_id,
                project_id=stored.project_id,
                detail={"expression": stored.schedule_expression},
            )
            await recorder.event(
                event_type=EventType.SCHEDULE_UPDATED,
                aggregate_type="schedule",
                aggregate_id=stored.id,
                occurred_at=now,
                workspace_id=stored.workspace_id,
            )
        return ScheduleView(schedule=stored, can_manage=True)


@dataclass(frozen=True, slots=True)
class ChangeScheduleStateCommand:
    actor: ActorContext
    schedule_id: str
    target: ScheduleState
    request: RequestContext


class ChangeScheduleState:
    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, command: ChangeScheduleStateCommand) -> ScheduleView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            schedule, _ = await _load_manageable(
                self._services, repositories, command.actor, command.schedule_id, recorder, now
            )
            updated = schedule.with_state(command.target)
            if command.target is ScheduleState.ENABLED:
                expression = ScheduleExpression.parse(schedule.schedule_expression)
                # Re-enabling never replays the past: the next firing is computed
                # from now, not from the moment it was disabled.
                updated = updated.with_next_execution(
                    expression.next_after(now, timezone_name=schedule.timezone_name)
                )
            else:
                updated = updated.with_next_execution(None)
            stored = await repositories.schedules.save(
                replace(updated, updated_by=command.actor.actor_id)
            )
            event = {
                ScheduleState.ENABLED: EventType.SCHEDULE_ENABLED,
                ScheduleState.DISABLED: EventType.SCHEDULE_DISABLED,
                ScheduleState.ARCHIVED: EventType.SCHEDULE_ARCHIVED,
            }[command.target]
            await recorder.audit(
                action="schedule.state_changed",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="schedule",
                resource_id=stored.id,
                workspace_id=stored.workspace_id,
                project_id=stored.project_id,
                previous_state=schedule.state.value,
                new_state=stored.state.value,
            )
            await recorder.event(
                event_type=event,
                aggregate_type="schedule",
                aggregate_id=stored.id,
                occurred_at=now,
                workspace_id=stored.workspace_id,
            )
        return ScheduleView(schedule=stored, can_manage=True)


async def _load_manageable(
    services: AnalysisServices,
    repositories,
    actor: ActorContext,
    schedule_id: str,
    recorder: ActivityRecorder,
    now,
):
    schedule = await repositories.schedules.get(schedule_id)
    if schedule is None or schedule.analysis_id is None:
        raise NotFoundError("schedule", schedule_id)
    analysis = await repositories.analyses.get(schedule.analysis_id)
    if analysis is None or not analysis.is_active:
        raise NotFoundError("schedule", schedule_id)
    await require_analysis_access(
        services,
        repositories,
        actor,
        analysis,
        action=SCHEDULE,
        recorder=recorder,
        occurred_at=now,
    )
    return schedule, analysis


@dataclass(frozen=True, slots=True)
class ListSchedulesQuery:
    actor: ActorContext
    page: Page
    request: RequestContext
    workspace_id: str | None = None
    project_id: str | None = None
    states: tuple[ScheduleState, ...] = ()


class ListSchedules:
    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, query: ListSchedulesQuery) -> Paged[ScheduleView]:
        scope = readable_workspace_scope(query.actor, workspace_id=query.workspace_id)
        if not scope:
            return Paged(items=(), total=0, page=query.page)
        async with self._services.unit_of_work.begin() as repositories:
            page = await repositories.schedules.list_for_scope(
                workspace_ids=scope,
                page=query.page,
                project_id=query.project_id,
                states=query.states,
            )
        views = tuple(
            ScheduleView(
                schedule=schedule,
                can_manage=bool(
                    schedule.project_id
                    and SCHEDULE.project in query.actor.project_capabilities(schedule.project_id)
                ),
            )
            for schedule in page.items
            if (
                schedule.project_id
                and READ.project in query.actor.project_capabilities(schedule.project_id)
            )
            or (
                schedule.workspace_id
                and READ.workspace in query.actor.workspace_capabilities(schedule.workspace_id)
            )
        )
        return Paged(items=views, total=page.total, page=page.page)


@dataclass(frozen=True, slots=True)
class ListScheduleTriggersQuery:
    actor: ActorContext
    schedule_id: str
    page: Page
    request: RequestContext


class ListScheduleTriggers:
    """The firing history of one schedule, including skipped and failed slots."""

    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, query: ListScheduleTriggersQuery) -> Paged[ScheduleTrigger]:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            schedule = await repositories.schedules.get(query.schedule_id)
            if schedule is None or schedule.analysis_id is None:
                raise NotFoundError("schedule", query.schedule_id)
            analysis = await repositories.analyses.get(schedule.analysis_id)
            if analysis is None or not analysis.is_active:
                raise NotFoundError("schedule", query.schedule_id)
            await require_analysis_access(
                self._services,
                repositories,
                query.actor,
                analysis,
                action=READ,
                recorder=recorder,
                occurred_at=now,
            )
            return await repositories.schedules.list_triggers(schedule.id, page=query.page)


__all__ = [
    "ChangeScheduleState",
    "ChangeScheduleStateCommand",
    "CreateSchedule",
    "CreateScheduleCommand",
    "ListScheduleTriggers",
    "ListScheduleTriggersQuery",
    "ListSchedules",
    "ListSchedulesQuery",
    "ScheduleView",
    "UpdateSchedule",
    "UpdateScheduleCommand",
]
