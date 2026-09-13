"""Analysis executions.

Rules the backend owns here:

* Requesting an execution freezes the configuration into the execution row. A
  later configuration edit can never change what a past run used.
* The execution row and its durable job are written in the **same transaction**:
  a rolled-back request leaves no orphan job, and a committed request cannot
  lose its work.
* Idempotency is server-side: a repeated request carrying the same idempotency
  key returns the existing execution instead of starting a second run.
* Cancellation is a *request*. The worker stops the work; only the worker's
  observation turns it into ``cancelled``, so a completed run is never rewritten
  into a cancelled one.
* Re-running never mutates history: it creates a new execution with the next
  attempt sequence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.analysis.dependencies import (
    CANCEL,
    EXECUTE,
    READ,
    AnalysisServices,
    readable_workspace_scope,
    require_analysis_access,
)
from app.domain.analysis.entities import (
    AnalysisDefinition,
    AnalysisExecutionRecord,
    ExecutionInput,
    clamp_priority,
)
from app.domain.analysis.policies import (
    ResourceRequirements,
    default_queue_for,
    node_class_for,
)
from app.domain.authorization.context import ActorContext
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.events import EventType
from app.domain.value_objects.enums import (
    AnalysisState,
    AuditOutcome,
    ExecutionState,
    JobKind,
    JobQueue,
    ProjectState,
)
from app.infrastructure.persistence.repositories.base import new_id

EXECUTION_JOB_KIND = JobKind.ANALYSIS_EXECUTION


@dataclass(frozen=True, slots=True)
class ExecutionView:
    execution: AnalysisExecutionRecord
    inputs: tuple[ExecutionInput, ...] = ()
    analysis_name: str | None = None
    can_cancel: bool = False


def _resolve_queue(analysis: AnalysisDefinition, requested: JobQueue | None) -> JobQueue:
    if requested is not None:
        return requested
    configured = (analysis.execution_defaults or {}).get("queue")
    if configured:
        try:
            return JobQueue(configured)
        except ValueError:
            # A stored default that no longer exists must not silently route work
            # to an arbitrary queue.
            raise ValidationError(
                "the analysis execution defaults name an unknown queue",
                details={"field": "queue", "value": configured},
            ) from None
    return default_queue_for(EXECUTION_JOB_KIND)


def _resolve_priority(analysis: AnalysisDefinition, requested: int | None) -> int:
    if requested is not None:
        return clamp_priority(requested)
    return clamp_priority((analysis.execution_defaults or {}).get("priority"))


def _resolve_requirements(
    analysis: AnalysisDefinition, configuration_snapshot: dict[str, Any]
) -> ResourceRequirements:
    declared = (configuration_snapshot.get("execution") or {}).get("resources")
    if not declared:
        declared = (analysis.execution_defaults or {}).get("resources")
    return ResourceRequirements.from_mapping(declared)


@dataclass(frozen=True, slots=True)
class RequestExecutionCommand:
    actor: ActorContext
    analysis_id: str
    request: RequestContext
    configuration_id: str | None = None
    queue: JobQueue | None = None
    priority: int | None = None
    idempotency_key: str | None = None
    #: Set only by the scheduler when a recurring schedule fires.
    schedule_id: str | None = None
    scheduled_for: Any | None = None


class RequestExecution:
    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, command: RequestExecutionCommand) -> ExecutionView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            if command.idempotency_key:
                existing = await repositories.analysis_executions.find_by_idempotency_key(
                    command.idempotency_key
                )
                if existing is not None:
                    inputs = await repositories.analysis_executions.list_inputs(existing.id)
                    return ExecutionView(execution=existing, inputs=inputs)
            analysis = await repositories.analyses.get(command.analysis_id)
            if analysis is None or not analysis.is_active:
                raise NotFoundError("analysis", command.analysis_id)
            scope = await require_analysis_access(
                self._services,
                repositories,
                command.actor,
                analysis,
                action=EXECUTE,
                recorder=recorder,
                occurred_at=now,
            )
            project = await repositories.projects.get(analysis.project_id)
            if project is None or project.state is not ProjectState.ACTIVE:
                # No scientific work may start inside an archived or closed
                # project, whatever the caller's role is.
                raise ConflictError(
                    "the project is not active", details={"project_id": analysis.project_id}
                )
            if analysis.state is AnalysisState.ARCHIVED:
                raise ConflictError("an archived analysis cannot be executed")
            configuration_id = command.configuration_id or analysis.current_configuration_id
            if configuration_id is None:
                raise ValidationError(
                    "this analysis has no configuration to execute",
                    details={"field": "configuration_id"},
                )
            configuration = await repositories.analysis_configurations.get(configuration_id)
            if configuration is None or configuration.analysis_id != analysis.id:
                raise NotFoundError("analysis_configuration", configuration_id)
            if not configuration.is_valid:
                raise ValidationError(
                    "this configuration version did not pass validation",
                    details={"field": "configuration_id"},
                )
            declared_inputs = await repositories.analysis_configurations.list_inputs(
                configuration.id
            )
            if not declared_inputs:
                raise ValidationError(
                    "the configuration declares no inputs", details={"field": "configuration_id"}
                )

            snapshot = dict(configuration.snapshot or {})
            snapshot["configuration_id"] = configuration.id
            snapshot["configuration_version_number"] = configuration.version_number
            snapshot["content_hash"] = configuration.content_hash
            queue = _resolve_queue(analysis, command.queue)
            priority = _resolve_priority(analysis, command.priority)
            requirements = _resolve_requirements(analysis, snapshot)
            attempt_sequence = await repositories.analysis_executions.next_attempt_sequence(
                analysis.id
            )
            execution = AnalysisExecutionRecord(
                id=new_id("aex"),
                analysis_id=analysis.id,
                workspace_id=analysis.workspace_id,
                project_id=analysis.project_id,
                analysis_configuration_id=configuration.id,
                attempt_sequence=attempt_sequence,
                state=ExecutionState.REQUESTED,
                requested_at=now,
                correlation_id=command.request.correlation_id,
                requested_by=scope.actor.actor_id,
                configuration_snapshot=snapshot,
                capability_key=analysis.capability_key,
                queue=queue,
                priority=priority,
                resource_requirements=requirements.as_mapping(),
                idempotency_key=command.idempotency_key,
                schedule_id=command.schedule_id,
                scheduled_for=command.scheduled_for,
            )
            stored = await repositories.analysis_executions.add(execution)
            inputs = tuple(
                ExecutionInput(
                    id=new_id("aei"),
                    analysis_execution_id=stored.id,
                    dataset_version_id=item.dataset_version_id,
                    role=item.role,
                )
                for item in declared_inputs
            )
            await repositories.analysis_executions.add_inputs(inputs)

            # Same transaction as the execution row: this is the whole point of
            # a transactional outbox-style enqueue.
            job_id = await repositories.jobs.enqueue(
                kind=EXECUTION_JOB_KIND,
                payload={
                    "analysis_execution_id": stored.id,
                    "analysis_id": analysis.id,
                    "configuration_id": configuration.id,
                },
                correlation_id=stored.correlation_id,
                queue=queue.value,
                priority=priority,
                workspace_id=stored.workspace_id,
                project_id=stored.project_id,
                requested_by=scope.actor.actor_id,
                idempotency_key=(
                    f"analysis-execution:{stored.id}"
                    if command.idempotency_key is None
                    else f"analysis-execution:{command.idempotency_key}"
                ),
                max_attempts=self._services.retry.max_attempts,
                analysis_execution_id=stored.id,
                node_class=node_class_for(EXECUTION_JOB_KIND),
                resource_requirements=requirements.as_mapping(),
                required_capabilities=(
                    (analysis.capability_key,) if analysis.capability_key else ()
                ),
                lease_duration_seconds=self._services.lease.lease_seconds,
            )
            queued = await repositories.analysis_executions.save(stored.queued(job_id=job_id))
            await recorder.audit(
                action="analysis_execution.requested",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=scope.actor.actor_id,
                resource_type="analysis_execution",
                resource_id=queued.id,
                workspace_id=queued.workspace_id,
                project_id=queued.project_id,
                new_state=queued.state.value,
                detail={
                    "analysis_id": analysis.id,
                    "configuration_id": configuration.id,
                    "job_id": job_id,
                    "queue": queue.value,
                    "priority": priority,
                },
            )
            await recorder.event(
                event_type=EventType.ANALYSIS_EXECUTION_QUEUED,
                aggregate_type="analysis_execution",
                aggregate_id=queued.id,
                occurred_at=now,
                workspace_id=queued.workspace_id,
                payload={"analysis_id": analysis.id, "job_id": job_id},
            )
        return ExecutionView(execution=queued, inputs=inputs, analysis_name=analysis.name)


@dataclass(frozen=True, slots=True)
class CancelExecutionCommand:
    actor: ActorContext
    execution_id: str
    reason: str | None
    request: RequestContext


class CancelExecution:
    """Records the intent to stop; the worker performs the stop."""

    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, command: CancelExecutionCommand) -> ExecutionView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            execution = await repositories.analysis_executions.get(command.execution_id)
            if execution is None:
                raise NotFoundError("analysis_execution", command.execution_id)
            analysis = await repositories.analyses.get(execution.analysis_id)
            if analysis is None:
                raise NotFoundError("analysis_execution", command.execution_id)
            scope = await require_analysis_access(
                self._services,
                repositories,
                command.actor,
                analysis,
                action=CANCEL,
                recorder=recorder,
                occurred_at=now,
            )
            if execution.is_terminal:
                raise ConflictError(
                    "this execution already finished",
                    details={"state": execution.state.value},
                )
            requested = execution.cancellation_requested(
                at=now, by=scope.actor.actor_id, reason=command.reason
            )
            stored = await repositories.analysis_executions.save(requested)
            if execution.scheduled_job_id:
                await repositories.jobs.request_cancellation(
                    job_id=execution.scheduled_job_id,
                    requested_by=scope.actor.actor_id,
                    now=now,
                )
            await recorder.audit(
                action="analysis_execution.cancel_requested",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=scope.actor.actor_id,
                resource_type="analysis_execution",
                resource_id=stored.id,
                workspace_id=stored.workspace_id,
                project_id=stored.project_id,
                previous_state=execution.state.value,
                new_state=stored.state.value,
                reason=command.reason,
            )
            await recorder.event(
                event_type=EventType.ANALYSIS_EXECUTION_CANCEL_REQUESTED,
                aggregate_type="analysis_execution",
                aggregate_id=stored.id,
                occurred_at=now,
                workspace_id=stored.workspace_id,
            )
            inputs = await repositories.analysis_executions.list_inputs(stored.id)
        return ExecutionView(execution=stored, inputs=inputs, analysis_name=analysis.name)


@dataclass(frozen=True, slots=True)
class GetExecutionQuery:
    actor: ActorContext
    execution_id: str
    request: RequestContext


class GetExecution:
    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, query: GetExecutionQuery) -> ExecutionView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            execution = await repositories.analysis_executions.get(query.execution_id)
            if execution is None:
                raise NotFoundError("analysis_execution", query.execution_id)
            analysis = await repositories.analyses.get(execution.analysis_id)
            if analysis is None:
                raise NotFoundError("analysis_execution", query.execution_id)
            scope = await require_analysis_access(
                self._services,
                repositories,
                query.actor,
                analysis,
                action=READ,
                recorder=recorder,
                occurred_at=now,
            )
            inputs = await repositories.analysis_executions.list_inputs(execution.id)
            can_cancel = (
                not execution.is_terminal
                and CANCEL.project in scope.actor.project_capabilities(analysis.project_id)
            )
        return ExecutionView(
            execution=execution,
            inputs=inputs,
            analysis_name=analysis.name,
            can_cancel=can_cancel,
        )


@dataclass(frozen=True, slots=True)
class ExecutionProvenanceView:
    """Everything needed to say what this run actually used, and produced.

    Read-only and reconstructed from stored records only: nothing here is
    recomputed, so a later configuration edit or engine upgrade cannot change
    the answer for a historical run.
    """

    execution: ExecutionView
    scientific_executions: tuple[tuple[Any, tuple[Any, ...]], ...] = ()
    configuration_snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GetExecutionProvenanceQuery:
    actor: ActorContext
    execution_id: str
    request: RequestContext


class GetExecutionProvenance:
    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, query: GetExecutionProvenanceQuery) -> ExecutionProvenanceView:
        view = await GetExecution(self._services).execute(
            GetExecutionQuery(
                actor=query.actor, execution_id=query.execution_id, request=query.request
            )
        )
        async with self._services.unit_of_work.begin() as repositories:
            records = await repositories.scientific_executions.list_for_execution(
                query.execution_id
            )
            enriched_records = []
            for record in records:
                artifacts = await repositories.scientific_executions.list_artifacts(record.id)
                enriched_records.append((record, artifacts))
            enriched = tuple(enriched_records)
        return ExecutionProvenanceView(
            execution=view,
            scientific_executions=enriched,
            configuration_snapshot=dict(view.execution.configuration_snapshot),
        )


@dataclass(frozen=True, slots=True)
class ListExecutionsQuery:
    actor: ActorContext
    page: Page
    request: RequestContext
    analysis_id: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    states: tuple[ExecutionState, ...] = ()


class ListExecutions:
    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, query: ListExecutionsQuery) -> Paged[ExecutionView]:
        scope = readable_workspace_scope(query.actor, workspace_id=query.workspace_id)
        if not scope:
            return Paged(items=(), total=0, page=query.page)
        async with self._services.unit_of_work.begin() as repositories:
            page = await repositories.analysis_executions.list_for_scope(
                workspace_ids=scope,
                page=query.page,
                analysis_id=query.analysis_id,
                project_id=query.project_id,
                states=query.states,
            )
        views = tuple(
            ExecutionView(
                execution=execution,
                can_cancel=not execution.is_terminal
                and CANCEL.project in query.actor.project_capabilities(execution.project_id),
            )
            for execution in page.items
            if READ.project in query.actor.project_capabilities(execution.project_id)
            or READ.workspace in query.actor.workspace_capabilities(execution.workspace_id)
        )
        return Paged(items=views, total=page.total, page=page.page)


__all__ = [
    "CancelExecution",
    "CancelExecutionCommand",
    "ExecutionProvenanceView",
    "ExecutionView",
    "GetExecution",
    "GetExecutionProvenance",
    "GetExecutionProvenanceQuery",
    "GetExecutionQuery",
    "ListExecutions",
    "ListExecutionsQuery",
    "RequestExecution",
    "RequestExecutionCommand",
]
