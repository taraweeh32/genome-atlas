"""Compute/worker node registry.

A node registers itself, heartbeats, and is drained or retired administratively.
Two facts are kept strictly apart:

* ``health_state`` is *observed* — derived from heartbeats, never asserted by an
  administrator, and
* ``lifecycle_state`` is *intended* — set administratively, never inferred from a
  missed heartbeat.

Application workers and scientific compute nodes share this registry but never
share a fleet: ``node_class`` decides which work a node may ever be offered.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.analysis.dependencies import AnalysisServices
from app.domain.analysis.entities import ComputeNode
from app.domain.authorization.context import ActorContext
from app.domain.authorization.permissions import Permission
from app.domain.errors import NotFoundError
from app.domain.events import EventType
from app.domain.value_objects.enums import (
    AuditOutcome,
    NodeClass,
    NodeHealthState,
    NodeLifecycleState,
)
from app.infrastructure.persistence.repositories.base import new_id

#: A node that has not heartbeated for this long is treated as unhealthy and is
#: therefore not schedulable. Fail closed: silence is never "probably fine".
DEFAULT_HEARTBEAT_GRACE_SECONDS = 90


@dataclass(frozen=True, slots=True)
class RegisterNodeCommand:
    node_key: str
    node_class: NodeClass
    queues: tuple[str, ...]
    capabilities: tuple[str, ...]
    resource_profile: dict
    max_concurrency: int
    engine_version: str | None = None
    environment_version: str | None = None


class RegisterNode:
    """Called by a worker process at startup, and on every heartbeat cycle.

    Not an API operation: a node registers through the trusted worker runtime,
    so nothing here accepts a browser-supplied identity.
    """

    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, command: RegisterNodeCommand) -> ComputeNode:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            existing = await repositories.compute_nodes.get_by_key(command.node_key)
            node = ComputeNode(
                id=existing.id if existing else new_id("nod"),
                node_key=command.node_key,
                node_class=command.node_class,
                health_state=NodeHealthState.HEALTHY,
                # Re-registration never revives a node an administrator retired
                # or is draining.
                lifecycle_state=(
                    existing.lifecycle_state if existing else NodeLifecycleState.ACTIVE
                ),
                queues=command.queues,
                capabilities=command.capabilities,
                resource_profile=dict(command.resource_profile),
                max_concurrency=max(1, command.max_concurrency),
                active_job_count=existing.active_job_count if existing else 0,
                engine_version=command.engine_version,
                environment_version=command.environment_version,
                heartbeat_at=now,
                registered_at=existing.registered_at if existing else now,
                version=existing.version if existing else 1,
            )
            stored = await repositories.compute_nodes.upsert(node)
            if existing is None:
                recorder = ActivityRecorder(repositories, RequestContext.system())
                await recorder.event(
                    event_type=EventType.COMPUTE_NODE_REGISTERED,
                    aggregate_type="compute_node",
                    aggregate_id=stored.id,
                    occurred_at=now,
                    payload={
                        "node_key": stored.node_key,
                        "node_class": stored.node_class.value,
                    },
                )
        return stored


@dataclass(frozen=True, slots=True)
class ListNodesQuery:
    actor: ActorContext
    request: RequestContext
    node_class: NodeClass | None = None


class ListNodes:
    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, query: ListNodesQuery) -> tuple[ComputeNode, ...]:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            await self._services.authorization.require(
                query.actor,
                Permission.PLATFORM_COMPUTE_READ,
                recorder=recorder,
                occurred_at=now,
            )
            return await repositories.compute_nodes.list_nodes(node_class=query.node_class)


@dataclass(frozen=True, slots=True)
class ChangeNodeLifecycleCommand:
    actor: ActorContext
    node_id: str
    target: NodeLifecycleState
    reason: str | None
    request: RequestContext


class ChangeNodeLifecycle:
    """Drain, reactivate or retire a node. Administrative intent only."""

    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    async def execute(self, command: ChangeNodeLifecycleCommand) -> ComputeNode:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            await self._services.authorization.require(
                command.actor,
                Permission.PLATFORM_COMPUTE_ADMINISTER,
                recorder=recorder,
                occurred_at=now,
            )
            node = await repositories.compute_nodes.get(command.node_id)
            if node is None:
                raise NotFoundError("compute_node", command.node_id)
            updated = node.with_lifecycle(command.target)
            if command.target is NodeLifecycleState.DRAINING:
                updated = replace(updated, drained_at=now, drain_reason=command.reason)
            stored = await repositories.compute_nodes.save(updated)
            await recorder.audit(
                action="compute_node.lifecycle_changed",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="compute_node",
                resource_id=stored.id,
                previous_state=node.lifecycle_state.value,
                new_state=stored.lifecycle_state.value,
                reason=command.reason,
            )
            if command.target is NodeLifecycleState.DRAINING:
                await recorder.event(
                    event_type=EventType.COMPUTE_NODE_DRAINED,
                    aggregate_type="compute_node",
                    aggregate_id=stored.id,
                    occurred_at=now,
                )
        return stored


class MarkSilentNodesUnhealthy:
    """Observed health, run by maintenance. Never changes lifecycle intent."""

    def __init__(
        self,
        services: AnalysisServices,
        *,
        grace_seconds: int = DEFAULT_HEARTBEAT_GRACE_SECONDS,
    ) -> None:
        self._services = services
        self._grace_seconds = grace_seconds

    async def execute(self) -> int:
        now = self._services.clock.now()
        threshold = now - timedelta(seconds=self._grace_seconds)
        async with self._services.unit_of_work.begin() as repositories:
            affected = await repositories.compute_nodes.mark_unhealthy_before(threshold=threshold)
            if affected:
                recorder = ActivityRecorder(repositories, RequestContext.system())
                await recorder.event(
                    event_type=EventType.COMPUTE_NODE_UNHEALTHY,
                    aggregate_type="compute_node",
                    aggregate_id="fleet",
                    occurred_at=now,
                    payload={"affected": affected, "threshold": threshold.isoformat()},
                )
        return affected


__all__ = [
    "DEFAULT_HEARTBEAT_GRACE_SECONDS",
    "ChangeNodeLifecycle",
    "ChangeNodeLifecycleCommand",
    "ListNodes",
    "ListNodesQuery",
    "MarkSilentNodesUnhealthy",
    "RegisterNode",
    "RegisterNodeCommand",
]
