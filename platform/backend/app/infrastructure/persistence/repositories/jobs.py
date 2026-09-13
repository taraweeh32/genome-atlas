"""Transactional job enqueue.

Only enqueue and read: claiming, leasing, heartbeats, retries and execution are
the job subsystem's own package. What matters here is that the row is written in
the *same transaction* as the business change that asked for the work, so:

* a rolled-back upload never leaves a validation job pointing at nothing, and
* a committed upload never loses its validation job.

Jobs live in the ``platform`` schema because they are operational bookkeeping,
not domain state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.domain.value_objects.enums import JobKind, JobState
from app.infrastructure.persistence.models.jobs import Job as JobModel
from app.infrastructure.persistence.repositories.base import SqlRepository, new_id

_JOBS = JobModel.__table__


class SqlJobRepository(SqlRepository):
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
    ) -> str:
        job_id = new_id("job")
        values = {
            "id": job_id,
            "kind": kind.value,
            "state": JobState.QUEUED.value,
            "queue": queue,
            "priority": priority,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "payload": payload,
            "requested_by": requested_by,
            "idempotency_key": idempotency_key,
            "available_at": available_at,
            "max_attempts": max_attempts,
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


__all__ = ["SqlJobRepository"]
