"""Job monitoring and job control.

Two audiences, one domain rule set:

* tenant users may observe and cancel the jobs belonging to work in *their* own
  scopes, and
* platform administration may observe and control any job, because the queue is
  operational infrastructure.

Neither audience may claim, lease or execute a job through the API: execution
belongs to workers only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.analysis.dependencies import (
    JOB_READ,
    AnalysisServices,
    readable_workspace_scope,
)
from app.domain.analysis.entities import JobAttemptRecord, JobRecord
from app.domain.authorization.context import ActorContext
from app.domain.authorization.permissions import Permission
from app.domain.errors import ConflictError, NotFoundError
from app.domain.events import EventType
from app.domain.value_objects.enums import AuditOutcome, JobKind, JobState


@dataclass(frozen=True, slots=True)
class JobView:
    job: JobRecord
    attempts: tuple[JobAttemptRecord, ...] = ()


def _visible_to_tenant(actor: ActorContext, job: JobRecord) -> bool:
    if job.project_id and JOB_READ.project in actor.project_capabilities(job.project_id):
        return True
    return bool(
        job.workspace_id and JOB_READ.workspace in actor.workspace_capabilities(job.workspace_id)
    )


@dataclass(frozen=True, slots=True)
class ListJobsQuery:
    actor: ActorContext
    page: Page
    request: RequestContext
    workspace_id: str | None = None
    project_id: str | None = None
    states: tuple[JobState, ...] = ()
    kinds: tuple[JobKind, ...] = ()
    queue: str | None = None


class ListJobs:
    """Tenant-scoped job listing. Never reveals another tenant's work."""

    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, query: ListJobsQuery) -> Paged[JobView]:
        scope = readable_workspace_scope(
            query.actor, workspace_id=query.workspace_id, action=JOB_READ
        )
        if not scope:
            return Paged(items=(), total=0, page=query.page)
        async with self._services.unit_of_work.begin() as repositories:
            page = await repositories.jobs.list_for_scope(
                workspace_ids=scope,
                page=query.page,
                project_id=query.project_id,
                states=query.states,
                kinds=query.kinds,
                queue=query.queue,
            )
        views = tuple(
            JobView(job=job) for job in page.items if _visible_to_tenant(query.actor, job)
        )
        return Paged(items=views, total=page.total, page=page.page)


@dataclass(frozen=True, slots=True)
class GetJobQuery:
    actor: ActorContext
    job_id: str
    request: RequestContext


class GetJob:
    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, query: GetJobQuery) -> JobView:
        async with self._services.unit_of_work.begin() as repositories:
            job = await repositories.jobs.find(query.job_id)
            if job is None:
                raise NotFoundError("job", query.job_id)
            platform_read = Permission.PLATFORM_JOB_READ in query.actor.platform_capabilities()
            if not platform_read:
                if job.project_id:
                    query_actor = await self._services.authorization.ensure_project_scope(
                        repositories, query.actor, job.project_id
                    )
                else:
                    query_actor = query.actor
                if not _visible_to_tenant(query_actor, job):
                    # Knowing a job id never grants sight of it.
                    raise NotFoundError("job", query.job_id)
            attempts = await repositories.jobs.list_attempts(job.id)
        return JobView(job=job, attempts=attempts)


@dataclass(frozen=True, slots=True)
class ListPlatformJobsQuery:
    actor: ActorContext
    page: Page
    request: RequestContext
    states: tuple[JobState, ...] = ()
    kinds: tuple[JobKind, ...] = ()
    queue: str | None = None


class ListPlatformJobs:
    """Platform-wide job listing. Requires an explicit platform capability."""

    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, query: ListPlatformJobsQuery) -> Paged[JobView]:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            await self._services.authorization.require(
                query.actor,
                Permission.PLATFORM_JOB_READ,
                recorder=recorder,
                occurred_at=now,
            )
            page = await repositories.jobs.list_all(
                page=query.page,
                states=query.states,
                kinds=query.kinds,
                queue=query.queue,
            )
        return Paged(
            items=tuple(JobView(job=job) for job in page.items),
            total=page.total,
            page=page.page,
        )


@dataclass(frozen=True, slots=True)
class CancelJobCommand:
    actor: ActorContext
    job_id: str
    reason: str | None
    request: RequestContext


class CancelJob:
    """Administrative cancellation request. The worker performs the stop."""

    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, command: CancelJobCommand) -> JobView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            await self._services.authorization.require(
                command.actor,
                Permission.PLATFORM_JOB_ADMINISTER,
                recorder=recorder,
                occurred_at=now,
            )
            job = await repositories.jobs.find(command.job_id)
            if job is None:
                raise NotFoundError("job", command.job_id)
            if job.is_terminal:
                raise ConflictError(
                    "this job already finished", details={"state": job.state.value}
                )
            updated = await repositories.jobs.request_cancellation(
                job_id=job.id, requested_by=command.actor.actor_id, now=now
            )
            if updated is None:
                raise ConflictError("this job could not be cancelled")
            if updated.analysis_execution_id:
                execution = await repositories.analysis_executions.get(
                    updated.analysis_execution_id
                )
                if execution is not None and not execution.is_terminal:
                    await repositories.analysis_executions.save(
                        execution.cancellation_requested(
                            at=now, by=command.actor.actor_id, reason=command.reason
                        )
                    )
            await recorder.audit(
                action="job.cancel_requested",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="job",
                resource_id=job.id,
                workspace_id=job.workspace_id,
                project_id=job.project_id,
                previous_state=job.state.value,
                new_state=updated.state.value,
                reason=command.reason,
            )
            await recorder.event(
                event_type=EventType.JOB_CANCEL_REQUESTED,
                aggregate_type="job",
                aggregate_id=job.id,
                occurred_at=now,
                workspace_id=job.workspace_id,
            )
        return JobView(job=updated)


@dataclass(frozen=True, slots=True)
class GetQueueStatisticsQuery:
    actor: ActorContext
    request: RequestContext


class GetQueueStatistics:
    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, query: GetQueueStatisticsQuery) -> tuple[dict[str, Any], ...]:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            await self._services.authorization.require(
                query.actor,
                Permission.PLATFORM_JOB_READ,
                recorder=recorder,
                occurred_at=now,
            )
            return await repositories.jobs.queue_statistics()


__all__ = [
    "CancelJob",
    "CancelJobCommand",
    "GetJob",
    "GetJobQuery",
    "GetQueueStatistics",
    "GetQueueStatisticsQuery",
    "JobView",
    "ListJobs",
    "ListJobsQuery",
    "ListPlatformJobs",
    "ListPlatformJobsQuery",
]
