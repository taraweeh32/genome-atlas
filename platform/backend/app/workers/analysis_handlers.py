"""Job handlers for analysis execution, scheduling and fleet maintenance.

Thin by design, exactly like ``DataJobHandlers``: a handler translates a job
payload into a use-case command and returns. Claiming, leasing, retries,
cancellation and stale recovery belong to :mod:`app.workers.runtime`, and the
scientific work itself belongs to the independent scientific subsystem behind the
integration contract.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.application.services.context import RequestContext
from app.application.use_cases.analysis.dependencies import AnalysisServices
from app.application.use_cases.analysis.execution_runner import (
    RunAnalysisExecution,
    RunExecutionCommand,
)
from app.application.use_cases.analysis.maintenance import RecoverAbandonedWork
from app.application.use_cases.analysis.scheduler import TriggerDueSchedules
from app.core.logging import get_logger
from app.domain.errors import ValidationError
from app.domain.value_objects.enums import JobKind

logger = get_logger(__name__)


def _require(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise ValidationError(
            "the job payload is missing a required reference",
            details={"field": field},
        )
    return value


class AnalysisJobHandlers:
    """Dispatches analysis, scheduling and fleet job kinds to their use cases."""

    def __init__(self, services: AnalysisServices) -> None:
        self._services = services

    @property
    def supported_kinds(self) -> frozenset[JobKind]:
        return frozenset(self._table())

    def _table(
        self,
    ) -> dict[JobKind, Callable[[dict[str, Any], RequestContext, str | None], Awaitable[Any]]]:
        return {
            JobKind.ANALYSIS_EXECUTION: self._run_execution,
            JobKind.SCIENTIFIC_EXECUTION: self._run_execution,
            JobKind.SCHEDULE_TRIGGER: self._trigger_schedules,
            JobKind.STALE_RECOVERY: self._recover_abandoned_work,
        }

    async def handle(
        self,
        kind: JobKind,
        payload: dict[str, Any],
        *,
        correlation_id: str,
        job_id: str | None = None,
        worker_id: str | None = None,
    ) -> Any:
        handler = self._table().get(kind)
        if handler is None:
            raise ValidationError(
                "no handler is registered for this job kind",
                details={"kind": kind.value},
            )
        context = RequestContext.system(correlation_id=correlation_id)
        logger.info(
            "analysis job handler started",
            extra={"job_kind": kind.value, "correlation_id": correlation_id, "job_id": job_id},
        )
        result = await handler(payload, context, job_id)
        logger.info(
            "analysis job handler finished",
            extra={"job_kind": kind.value, "correlation_id": correlation_id, "job_id": job_id},
        )
        return result

    # -- handlers ---------------------------------------------------------- #

    async def _run_execution(
        self, payload: dict[str, Any], context: RequestContext, job_id: str | None
    ) -> Any:
        return await RunAnalysisExecution(self._services).execute(
            RunExecutionCommand(
                analysis_execution_id=_require(payload, "analysis_execution_id"),
                request=context,
                job_id=job_id,
            )
        )

    async def _trigger_schedules(
        self, payload: dict[str, Any], context: RequestContext, job_id: str | None
    ) -> Any:
        batch = payload.get("batch_size")
        scheduler = (
            TriggerDueSchedules(self._services, batch_size=int(batch))
            if isinstance(batch, int) and batch > 0
            else TriggerDueSchedules(self._services)
        )
        return await scheduler.execute()

    async def _recover_abandoned_work(
        self, payload: dict[str, Any], context: RequestContext, job_id: str | None
    ) -> Any:
        limit = payload.get("limit")
        use_case = (
            RecoverAbandonedWork(self._services, limit=int(limit))
            if isinstance(limit, int) and limit > 0
            else RecoverAbandonedWork(self._services)
        )
        return await use_case.execute()


__all__ = ["AnalysisJobHandlers"]
