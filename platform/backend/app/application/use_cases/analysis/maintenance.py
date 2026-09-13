"""Operational recovery: abandoned jobs and silent compute nodes.

Two independent facts, recovered in one maintenance pass:

* a job whose lease expired without a heartbeat is re-queued (or dead-lettered
  when its attempts are exhausted), so work is never lost to a crashed worker and
  never runs twice under two live leases; and
* a node that stopped reporting is marked *observed* unhealthy, which stops it
  being offered work without touching an administrator's stated intent for it.

Neither step interprets scientific content, and neither invents an actor: the
recovery runs as the system.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.analysis.dependencies import AnalysisServices
from app.application.use_cases.analysis.nodes import (
    DEFAULT_HEARTBEAT_GRACE_SECONDS,
    MarkSilentNodesUnhealthy,
)
from app.core.logging import get_logger
from app.domain.events import EventType
from app.domain.value_objects.enums import JobState

logger = get_logger(__name__)

DEFAULT_RECOVERY_LIMIT = 50


@dataclass(frozen=True, slots=True)
class RecoverySummary:
    requeued: int = 0
    dead_lettered: int = 0
    nodes_marked_unhealthy: int = 0


class RecoverAbandonedWork:
    def __init__(
        self,
        services: AnalysisServices,
        *,
        limit: int = DEFAULT_RECOVERY_LIMIT,
        node_grace_seconds: int = DEFAULT_HEARTBEAT_GRACE_SECONDS,
    ) -> None:
        self._services = services
        self._limit = limit
        self._node_grace_seconds = node_grace_seconds

    async def execute(self) -> RecoverySummary:
        now = self._services.clock.now()
        stale_before = self._services.lease.stale_before(now)
        async with self._services.unit_of_work.begin() as repositories:
            recovered = await repositories.jobs.recover_stale(
                before=stale_before, now=now, limit=self._limit
            )
            requeued = sum(1 for job in recovered if job.state is JobState.QUEUED)
            dead_lettered = sum(1 for job in recovered if job.state is JobState.DEAD_LETTER)
            if recovered:
                recorder = ActivityRecorder(repositories, RequestContext.system())
                for job in recovered:
                    await recorder.event(
                        event_type=(
                            EventType.JOB_DEAD_LETTERED
                            if job.state is JobState.DEAD_LETTER
                            else EventType.JOB_RECOVERED
                        ),
                        aggregate_type="job",
                        aggregate_id=job.id,
                        occurred_at=now,
                        workspace_id=job.workspace_id,
                        payload={"attempt_number": job.attempt_number, "reason": "lease_expired"},
                    )
        nodes = await MarkSilentNodesUnhealthy(
            self._services, grace_seconds=self._node_grace_seconds
        ).execute()
        summary = RecoverySummary(
            requeued=requeued,
            dead_lettered=dead_lettered,
            nodes_marked_unhealthy=nodes,
        )
        if requeued or dead_lettered or nodes:
            logger.info(
                "abandoned work recovered",
                extra={
                    "requeued": summary.requeued,
                    "dead_lettered": summary.dead_lettered,
                    "nodes_marked_unhealthy": summary.nodes_marked_unhealthy,
                },
            )
        return summary


__all__ = ["DEFAULT_RECOVERY_LIMIT", "RecoverAbandonedWork", "RecoverySummary"]
