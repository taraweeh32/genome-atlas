"""Durable job enqueue and concurrency-safe job execution.

Two halves, both authoritative in the database:

* **Enqueue** happens in the *same transaction* as the business change that
  asked for the work, so a rolled-back upload never leaves a job pointing at
  nothing, and a committed upload never loses its job.
* **Execution** is claimed, leased and completed with single atomic statements.
  Claiming uses ``FOR UPDATE SKIP LOCKED`` over an ordered candidate set, so N
  workers polling the same queue each get a different job and none of them
  blocks. The claim writes the lease in the same statement: a worker that dies
  without heartbeating loses the job when the lease expires, and
  ``recover_stale`` re-queues it (or dead-letters it once attempts run out)
  instead of leaving it "running" forever.

Nothing here decides *what* the work means: kinds, retry policy and handlers
live in the domain policy module and the worker fleet.

Jobs live in the ``platform`` schema because they are operational bookkeeping,
not domain state.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.application.repositories import Page, Paged
from app.domain.analysis.entities import JobAttemptRecord, JobRecord
from app.domain.value_objects.enums import (
    JobErrorClass,
    JobKind,
    JobQueue,
    JobState,
    NodeClass,
)
from app.infrastructure.persistence.models.jobs import Job as JobModel
from app.infrastructure.persistence.models.jobs import JobAttempt as JobAttemptModel
from app.infrastructure.persistence.repositories.base import SqlRepository, new_id

_JOBS = JobModel.__table__
_ATTEMPTS = JobAttemptModel.__table__

#: States a worker may take work from. ``stale`` is deliberately excluded:
#: recovery re-queues such jobs explicitly, it is not a claimable state.
_CLAIMABLE_STATES = (JobState.QUEUED.value, JobState.RETRY_WAITING.value)


def to_job(row: Mapping[str, Any]) -> JobRecord:
    return JobRecord(
        id=row["id"],
        kind=JobKind(row["kind"]),
        state=JobState(row["state"]),
        queue=JobQueue(row["queue"]),
        priority=row["priority"],
        correlation_id=row["correlation_id"],
        attempt_number=row["attempt_number"],
        max_attempts=row["max_attempts"],
        payload=row["payload"] or {},
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        analysis_execution_id=row["analysis_execution_id"],
        scientific_execution_id=row["scientific_execution_id"],
        scheduled_job_id=row["scheduled_job_id"],
        requested_by=row["requested_by"],
        idempotency_key=row["idempotency_key"],
        execution_context_ref=row["execution_context_ref"],
        available_at=row["available_at"],
        claimed_at=row["claimed_at"],
        claimed_by_worker_id=row["claimed_by_worker_id"],
        assigned_node_id=row["assigned_node_id"],
        lease_expires_at=row["lease_expires_at"],
        lease_duration_seconds=row["lease_duration_seconds"],
        heartbeat_at=row["heartbeat_at"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        cancellation_requested_at=row["cancellation_requested_at"],
        cancellation_requested_by=row["cancellation_requested_by"],
        progress_percent=row["progress_percent"],
        progress_message=row["progress_message"],
        failure_code=row["failure_code"],
        failure_message=row["failure_message"],
        failure_details=row["failure_details"] or {},
        error_class=JobErrorClass(row["error_class"]) if row["error_class"] else None,
        resource_requirements=row["resource_requirements"] or {},
        required_capabilities=tuple(row["required_capabilities"] or ()),
        node_class=NodeClass(row["node_class"]),
        causation_id=row["causation_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        version=row["version"],
    )


def to_attempt(row: Mapping[str, Any]) -> JobAttemptRecord:
    return JobAttemptRecord(
        id=row["id"],
        job_id=row["job_id"],
        attempt_number=row["attempt_number"],
        state=JobState(row["state"]),
        worker_id=row["worker_id"],
        node_id=row["node_id"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        failure_code=row["failure_code"],
        failure_message=row["failure_message"],
        error_class=JobErrorClass(row["error_class"]) if row["error_class"] else None,
        diagnostics=row["diagnostics"] or {},
    )


class SqlJobRepository(SqlRepository):
    # ------------------------------------------------------------------ enqueue

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
        job_id = new_id("job")
        queue_value = queue.value if isinstance(queue, JobQueue) else queue
        values = {
            "id": job_id,
            "kind": kind.value,
            "state": JobState.QUEUED.value,
            "queue": queue_value,
            "priority": priority,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "analysis_execution_id": analysis_execution_id,
            "scheduled_job_id": scheduled_job_id,
            "payload": payload,
            "requested_by": requested_by,
            "idempotency_key": idempotency_key,
            "available_at": available_at,
            "max_attempts": max_attempts,
            "node_class": node_class.value,
            "resource_requirements": resource_requirements or {},
            "required_capabilities": list(required_capabilities),
            "lease_duration_seconds": lease_duration_seconds,
            "execution_context_ref": execution_context_ref,
            "correlation_id": correlation_id,
            "version": 1,
        }
        if idempotency_key is None:
            await self._session.execute(insert(_JOBS).values(**values))
            return job_id
        # Idempotent enqueue: a retried request re-uses the existing job instead
        # of duplicating the work.
        statement = (
            pg_insert(_JOBS)
            .values(**values)
            .on_conflict_do_nothing(index_elements=[_JOBS.c.idempotency_key])
            .returning(_JOBS.c.id)
        )
        result = await self._session.execute(statement)
        inserted = result.scalar_one_or_none()
        if inserted is not None:
            return str(inserted)
        existing = await self._fetch_one(
            select(_JOBS.c.id).where(_JOBS.c.idempotency_key == idempotency_key)
        )
        return str(existing["id"]) if existing else job_id

    async def get(self, job_id: str) -> dict[str, Any] | None:
        return await self._fetch_one(select(_JOBS).where(_JOBS.c.id == job_id))

    async def find(self, job_id: str) -> JobRecord | None:
        row = await self.get(job_id)
        return to_job(row) if row else None

    # ---------------------------------------------------------------- execution

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
        """Atomically take the highest-priority available job, or return None.

        The candidate select locks with ``SKIP LOCKED`` so concurrent workers
        never contend on, or double-claim, the same row.
        """
        if not queues:
            return None
        queue_values = [q.value if isinstance(q, JobQueue) else q for q in queues]
        candidates = (
            select(_JOBS.c.id)
            .where(
                _JOBS.c.state.in_(_CLAIMABLE_STATES),
                _JOBS.c.queue.in_(queue_values),
                _JOBS.c.node_class == node_class.value,
                _JOBS.c.cancellation_requested_at.is_(None),
                (_JOBS.c.available_at.is_(None)) | (_JOBS.c.available_at <= now),
            )
            .order_by(_JOBS.c.priority.asc(), _JOBS.c.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if kinds:
            candidates = candidates.where(_JOBS.c.kind.in_([k.value for k in kinds]))
        claimed = (
            update(_JOBS)
            .where(_JOBS.c.id.in_(candidates.scalar_subquery()))
            .values(
                state=JobState.CLAIMED.value,
                claimed_at=now,
                claimed_by_worker_id=worker_id,
                assigned_node_id=node_id,
                lease_expires_at=lease_expires_at,
                heartbeat_at=now,
                attempt_number=_JOBS.c.attempt_number + 1,
                version=_JOBS.c.version + 1,
            )
            .returning(_JOBS)
        )
        result = await self._session.execute(claimed)
        row = result.mappings().first()
        return to_job(dict(row)) if row is not None else None

    async def mark_running(
        self, *, job_id: str, worker_id: str, now: datetime
    ) -> JobRecord | None:
        return await self._owned_update(
            job_id=job_id,
            worker_id=worker_id,
            values={
                "state": JobState.RUNNING.value,
                "started_at": func.coalesce(_JOBS.c.started_at, now),
                "heartbeat_at": now,
            },
        )

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
        """Extend the lease *only* while this worker still holds the claim.

        Returning ``None`` tells the worker it lost the job (its lease expired
        and recovery re-queued it) so it must stop rather than keep writing.
        """
        values: dict[str, Any] = {"heartbeat_at": now, "lease_expires_at": lease_expires_at}
        if progress_percent is not None:
            values["progress_percent"] = progress_percent
        if progress_message is not None:
            values["progress_message"] = progress_message
        return await self._owned_update(job_id=job_id, worker_id=worker_id, values=values)

    async def complete(self, *, job_id: str, worker_id: str, now: datetime) -> None:
        await self._owned_update(
            job_id=job_id,
            worker_id=worker_id,
            values={
                "state": JobState.SUCCEEDED.value,
                "completed_at": now,
                "lease_expires_at": None,
                "progress_percent": 100,
            },
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
        if dead_letter or retry_at is None:
            state = JobState.DEAD_LETTER.value if dead_letter else JobState.FAILED.value
            values: dict[str, Any] = {
                "state": state,
                "completed_at": now,
                "lease_expires_at": None,
            }
        else:
            values = {
                "state": JobState.RETRY_WAITING.value,
                "available_at": retry_at,
                "claimed_at": None,
                "claimed_by_worker_id": None,
                "assigned_node_id": None,
                "lease_expires_at": None,
            }
        values |= {
            "failure_code": code,
            "failure_message": message,
            "failure_details": details or {},
            "error_class": error_class.value,
        }
        return await self._owned_update(job_id=job_id, worker_id=worker_id, values=values)

    async def request_cancellation(
        self, *, job_id: str, requested_by: str | None, now: datetime
    ) -> JobRecord | None:
        """Cancellation is cooperative for running work, immediate for waiting work."""
        result = await self._session.execute(
            update(_JOBS)
            .where(
                _JOBS.c.id == job_id,
                _JOBS.c.state.notin_(
                    (
                        JobState.SUCCEEDED.value,
                        JobState.FAILED.value,
                        JobState.CANCELLED.value,
                        JobState.DEAD_LETTER.value,
                    )
                ),
            )
            .values(
                state=JobState.CANCEL_REQUESTED.value,
                cancellation_requested_at=now,
                cancellation_requested_by=requested_by,
                version=_JOBS.c.version + 1,
            )
            .returning(_JOBS)
        )
        row = result.mappings().first()
        return to_job(dict(row)) if row is not None else None

    async def mark_cancelled(self, *, job_id: str, now: datetime) -> JobRecord | None:
        result = await self._session.execute(
            update(_JOBS)
            .where(_JOBS.c.id == job_id)
            .values(
                state=JobState.CANCELLED.value,
                completed_at=now,
                lease_expires_at=None,
                version=_JOBS.c.version + 1,
            )
            .returning(_JOBS)
        )
        row = result.mappings().first()
        return to_job(dict(row)) if row is not None else None

    async def recover_stale(
        self, *, before: datetime, now: datetime, limit: int = 50
    ) -> tuple[JobRecord, ...]:
        """Re-queue or dead-letter jobs whose lease expired without a heartbeat."""
        candidates = (
            select(_JOBS.c.id, _JOBS.c.attempt_number, _JOBS.c.max_attempts)
            .where(
                _JOBS.c.state.in_(
                    (
                        JobState.CLAIMED.value,
                        JobState.RUNNING.value,
                        JobState.CANCEL_REQUESTED.value,
                    )
                ),
                _JOBS.c.lease_expires_at.isnot(None),
                _JOBS.c.lease_expires_at < before,
            )
            .order_by(_JOBS.c.lease_expires_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = await self._fetch_all(candidates)
        recovered: list[JobRecord] = []
        for row in rows:
            exhausted = int(row["attempt_number"]) >= int(row["max_attempts"])
            values: dict[str, Any] = {
                "failure_code": "job.lease_expired",
                "failure_message": "the worker holding this job stopped reporting progress",
                "error_class": JobErrorClass.INFRASTRUCTURE.value,
                "claimed_at": None,
                "claimed_by_worker_id": None,
                "assigned_node_id": None,
                "lease_expires_at": None,
                "version": _JOBS.c.version + 1,
            }
            if exhausted:
                values |= {"state": JobState.DEAD_LETTER.value, "completed_at": now}
            else:
                values |= {"state": JobState.QUEUED.value, "available_at": now}
            result = await self._session.execute(
                update(_JOBS).where(_JOBS.c.id == row["id"]).values(**values).returning(_JOBS)
            )
            updated = result.mappings().first()
            if updated is not None:
                recovered.append(to_job(dict(updated)))
        return tuple(recovered)

    # ----------------------------------------------------------------- attempts

    async def add_attempt(self, attempt: JobAttemptRecord) -> JobAttemptRecord:
        await self._session.execute(
            insert(_ATTEMPTS).values(
                id=attempt.id or new_id("jatt"),
                job_id=attempt.job_id,
                attempt_number=attempt.attempt_number,
                state=attempt.state.value,
                worker_id=attempt.worker_id,
                node_id=attempt.node_id,
                started_at=attempt.started_at,
                finished_at=attempt.finished_at,
                failure_code=attempt.failure_code,
                failure_message=attempt.failure_message,
                error_class=attempt.error_class.value if attempt.error_class else None,
                diagnostics=attempt.diagnostics,
            )
        )
        return attempt

    async def list_attempts(self, job_id: str) -> tuple[JobAttemptRecord, ...]:
        rows = await self._fetch_all(
            select(_ATTEMPTS)
            .where(_ATTEMPTS.c.job_id == job_id)
            .order_by(_ATTEMPTS.c.attempt_number)
        )
        return tuple(to_attempt(row) for row in rows)

    # ------------------------------------------------------------------ reading

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
        statement = select(_JOBS).where(_JOBS.c.workspace_id.in_(workspace_ids))
        if project_id is not None:
            statement = statement.where(_JOBS.c.project_id == project_id)
        return await self._paged(statement, page=page, states=states, kinds=kinds, queue=queue)

    async def list_all(
        self,
        *,
        page: Page,
        states: tuple[JobState, ...] = (),
        kinds: tuple[JobKind, ...] = (),
        queue: str | None = None,
    ) -> Paged[JobRecord]:
        """Platform-administrative listing across every tenant."""
        return await self._paged(select(_JOBS), page=page, states=states, kinds=kinds, queue=queue)

    async def queue_statistics(self) -> tuple[dict[str, Any], ...]:
        rows = await self._fetch_all(
            select(
                _JOBS.c.queue,
                _JOBS.c.state,
                func.count().label("total"),
            ).group_by(_JOBS.c.queue, _JOBS.c.state)
        )
        return tuple(
            {"queue": row["queue"], "state": row["state"], "total": int(row["total"])}
            for row in rows
        )

    # ------------------------------------------------------------------ helpers

    async def _paged(
        self,
        statement: Any,
        *,
        page: Page,
        states: tuple[JobState, ...],
        kinds: tuple[JobKind, ...],
        queue: str | None,
    ) -> Paged[JobRecord]:
        if states:
            statement = statement.where(_JOBS.c.state.in_([s.value for s in states]))
        if kinds:
            statement = statement.where(_JOBS.c.kind.in_([k.value for k in kinds]))
        if queue is not None:
            statement = statement.where(
                _JOBS.c.queue == (queue.value if isinstance(queue, JobQueue) else queue)
            )
        total = await self._count(statement)
        rows = await self._fetch_all(
            statement.order_by(_JOBS.c.created_at.desc()).limit(page.size).offset(page.offset)
        )
        return Paged(items=tuple(to_job(row) for row in rows), total=total, page=page)

    async def _owned_update(
        self, *, job_id: str, worker_id: str, values: dict[str, Any]
    ) -> JobRecord | None:
        """Apply an update only while ``worker_id`` still holds the claim."""
        result = await self._session.execute(
            update(_JOBS)
            .where(
                _JOBS.c.id == job_id,
                _JOBS.c.claimed_by_worker_id == worker_id,
            )
            .values(**values, version=_JOBS.c.version + 1)
            .returning(_JOBS)
        )
        row = result.mappings().first()
        return to_job(dict(row)) if row is not None else None


__all__ = ["SqlJobRepository", "to_attempt", "to_job"]
