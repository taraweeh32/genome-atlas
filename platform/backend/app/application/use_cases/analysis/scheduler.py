"""The scheduler: turns due schedules into ordinary executions.

Safety properties this use case is responsible for:

* **Bounded work per run.** At most ``limit`` schedules are considered, and each
  schedule contributes at most ``catch_up_limit`` firings, so downtime can never
  produce an unbounded burst.
* **Exactly-once per slot.** A trigger row is written for ``(schedule,
  scheduled_for)`` *before* any work is created; the unique constraint makes two
  racing schedulers unable to both fire the same slot.
* **Re-authorization at firing time.** The schedule's owner is re-resolved from
  the database on every firing. A schedule created by someone who has since lost
  project access, been suspended or been removed stops firing instead of running
  with stale authority.
* **Recorded skips.** Concurrency skips, missed-slot skips and failures are
  written to the firing history rather than silently dropped.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.analysis.dependencies import EXECUTE, AnalysisServices
from app.application.use_cases.analysis.executions import (
    RequestExecution,
    RequestExecutionCommand,
)
from app.core.logging import get_logger
from app.domain.analysis.entities import AnalysisSchedule, ScheduleTrigger
from app.domain.analysis.schedule import ScheduleExpression, resolve_missed
from app.domain.errors import DomainError
from app.domain.value_objects.enums import (
    AuditChannel,
    AuditOutcome,
    ScheduleConcurrencyPolicy,
    ScheduleState,
    ScheduleTriggerOutcome,
)
from app.infrastructure.persistence.repositories.base import new_id

logger = get_logger(__name__)

DEFAULT_SCHEDULE_BATCH = 25


@dataclass(frozen=True, slots=True)
class SchedulerRunSummary:
    considered: int = 0
    triggered: int = 0
    skipped: int = 0
    failed: int = 0


class TriggerDueSchedules:
    def __init__(
        self, services: AnalysisServices, *, batch_size: int = DEFAULT_SCHEDULE_BATCH
    ) -> None:
        self._services = services
        self._batch_size = batch_size
        self._request_execution = RequestExecution(services)

    async def execute(self) -> SchedulerRunSummary:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            due = await repositories.schedules.list_due(now=now, limit=self._batch_size)
        considered = triggered = skipped = failed = 0
        for schedule in due:
            considered += 1
            outcome = await self._fire(schedule, now)
            triggered += outcome[0]
            skipped += outcome[1]
            failed += outcome[2]
        return SchedulerRunSummary(
            considered=considered, triggered=triggered, skipped=skipped, failed=failed
        )

    async def _fire(self, schedule: AnalysisSchedule, now: datetime) -> tuple[int, int, int]:
        expression = ScheduleExpression.parse(schedule.schedule_expression)
        firings = resolve_missed(
            expression=expression,
            timezone_name=schedule.timezone_name,
            scheduled_for=schedule.next_execution_at,
            now=now,
            policy=schedule.missed_policy,
            catch_up_limit=schedule.catch_up_limit,
        )
        triggered = skipped = failed = 0
        last_outcome: ScheduleTriggerOutcome | None = None

        for slot in firings.skipped:
            if await self._record(
                schedule,
                slot=slot,
                now=now,
                outcome=ScheduleTriggerOutcome.SKIPPED_MISSED,
                detail={"reason": schedule.missed_policy.value},
            ):
                skipped += 1

        for slot in firings.due:
            if schedule.state is not ScheduleState.ENABLED:
                if await self._record(
                    schedule,
                    slot=slot,
                    now=now,
                    outcome=ScheduleTriggerOutcome.SKIPPED_DISABLED,
                ):
                    skipped += 1
                continue
            claimed = await self._record(
                schedule, slot=slot, now=now, outcome=ScheduleTriggerOutcome.TRIGGERED
            )
            if claimed is None:
                # Another scheduler already owns this slot.
                continue
            result = await self._start_execution(schedule, slot=slot, now=now)
            last_outcome = result
            if result is ScheduleTriggerOutcome.TRIGGERED:
                triggered += 1
            elif result is ScheduleTriggerOutcome.FAILED:
                failed += 1
            else:
                skipped += 1

        await self._advance(
            schedule,
            now=now,
            next_execution_at=firings.next_execution_at,
            outcome=last_outcome,
        )
        return triggered, skipped, failed

    async def _record(
        self,
        schedule: AnalysisSchedule,
        *,
        slot: datetime,
        now: datetime,
        outcome: ScheduleTriggerOutcome,
        detail: dict | None = None,
    ) -> ScheduleTrigger | None:
        async with self._services.unit_of_work.begin() as repositories:
            return await repositories.schedules.record_trigger(
                ScheduleTrigger(
                    id=new_id("str"),
                    schedule_id=schedule.id,
                    scheduled_for=slot,
                    outcome=outcome,
                    triggered_at=now,
                    detail=detail or {},
                )
            )

    async def _finalize(
        self,
        schedule: AnalysisSchedule,
        *,
        slot: datetime,
        now: datetime,
        outcome: ScheduleTriggerOutcome,
        execution_id: str | None = None,
        detail: dict | None = None,
    ) -> None:
        """Complete the claimed slot in place with its observed outcome."""
        async with self._services.unit_of_work.begin() as repositories:
            await repositories.schedules.finalize_trigger(
                schedule_id=schedule.id,
                scheduled_for=slot,
                outcome=outcome,
                analysis_execution_id=execution_id,
                detail=detail or {},
            )

    async def _start_execution(
        self, schedule: AnalysisSchedule, *, slot: datetime, now: datetime
    ) -> ScheduleTriggerOutcome:
        request = RequestContext.system(
            correlation_id=f"schedule-{schedule.id}-{int(slot.timestamp())}",
            channel=AuditChannel.SCHEDULER,
        )
        if schedule.analysis_id is None or schedule.created_by is None:
            await self._finalize(
                schedule,
                slot=slot,
                now=now,
                outcome=ScheduleTriggerOutcome.FAILED,
                detail={"reason": "schedule_is_incomplete"},
            )
            return ScheduleTriggerOutcome.FAILED

        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, request)
            owner = await repositories.users.get(schedule.created_by)
            if owner is None or not owner.can_authenticate:
                await recorder.audit(
                    action="schedule.trigger_denied",
                    outcome=AuditOutcome.DENIED,
                    occurred_at=now,
                    resource_type="schedule",
                    resource_id=schedule.id,
                    workspace_id=schedule.workspace_id,
                    project_id=schedule.project_id,
                    reason="owner_not_usable",
                )
                await self._finalize(
                    schedule,
                    slot=slot,
                    now=now,
                    outcome=ScheduleTriggerOutcome.FAILED,
                    detail={"reason": "owner_not_usable"},
                )
                return ScheduleTriggerOutcome.FAILED
            actor = await self._services.authorization.resolve(repositories, owner)
            if schedule.project_id:
                actor = await self._services.authorization.ensure_project_scope(
                    repositories, actor, schedule.project_id
                )
                permitted = EXECUTE.project in actor.project_capabilities(schedule.project_id)
            else:
                permitted = EXECUTE.workspace in actor.workspace_capabilities(
                    schedule.workspace_id or ""
                )
            if not permitted:
                await recorder.audit(
                    action="schedule.trigger_denied",
                    outcome=AuditOutcome.DENIED,
                    occurred_at=now,
                    actor_user_id=owner.id,
                    resource_type="schedule",
                    resource_id=schedule.id,
                    workspace_id=schedule.workspace_id,
                    project_id=schedule.project_id,
                    reason="owner_lost_execute_permission",
                )
            active = await repositories.analysis_executions.count_active_for_analysis(
                schedule.analysis_id
            )
        if not permitted:
            await self._finalize(
                schedule,
                slot=slot,
                now=now,
                outcome=ScheduleTriggerOutcome.FAILED,
                detail={"reason": "owner_lost_execute_permission"},
            )
            return ScheduleTriggerOutcome.FAILED

        if active and schedule.concurrency_policy is ScheduleConcurrencyPolicy.SKIP_IF_RUNNING:
            await self._finalize(
                schedule,
                slot=slot,
                now=now,
                outcome=ScheduleTriggerOutcome.SKIPPED_CONCURRENCY,
                detail={"active_executions": active},
            )
            return ScheduleTriggerOutcome.SKIPPED_CONCURRENCY

        try:
            view = await self._request_execution.execute(
                RequestExecutionCommand(
                    actor=actor,
                    analysis_id=schedule.analysis_id,
                    request=request,
                    configuration_id=schedule.analysis_configuration_id,
                    queue=schedule.queue,
                    priority=schedule.priority,
                    idempotency_key=f"schedule:{schedule.id}:{slot.isoformat()}",
                    schedule_id=schedule.id,
                    scheduled_for=slot,
                )
            )
        except DomainError as error:
            logger.warning(
                "schedule firing failed",
                extra={"schedule_id": schedule.id, "error": error.__class__.__name__},
            )
            await self._finalize(
                schedule,
                slot=slot,
                now=now,
                outcome=ScheduleTriggerOutcome.FAILED,
                detail={"error": error.__class__.__name__, "message": str(error)},
            )
            return ScheduleTriggerOutcome.FAILED

        await self._finalize(
            schedule,
            slot=slot,
            now=now,
            outcome=ScheduleTriggerOutcome.TRIGGERED,
            execution_id=view.execution.id,
        )
        return ScheduleTriggerOutcome.TRIGGERED

    async def _advance(
        self,
        schedule: AnalysisSchedule,
        *,
        now: datetime,
        next_execution_at: datetime | None,
        outcome: ScheduleTriggerOutcome | None,
    ) -> None:
        """Record the firing on the schedule itself and move the cursor forward.

        Re-read inside the transaction: an administrator may have disabled the
        schedule while this run was firing, and that intent wins.
        """
        async with self._services.unit_of_work.begin() as repositories:
            current = await repositories.schedules.get(schedule.id)
            if current is None:
                return
            following = next_execution_at if current.state is ScheduleState.ENABLED else None
            updated = (
                current.fired(at=now, next_execution_at=following, outcome=outcome)
                if outcome is not None
                else current.with_next_execution(following)
            )
            await repositories.schedules.save(updated)


__all__ = ["DEFAULT_SCHEDULE_BATCH", "SchedulerRunSummary", "TriggerDueSchedules"]
