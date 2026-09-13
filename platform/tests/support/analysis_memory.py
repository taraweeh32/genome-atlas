"""In-memory doubles for the Package 5 orchestration repositories.

Same intent as the other memory doubles: the ports are protocols, so analysis
definition, configuration versioning, execution lifecycle, job claiming/leasing/
retrying and scheduling can be exercised for real without PostgreSQL.

The job double is deliberately *not* a convenience stub. It models the
properties the SQL repository guarantees, because those properties are what the
tests are about:

* a claim is exclusive — a second worker polling concurrently gets a different
  job, or nothing;
* lease-bound writes only apply while the claiming worker still owns the job;
* recovery re-queues an expired lease, or dead-letters it when the attempt
  budget is spent;
* enqueue is idempotent on ``idempotency_key``.

Optimistic concurrency is modelled faithfully: a save whose version does not
match raises ``ConcurrencyConflictError``, exactly as the SQL repositories do.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from app.application.repositories import Page, Paged
from app.domain.analysis.entities import (
    AnalysisConfigurationVersion,
    AnalysisDefinition,
    AnalysisExecutionRecord,
    AnalysisSchedule,
    ComputeNode,
    ConfigurationInput,
    ExecutionInput,
    JobAttemptRecord,
    JobRecord,
    ScheduleTrigger,
    ScientificArtifactRecord,
    ScientificExecutionRecord,
)
from app.domain.errors import ConcurrencyConflictError
from app.domain.lifecycle import ACTIVE_EXECUTION_STATES
from app.domain.value_objects.enums import (
    AnalysisState,
    DeletionState,
    ExecutionState,
    JobErrorClass,
    JobKind,
    JobQueue,
    JobState,
    NodeClass,
    NodeHealthState,
    ScheduleState,
    ScheduleTriggerOutcome,
)
from tests.support.data_memory import MemoryJobs, RecordedJob

_TERMINAL_JOB_STATES = (
    JobState.SUCCEEDED,
    JobState.FAILED,
    JobState.CANCELLED,
    JobState.DEAD_LETTER,
)


def _paged(items: list, page: Page) -> Paged:
    window = items[page.offset : page.offset + page.size]
    return Paged(items=tuple(window), total=len(items), page=page)


@dataclass
class MemoryAnalyses:
    rows: dict[str, AnalysisDefinition] = field(default_factory=dict)

    async def add(self, analysis: AnalysisDefinition) -> AnalysisDefinition:
        self.rows[analysis.id] = analysis
        return analysis

    async def get(self, analysis_id: str) -> AnalysisDefinition | None:
        return self.rows.get(analysis_id)

    async def save(self, analysis: AnalysisDefinition) -> AnalysisDefinition:
        stored = self.rows.get(analysis.id)
        if stored is None or stored.version != analysis.version:
            raise ConcurrencyConflictError(
                "the resource changed since it was read; re-read and retry",
                details={"resource_id": analysis.id},
            )
        updated = replace(analysis, version=analysis.version + 1)
        self.rows[analysis.id] = updated
        return updated

    async def name_exists(self, *, project_id: str, name: str) -> bool:
        target = name.strip().lower()
        return any(
            row.project_id == project_id
            and row.name.strip().lower() == target
            and row.deletion_state is DeletionState.ACTIVE
            for row in self.rows.values()
        )

    async def list_for_scope(
        self,
        *,
        workspace_ids: tuple[str, ...],
        page: Page,
        project_id: str | None = None,
        states: tuple[AnalysisState, ...] = (),
        query: str | None = None,
    ) -> Paged[AnalysisDefinition]:
        if not workspace_ids:
            return Paged(items=(), total=0, page=page)
        items = [
            row
            for row in self.rows.values()
            if row.workspace_id in workspace_ids
            and row.deletion_state is DeletionState.ACTIVE
            and (project_id is None or row.project_id == project_id)
            and (not states or row.state in states)
            and (query is None or query.strip().lower() in row.name.lower())
        ]
        items.sort(key=lambda row: row.name)
        return _paged(items, page)


@dataclass
class MemoryAnalysisConfigurations:
    rows: dict[str, AnalysisConfigurationVersion] = field(default_factory=dict)
    inputs: list[ConfigurationInput] = field(default_factory=list)

    async def add(
        self, configuration: AnalysisConfigurationVersion
    ) -> AnalysisConfigurationVersion:
        self.rows[configuration.id] = configuration
        return configuration

    async def get(self, configuration_id: str) -> AnalysisConfigurationVersion | None:
        return self.rows.get(configuration_id)

    async def record_validation(
        self, configuration: AnalysisConfigurationVersion
    ) -> AnalysisConfigurationVersion:
        stored = self.rows[configuration.id]
        self.rows[configuration.id] = replace(
            stored,
            validation_state=configuration.validation_state,
            validation_findings=configuration.validation_findings,
            content_hash=configuration.content_hash,
        )
        return self.rows[configuration.id]

    async def next_version_number(self, analysis_id: str) -> int:
        existing = [row.version_number for row in self.rows.values() if row.analysis_id == analysis_id]
        return (max(existing) if existing else 0) + 1

    async def list_for_analysis(
        self, analysis_id: str, *, page: Page
    ) -> Paged[AnalysisConfigurationVersion]:
        items = sorted(
            (row for row in self.rows.values() if row.analysis_id == analysis_id),
            key=lambda row: row.version_number,
            reverse=True,
        )
        return _paged(list(items), page)

    async def add_inputs(self, inputs: tuple[ConfigurationInput, ...]) -> None:
        self.inputs.extend(inputs)

    async def list_inputs(self, configuration_id: str) -> tuple[ConfigurationInput, ...]:
        return tuple(
            item for item in self.inputs if item.analysis_configuration_id == configuration_id
        )


@dataclass
class MemoryAnalysisExecutions:
    rows: dict[str, AnalysisExecutionRecord] = field(default_factory=dict)
    inputs: list[ExecutionInput] = field(default_factory=list)

    async def add(self, execution: AnalysisExecutionRecord) -> AnalysisExecutionRecord:
        self.rows[execution.id] = execution
        return execution

    async def get(self, execution_id: str) -> AnalysisExecutionRecord | None:
        return self.rows.get(execution_id)

    async def save(self, execution: AnalysisExecutionRecord) -> AnalysisExecutionRecord:
        stored = self.rows[execution.id]
        # History is not rewritable: the request-time facts stay as stored.
        self.rows[execution.id] = replace(
            execution,
            attempt_sequence=stored.attempt_sequence,
            requested_at=stored.requested_at,
            requested_by=stored.requested_by,
            configuration_snapshot=stored.configuration_snapshot,
        )
        return self.rows[execution.id]

    async def find_by_idempotency_key(self, key: str) -> AnalysisExecutionRecord | None:
        for row in self.rows.values():
            if row.idempotency_key == key:
                return row
        return None

    async def next_attempt_sequence(self, analysis_id: str) -> int:
        existing = [
            row.attempt_sequence for row in self.rows.values() if row.analysis_id == analysis_id
        ]
        return (max(existing) if existing else 0) + 1

    async def count_active_for_analysis(self, analysis_id: str) -> int:
        return sum(
            1
            for row in self.rows.values()
            if row.analysis_id == analysis_id and row.state in ACTIVE_EXECUTION_STATES
        )

    async def list_for_scope(
        self,
        *,
        workspace_ids: tuple[str, ...],
        page: Page,
        analysis_id: str | None = None,
        project_id: str | None = None,
        states: tuple[ExecutionState, ...] = (),
    ) -> Paged[AnalysisExecutionRecord]:
        if not workspace_ids:
            return Paged(items=(), total=0, page=page)
        items = [
            row
            for row in self.rows.values()
            if row.workspace_id in workspace_ids
            and (analysis_id is None or row.analysis_id == analysis_id)
            and (project_id is None or row.project_id == project_id)
            and (not states or row.state in states)
        ]
        items.sort(key=lambda row: row.requested_at, reverse=True)
        return _paged(items, page)

    async def add_inputs(self, inputs: tuple[ExecutionInput, ...]) -> None:
        self.inputs.extend(inputs)

    async def list_inputs(self, execution_id: str) -> tuple[ExecutionInput, ...]:
        return tuple(item for item in self.inputs if item.analysis_execution_id == execution_id)


@dataclass
class MemorySchedules:
    rows: dict[str, AnalysisSchedule] = field(default_factory=dict)
    triggers: list[ScheduleTrigger] = field(default_factory=list)

    async def add(self, schedule: AnalysisSchedule) -> AnalysisSchedule:
        self.rows[schedule.id] = schedule
        return schedule

    async def get(self, schedule_id: str) -> AnalysisSchedule | None:
        return self.rows.get(schedule_id)

    async def save(self, schedule: AnalysisSchedule) -> AnalysisSchedule:
        stored = self.rows.get(schedule.id)
        if stored is None or stored.version != schedule.version:
            raise ConcurrencyConflictError(
                "the resource changed since it was read; re-read and retry",
                details={"resource_id": schedule.id},
            )
        updated = replace(schedule, version=schedule.version + 1)
        self.rows[schedule.id] = updated
        return updated

    async def name_exists(self, *, owner_scope: str, owner_id: str | None, name: str) -> bool:
        return any(
            row.owner_scope == owner_scope
            and row.owner_id == owner_id
            and row.name == name.strip()
            for row in self.rows.values()
        )

    async def list_for_scope(
        self,
        *,
        workspace_ids: tuple[str, ...],
        page: Page,
        project_id: str | None = None,
        states: tuple[ScheduleState, ...] = (),
    ) -> Paged[AnalysisSchedule]:
        if not workspace_ids:
            return Paged(items=(), total=0, page=page)
        items = [
            row
            for row in self.rows.values()
            if row.workspace_id in workspace_ids
            and (project_id is None or row.project_id == project_id)
            and (not states or row.state in states)
        ]
        items.sort(key=lambda row: row.name)
        return _paged(items, page)

    async def list_due(self, *, now: datetime, limit: int = 25) -> tuple[AnalysisSchedule, ...]:
        items = [
            row
            for row in self.rows.values()
            if row.state is ScheduleState.ENABLED
            and row.next_execution_at is not None
            and row.next_execution_at <= now
        ]
        items.sort(key=lambda row: row.next_execution_at or now)
        return tuple(items[:limit])

    async def record_trigger(self, trigger: ScheduleTrigger) -> ScheduleTrigger | None:
        if any(
            existing.schedule_id == trigger.schedule_id
            and existing.scheduled_for == trigger.scheduled_for
            for existing in self.triggers
        ):
            return None
        self.triggers.append(trigger)
        return trigger

    async def finalize_trigger(
        self,
        *,
        schedule_id: str,
        scheduled_for: datetime,
        outcome: ScheduleTriggerOutcome,
        analysis_execution_id: str | None = None,
        job_id: str | None = None,
        detail: dict | None = None,
    ) -> None:
        for index, existing in enumerate(self.triggers):
            if existing.schedule_id == schedule_id and existing.scheduled_for == scheduled_for:
                self.triggers[index] = replace(
                    existing,
                    outcome=outcome,
                    analysis_execution_id=analysis_execution_id,
                    job_id=job_id,
                    detail=detail or {},
                )
                return

    async def list_triggers(self, schedule_id: str, *, page: Page) -> Paged[ScheduleTrigger]:
        items = sorted(
            (row for row in self.triggers if row.schedule_id == schedule_id),
            key=lambda row: row.scheduled_for,
            reverse=True,
        )
        return _paged(list(items), page)


@dataclass
class MemoryComputeNodes:
    rows: dict[str, ComputeNode] = field(default_factory=dict)

    async def upsert(self, node: ComputeNode) -> ComputeNode:
        existing = await self.get_by_key(node.node_key)
        if existing is not None:
            merged = replace(
                node,
                id=existing.id,
                version=existing.version,
                active_job_count=existing.active_job_count,
            )
            self.rows[existing.id] = merged
            return merged
        self.rows[node.id] = node
        return node

    async def get_by_key(self, node_key: str) -> ComputeNode | None:
        for row in self.rows.values():
            if row.node_key == node_key:
                return row
        return None

    async def get(self, node_id: str) -> ComputeNode | None:
        return self.rows.get(node_id)

    async def save(self, node: ComputeNode) -> ComputeNode:
        stored = self.rows.get(node.id)
        if stored is None or stored.version != node.version:
            raise ConcurrencyConflictError(
                "the resource changed since it was read; re-read and retry",
                details={"resource_id": node.id},
            )
        updated = replace(node, version=node.version + 1)
        self.rows[node.id] = updated
        return updated

    async def list_nodes(
        self, *, node_class: NodeClass | None = None, page: Page | None = None
    ) -> tuple[ComputeNode, ...]:
        items = [
            row
            for row in self.rows.values()
            if node_class is None or row.node_class is node_class
        ]
        items.sort(key=lambda row: row.node_key)
        if page is not None:
            items = items[page.offset : page.offset + page.size]
        return tuple(items)

    async def mark_unhealthy_before(self, *, threshold: datetime) -> int:
        affected = 0
        for node_id, row in list(self.rows.items()):
            if (
                row.heartbeat_at is not None
                and row.heartbeat_at < threshold
                and row.health_state is not NodeHealthState.UNAVAILABLE
            ):
                self.rows[node_id] = replace(row, health_state=NodeHealthState.UNAVAILABLE)
                affected += 1
        return affected


@dataclass
class MemoryScientificExecutions:
    rows: dict[str, ScientificExecutionRecord] = field(default_factory=dict)
    artifacts: list[ScientificArtifactRecord] = field(default_factory=list)

    async def record_artifacts(
        self, artifacts: tuple[ScientificArtifactRecord, ...]
    ) -> tuple[ScientificArtifactRecord, ...]:
        known = {
            (item.scientific_execution_id, item.artifact_key) for item in self.artifacts
        }
        for artifact in artifacts:
            key = (artifact.scientific_execution_id, artifact.artifact_key)
            if key not in known:
                self.artifacts.append(artifact)
                known.add(key)
        return artifacts

    async def list_artifacts(
        self, scientific_execution_id: str
    ) -> tuple[ScientificArtifactRecord, ...]:
        return tuple(
            sorted(
                (
                    item
                    for item in self.artifacts
                    if item.scientific_execution_id == scientific_execution_id
                ),
                key=lambda item: item.artifact_key,
            )
        )

    async def add(self, record: ScientificExecutionRecord) -> ScientificExecutionRecord:
        self.rows[record.id] = record
        return record

    async def get(self, record_id: str) -> ScientificExecutionRecord | None:
        return self.rows.get(record_id)

    async def record_outcome(
        self, record: ScientificExecutionRecord
    ) -> ScientificExecutionRecord:
        stored = self.rows[record.id]
        self.rows[record.id] = replace(
            record,
            capability_key=stored.capability_key,
            submitted_at=stored.submitted_at,
            correlation_id=stored.correlation_id,
        )
        return self.rows[record.id]

    async def list_for_execution(
        self, analysis_execution_id: str
    ) -> tuple[ScientificExecutionRecord, ...]:
        return tuple(
            sorted(
                (
                    row
                    for row in self.rows.values()
                    if row.analysis_execution_id == analysis_execution_id
                ),
                key=lambda row: row.submitted_at,
            )
        )


@dataclass
class MemoryJobQueue(MemoryJobs):
    """A durable queue with the execution half modelled, not stubbed."""

    jobs: dict[str, JobRecord] = field(default_factory=dict)
    attempts: list[JobAttemptRecord] = field(default_factory=list)
    _sequence: int = 0

    async def enqueue(
        self,
        *,
        kind: JobKind,
        payload: dict[str, Any],
        correlation_id: str,
        queue: str = "default",
        priority: int = 100,
        workspace_id: str | None = None,
        project_id: str | None = None,
        requested_by: str | None = None,
        idempotency_key: str | None = None,
        available_at: datetime | None = None,
        max_attempts: int = 3,
        analysis_execution_id: str | None = None,
        scheduled_job_id: str | None = None,
        node_class: NodeClass = NodeClass.APPLICATION_WORKER,
        resource_requirements: dict[str, Any] | None = None,
        required_capabilities: tuple[str, ...] = (),
        lease_duration_seconds: int = 60,
        execution_context_ref: str | None = None,
    ) -> str:
        queue_value = queue.value if isinstance(queue, JobQueue) else queue
        if idempotency_key is not None:
            for existing in self.jobs.values():
                if existing.idempotency_key == idempotency_key:
                    return existing.id
        self._sequence += 1
        job_id = f"job_{self._sequence:032x}"
        self.jobs[job_id] = JobRecord(
            id=job_id,
            kind=kind,
            state=JobState.QUEUED,
            queue=JobQueue(queue_value),
            priority=priority,
            correlation_id=correlation_id,
            max_attempts=max_attempts,
            payload=dict(payload),
            workspace_id=workspace_id,
            project_id=project_id,
            analysis_execution_id=analysis_execution_id,
            scheduled_job_id=scheduled_job_id,
            requested_by=requested_by,
            idempotency_key=idempotency_key,
            execution_context_ref=execution_context_ref,
            available_at=available_at,
            lease_duration_seconds=lease_duration_seconds,
            resource_requirements=resource_requirements or {},
            required_capabilities=required_capabilities,
            node_class=node_class,
        )
        # Package 4 assertions read this enqueue log; keep it populated.
        self.recorded.append(
            RecordedJob(
                kind=kind,
                payload=dict(payload),
                correlation_id=correlation_id,
                queue=queue_value,
                priority=priority,
                workspace_id=workspace_id,
                project_id=project_id,
                requested_by=requested_by,
                idempotency_key=idempotency_key,
                available_at=available_at,
                max_attempts=max_attempts,
            )
        )
        return job_id

    async def get(self, job_id: str) -> dict[str, Any] | None:
        record = self.jobs.get(job_id)
        return {"id": record.id, "state": record.state.value} if record else None

    async def find(self, job_id: str) -> JobRecord | None:
        return self.jobs.get(job_id)

    async def claim_next(
        self,
        *,
        worker_id: str,
        queues: tuple[str, ...],
        node_class: NodeClass,
        kinds: tuple[JobKind, ...] = (),
        now: datetime,
        lease_expires_at: datetime,
        node_id: str | None = None,
    ) -> JobRecord | None:
        queue_values = {q.value if isinstance(q, JobQueue) else q for q in queues}
        candidates = [
            row
            for row in self.jobs.values()
            if row.state in (JobState.QUEUED, JobState.RETRY_WAITING)
            and row.queue.value in queue_values
            and row.node_class is node_class
            and row.cancellation_requested_at is None
            and (row.available_at is None or row.available_at <= now)
            and (not kinds or row.kind in kinds)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda row: (row.priority, row.id))
        chosen = candidates[0]
        claimed = replace(
            chosen,
            state=JobState.CLAIMED,
            claimed_at=now,
            claimed_by_worker_id=worker_id,
            assigned_node_id=node_id,
            lease_expires_at=lease_expires_at,
            heartbeat_at=now,
            attempt_number=chosen.attempt_number + 1,
            version=chosen.version + 1,
        )
        self.jobs[chosen.id] = claimed
        return claimed

    def _owned(self, job_id: str, worker_id: str) -> JobRecord | None:
        row = self.jobs.get(job_id)
        if row is None or row.claimed_by_worker_id != worker_id:
            return None
        return row

    async def mark_running(
        self, *, job_id: str, worker_id: str, now: datetime
    ) -> JobRecord | None:
        row = self._owned(job_id, worker_id)
        if row is None:
            return None
        updated = replace(
            row,
            state=JobState.RUNNING,
            started_at=row.started_at or now,
            heartbeat_at=now,
            version=row.version + 1,
        )
        self.jobs[job_id] = updated
        return updated

    async def heartbeat(
        self,
        *,
        job_id: str,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
        progress_percent: int | None = None,
        progress_message: str | None = None,
    ) -> JobRecord | None:
        row = self._owned(job_id, worker_id)
        if row is None:
            return None
        updated = replace(
            row,
            heartbeat_at=now,
            lease_expires_at=lease_expires_at,
            progress_percent=(
                progress_percent if progress_percent is not None else row.progress_percent
            ),
            progress_message=(
                progress_message if progress_message is not None else row.progress_message
            ),
            version=row.version + 1,
        )
        self.jobs[job_id] = updated
        return updated

    async def complete(self, *, job_id: str, worker_id: str, now: datetime) -> None:
        row = self._owned(job_id, worker_id)
        if row is None:
            return
        self.jobs[job_id] = replace(
            row,
            state=JobState.SUCCEEDED,
            completed_at=now,
            lease_expires_at=None,
            progress_percent=100,
            version=row.version + 1,
        )

    async def fail(
        self,
        *,
        job_id: str,
        worker_id: str,
        now: datetime,
        error_class: JobErrorClass,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        retry_at: datetime | None = None,
        dead_letter: bool = False,
    ) -> JobRecord | None:
        row = self._owned(job_id, worker_id)
        if row is None:
            return None
        if dead_letter or retry_at is None:
            updated = replace(
                row,
                state=JobState.DEAD_LETTER if dead_letter else JobState.FAILED,
                completed_at=now,
                lease_expires_at=None,
            )
        else:
            updated = replace(
                row,
                state=JobState.RETRY_WAITING,
                available_at=retry_at,
                claimed_at=None,
                claimed_by_worker_id=None,
                assigned_node_id=None,
                lease_expires_at=None,
            )
        updated = replace(
            updated,
            failure_code=code,
            failure_message=message,
            failure_details=details or {},
            error_class=error_class,
            version=row.version + 1,
        )
        self.jobs[job_id] = updated
        return updated

    async def request_cancellation(
        self, *, job_id: str, requested_by: str | None, now: datetime
    ) -> JobRecord | None:
        row = self.jobs.get(job_id)
        if row is None or row.state in _TERMINAL_JOB_STATES:
            return None
        updated = replace(
            row,
            state=JobState.CANCEL_REQUESTED,
            cancellation_requested_at=now,
            cancellation_requested_by=requested_by,
            version=row.version + 1,
        )
        self.jobs[job_id] = updated
        return updated

    async def mark_cancelled(self, *, job_id: str, now: datetime) -> JobRecord | None:
        row = self.jobs.get(job_id)
        if row is None:
            return None
        updated = replace(
            row,
            state=JobState.CANCELLED,
            completed_at=now,
            lease_expires_at=None,
            version=row.version + 1,
        )
        self.jobs[job_id] = updated
        return updated

    async def recover_stale(
        self, *, before: datetime, now: datetime, limit: int = 50
    ) -> tuple[JobRecord, ...]:
        recovered: list[JobRecord] = []
        for job_id, row in list(self.jobs.items()):
            if len(recovered) >= limit:
                break
            if (
                row.state
                not in (JobState.CLAIMED, JobState.RUNNING, JobState.CANCEL_REQUESTED)
                or row.lease_expires_at is None
                or row.lease_expires_at >= before
            ):
                continue
            exhausted = row.attempt_number >= row.max_attempts
            updated = replace(
                row,
                state=JobState.DEAD_LETTER if exhausted else JobState.QUEUED,
                completed_at=now if exhausted else None,
                available_at=None if exhausted else now,
                claimed_at=None,
                claimed_by_worker_id=None,
                assigned_node_id=None,
                lease_expires_at=None,
                failure_code="job.lease_expired",
                failure_message="the worker holding this job stopped reporting progress",
                error_class=JobErrorClass.TRANSIENT_INFRASTRUCTURE_ERROR,
                version=row.version + 1,
            )
            self.jobs[job_id] = updated
            recovered.append(updated)
        return tuple(recovered)

    async def add_attempt(self, attempt: JobAttemptRecord) -> JobAttemptRecord:
        self.attempts.append(attempt)
        return attempt

    async def list_attempts(self, job_id: str) -> tuple[JobAttemptRecord, ...]:
        return tuple(
            sorted(
                (row for row in self.attempts if row.job_id == job_id),
                key=lambda row: row.attempt_number,
            )
        )

    async def list_for_scope(
        self,
        *,
        workspace_ids: tuple[str, ...],
        page: Page,
        project_id: str | None = None,
        states: tuple[JobState, ...] = (),
        kinds: tuple[JobKind, ...] = (),
        queue: str | None = None,
    ) -> Paged[JobRecord]:
        if not workspace_ids:
            return Paged(items=(), total=0, page=page)
        items = [
            row
            for row in self.jobs.values()
            if row.workspace_id in workspace_ids
            and (project_id is None or row.project_id == project_id)
        ]
        return _paged(self._filtered(items, states, kinds, queue), page)

    async def list_all(
        self,
        *,
        page: Page,
        states: tuple[JobState, ...] = (),
        kinds: tuple[JobKind, ...] = (),
        queue: str | None = None,
    ) -> Paged[JobRecord]:
        return _paged(self._filtered(list(self.jobs.values()), states, kinds, queue), page)

    async def queue_statistics(self) -> tuple[dict[str, Any], ...]:
        totals: dict[tuple[str, str], int] = {}
        for row in self.jobs.values():
            key = (row.queue.value, row.state.value)
            totals[key] = totals.get(key, 0) + 1
        return tuple(
            {"queue": queue, "state": state, "total": total}
            for (queue, state), total in sorted(totals.items())
        )

    @staticmethod
    def _filtered(
        items: list[JobRecord],
        states: tuple[JobState, ...],
        kinds: tuple[JobKind, ...],
        queue: str | None,
    ) -> list[JobRecord]:
        queue_value = queue.value if isinstance(queue, JobQueue) else queue
        selected = [
            row
            for row in items
            if (not states or row.state in states)
            and (not kinds or row.kind in kinds)
            and (queue_value is None or row.queue.value == queue_value)
        ]
        selected.sort(key=lambda row: row.id, reverse=True)
        return selected


__all__ = [
    "MemoryAnalyses",
    "MemoryAnalysisConfigurations",
    "MemoryAnalysisExecutions",
    "MemoryComputeNodes",
    "MemoryJobQueue",
    "MemorySchedules",
    "MemoryScientificExecutions",
]
