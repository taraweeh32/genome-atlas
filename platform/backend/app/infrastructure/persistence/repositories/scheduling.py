"""Schedules, schedule triggers and compute-node registry.

Two correctness properties matter more than anything else here:

* **A schedule slot fires once.** ``record_trigger`` relies on the unique
  ``(scheduled_job_id, scheduled_for)`` constraint and returns ``None`` when the
  slot was already claimed, so two scheduler runs — or a retried run — cannot
  produce two executions for the same instant.
* **A silent node is not schedulable.** ``mark_unhealthy_before`` demotes nodes
  that stopped heartbeating, rather than leaving them eligible for placement.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.application.repositories import Page, Paged
from app.domain.analysis.entities import AnalysisSchedule, ComputeNode, ScheduleTrigger
from app.domain.value_objects.enums import (
    JobKind,
    JobQueue,
    MissedSchedulePolicy,
    NodeClass,
    NodeHealthState,
    NodeLifecycleState,
    ScheduleConcurrencyPolicy,
    ScheduleState,
    ScheduleTriggerOutcome,
)
from app.infrastructure.persistence.models.jobs import ScheduledJob as ScheduleModel
from app.infrastructure.persistence.models.jobs import ScheduleTrigger as TriggerModel
from app.infrastructure.persistence.models.jobs import WorkerNode as NodeModel
from app.infrastructure.persistence.repositories.base import SqlRepository

_SCHEDULES = ScheduleModel.__table__
_TRIGGERS = TriggerModel.__table__
_NODES = NodeModel.__table__

_SCHEDULABLE_STATES = (ScheduleState.ENABLED.value,)


def to_schedule(row: Mapping[str, Any]) -> AnalysisSchedule:
    return AnalysisSchedule(
        id=row["id"],
        name=row["name"],
        owner_scope=row["owner_scope"],
        owner_id=row["owner_id"],
        job_kind=JobKind(row["job_kind"]),
        state=ScheduleState(row["state"]),
        schedule_kind=row["schedule_kind"],
        schedule_expression=row["schedule_expression"],
        timezone_name=row["timezone_name"],
        concurrency_policy=ScheduleConcurrencyPolicy(row["concurrency_policy"]),
        missed_policy=MissedSchedulePolicy(row["missed_policy"]),
        analysis_id=row["analysis_id"],
        analysis_configuration_id=row["analysis_configuration_id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        description=row["description"],
        queue=JobQueue(row["queue"]),
        priority=row["priority"],
        catch_up_limit=row["catch_up_limit"],
        schedule_configuration=row["schedule_configuration"] or {},
        next_execution_at=row["next_execution_at"],
        previous_execution_at=row["previous_execution_at"],
        previous_job_id=row["previous_job_id"],
        last_trigger_outcome=(
            ScheduleTriggerOutcome(row["last_trigger_outcome"])
            if row["last_trigger_outcome"]
            else None
        ),
        consecutive_failure_count=row["consecutive_failure_count"],
        created_by=row["created_by"],
        updated_by=row["updated_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        version=row["version"],
    )


def to_trigger(row: Mapping[str, Any]) -> ScheduleTrigger:
    return ScheduleTrigger(
        id=row["id"],
        schedule_id=row["scheduled_job_id"],
        scheduled_for=row["scheduled_for"],
        outcome=ScheduleTriggerOutcome(row["outcome"]),
        triggered_at=row["triggered_at"],
        analysis_execution_id=row["analysis_execution_id"],
        job_id=row["job_id"],
        detail=row["detail"] or {},
    )


def to_node(row: Mapping[str, Any]) -> ComputeNode:
    return ComputeNode(
        id=row["id"],
        node_key=row["node_key"],
        node_class=NodeClass(row["node_class"]),
        health_state=NodeHealthState(row["health_state"]),
        lifecycle_state=NodeLifecycleState(row["lifecycle_state"]),
        queues=tuple(row["queues"] or ()),
        capabilities=tuple(row["capabilities"] or ()),
        resource_profile=row["resource_profile"] or {},
        max_concurrency=row["max_concurrency"],
        active_job_count=row["active_job_count"],
        engine_version=row["engine_version"],
        environment_version=row["environment_version"],
        heartbeat_at=row["heartbeat_at"],
        registered_at=row["registered_at"],
        drained_at=row["drained_at"],
        drain_reason=row["drain_reason"],
        last_error=row["last_error"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        version=row["version"],
    )


class SqlScheduleRepository(SqlRepository):
    async def add(self, schedule: AnalysisSchedule) -> AnalysisSchedule:
        await self._session.execute(
            insert(_SCHEDULES).values(
                id=schedule.id,
                name=schedule.name,
                owner_scope=schedule.owner_scope,
                owner_id=schedule.owner_id,
                job_kind=schedule.job_kind.value,
                analysis_id=schedule.analysis_id,
                analysis_configuration_id=schedule.analysis_configuration_id,
                state=schedule.state.value,
                description=schedule.description,
                workspace_id=schedule.workspace_id,
                project_id=schedule.project_id,
                schedule_kind=schedule.schedule_kind,
                schedule_expression=schedule.schedule_expression,
                timezone_name=schedule.timezone_name,
                concurrency_policy=schedule.concurrency_policy.value,
                missed_policy=schedule.missed_policy.value,
                queue=schedule.queue.value,
                priority=schedule.priority,
                catch_up_limit=schedule.catch_up_limit,
                schedule_configuration=schedule.schedule_configuration,
                next_execution_at=schedule.next_execution_at,
                created_by=schedule.created_by,
                updated_by=schedule.updated_by,
                version=schedule.version,
            )
        )
        return schedule

    async def get(self, schedule_id: str) -> AnalysisSchedule | None:
        row = await self._fetch_one(select(_SCHEDULES).where(_SCHEDULES.c.id == schedule_id))
        return to_schedule(row) if row else None

    async def save(self, schedule: AnalysisSchedule) -> AnalysisSchedule:
        version = await self._versioned_update(
            _SCHEDULES,
            entity_id=schedule.id,
            expected_version=schedule.version,
            values={
                "name": schedule.name,
                "description": schedule.description,
                "state": schedule.state.value,
                "analysis_configuration_id": schedule.analysis_configuration_id,
                "schedule_kind": schedule.schedule_kind,
                "schedule_expression": schedule.schedule_expression,
                "timezone_name": schedule.timezone_name,
                "concurrency_policy": schedule.concurrency_policy.value,
                "missed_policy": schedule.missed_policy.value,
                "queue": schedule.queue.value,
                "priority": schedule.priority,
                "catch_up_limit": schedule.catch_up_limit,
                "schedule_configuration": schedule.schedule_configuration,
                "next_execution_at": schedule.next_execution_at,
                "previous_execution_at": schedule.previous_execution_at,
                "previous_job_id": schedule.previous_job_id,
                "last_trigger_outcome": (
                    schedule.last_trigger_outcome.value
                    if schedule.last_trigger_outcome
                    else None
                ),
                "consecutive_failure_count": schedule.consecutive_failure_count,
                "updated_by": schedule.updated_by,
            },
        )
        return replace(schedule, version=version)

    async def name_exists(self, *, owner_scope: str, owner_id: str | None, name: str) -> bool:
        statement = select(_SCHEDULES.c.id).where(
            _SCHEDULES.c.owner_scope == owner_scope,
            _SCHEDULES.c.name == name.strip(),
        )
        statement = statement.where(
            _SCHEDULES.c.owner_id.is_(None) if owner_id is None else _SCHEDULES.c.owner_id == owner_id
        )
        return await self._fetch_one(statement) is not None

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
        statement = select(_SCHEDULES).where(_SCHEDULES.c.workspace_id.in_(workspace_ids))
        if project_id is not None:
            statement = statement.where(_SCHEDULES.c.project_id == project_id)
        if states:
            statement = statement.where(_SCHEDULES.c.state.in_([s.value for s in states]))
        total = await self._count(statement)
        rows = await self._fetch_all(
            statement.order_by(_SCHEDULES.c.name).limit(page.size).offset(page.offset)
        )
        return Paged(items=tuple(to_schedule(row) for row in rows), total=total, page=page)

    async def list_due(self, *, now: datetime, limit: int = 25) -> tuple[AnalysisSchedule, ...]:
        """Active schedules whose next slot has arrived, locked against races."""
        statement = (
            select(_SCHEDULES)
            .where(
                _SCHEDULES.c.state.in_(_SCHEDULABLE_STATES),
                _SCHEDULES.c.next_execution_at.isnot(None),
                _SCHEDULES.c.next_execution_at <= now,
            )
            .order_by(_SCHEDULES.c.next_execution_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        rows = await self._fetch_all(statement)
        return tuple(to_schedule(row) for row in rows)

    async def record_trigger(self, trigger: ScheduleTrigger) -> ScheduleTrigger | None:
        statement = (
            pg_insert(_TRIGGERS)
            .values(
                id=trigger.id,
                scheduled_job_id=trigger.schedule_id,
                scheduled_for=trigger.scheduled_for,
                triggered_at=trigger.triggered_at,
                outcome=trigger.outcome.value,
                analysis_execution_id=trigger.analysis_execution_id,
                job_id=trigger.job_id,
                detail=trigger.detail,
            )
            .on_conflict_do_nothing(
                index_elements=[_TRIGGERS.c.scheduled_job_id, _TRIGGERS.c.scheduled_for]
            )
            .returning(_TRIGGERS.c.id)
        )
        result = await self._session.execute(statement)
        return trigger if result.scalar_one_or_none() is not None else None

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
        """Replace a claimed slot's provisional outcome with the observed one.

        The claim row is written before any work exists, so the firing history
        must be completed in place — never by inserting a second row for the same
        slot, which uniqueness rightly forbids.
        """
        await self._session.execute(
            update(_TRIGGERS)
            .where(
                _TRIGGERS.c.scheduled_job_id == schedule_id,
                _TRIGGERS.c.scheduled_for == scheduled_for,
            )
            .values(
                outcome=outcome.value,
                analysis_execution_id=analysis_execution_id,
                job_id=job_id,
                detail=detail or {},
            )
        )

    async def list_triggers(self, schedule_id: str, *, page: Page) -> Paged[ScheduleTrigger]:
        statement = select(_TRIGGERS).where(_TRIGGERS.c.scheduled_job_id == schedule_id)
        total = await self._count(statement)
        rows = await self._fetch_all(
            statement.order_by(_TRIGGERS.c.scheduled_for.desc())
            .limit(page.size)
            .offset(page.offset)
        )
        return Paged(items=tuple(to_trigger(row) for row in rows), total=total, page=page)


class SqlComputeNodeRepository(SqlRepository):
    async def upsert(self, node: ComputeNode) -> ComputeNode:
        """Registration is idempotent: a restarted node re-registers itself."""
        values = {
            "id": node.id,
            "node_key": node.node_key,
            "node_class": node.node_class.value,
            "queues": list(node.queues),
            "capabilities": list(node.capabilities),
            "resource_profile": node.resource_profile,
            "health_state": node.health_state.value,
            "lifecycle_state": node.lifecycle_state.value,
            "max_concurrency": node.max_concurrency,
            "active_job_count": node.active_job_count,
            "engine_version": node.engine_version,
            "environment_version": node.environment_version,
            "registered_at": node.registered_at,
            "heartbeat_at": node.heartbeat_at,
            "version": node.version,
        }
        statement = (
            pg_insert(_NODES)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[_NODES.c.node_key],
                set_={
                    key: values[key]
                    for key in (
                        "node_class",
                        "queues",
                        "capabilities",
                        "resource_profile",
                        "health_state",
                        "lifecycle_state",
                        "max_concurrency",
                        "engine_version",
                        "environment_version",
                        "heartbeat_at",
                    )
                },
            )
            .returning(_NODES)
        )
        result = await self._session.execute(statement)
        return to_node(dict(result.mappings().one()))

    async def get_by_key(self, node_key: str) -> ComputeNode | None:
        row = await self._fetch_one(select(_NODES).where(_NODES.c.node_key == node_key))
        return to_node(row) if row else None

    async def get(self, node_id: str) -> ComputeNode | None:
        row = await self._fetch_one(select(_NODES).where(_NODES.c.id == node_id))
        return to_node(row) if row else None

    async def save(self, node: ComputeNode) -> ComputeNode:
        version = await self._versioned_update(
            _NODES,
            entity_id=node.id,
            expected_version=node.version,
            values={
                "queues": list(node.queues),
                "capabilities": list(node.capabilities),
                "resource_profile": node.resource_profile,
                "health_state": node.health_state.value,
                "lifecycle_state": node.lifecycle_state.value,
                "max_concurrency": node.max_concurrency,
                "active_job_count": node.active_job_count,
                "engine_version": node.engine_version,
                "environment_version": node.environment_version,
                "heartbeat_at": node.heartbeat_at,
                "drained_at": node.drained_at,
                "drain_reason": node.drain_reason,
                "last_error": node.last_error,
            },
        )
        return replace(node, version=version)

    async def list_nodes(
        self, *, node_class: NodeClass | None = None, page: Page | None = None
    ) -> tuple[ComputeNode, ...]:
        statement = select(_NODES)
        if node_class is not None:
            statement = statement.where(_NODES.c.node_class == node_class.value)
        statement = statement.order_by(_NODES.c.node_key)
        if page is not None:
            statement = statement.limit(page.size).offset(page.offset)
        rows = await self._fetch_all(statement)
        return tuple(to_node(row) for row in rows)

    async def mark_unhealthy_before(self, *, threshold: datetime) -> int:
        result = await self._session.execute(
            update(_NODES)
            .where(
                _NODES.c.health_state != NodeHealthState.UNREACHABLE.value,
                _NODES.c.heartbeat_at.isnot(None),
                _NODES.c.heartbeat_at < threshold,
            )
            .values(health_state=NodeHealthState.UNREACHABLE.value)
        )
        return int(result.rowcount or 0)


__all__ = [
    "SqlComputeNodeRepository",
    "SqlScheduleRepository",
    "to_node",
    "to_schedule",
    "to_trigger",
]
