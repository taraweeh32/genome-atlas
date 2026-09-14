"""One dispatch table over every job kind the application can execute.

Each family of handlers stays in its own module (dataset ingestion, analysis and
scheduling); this composes them and refuses a kind nobody claims, so an
unregistered job fails loudly as a configuration error instead of being silently
dropped from a queue.
"""

from __future__ import annotations

from typing import Any

from app.application.container import Container
from app.core.logging import get_logger
from app.domain.analysis.entities import JobRecord
from app.domain.errors import ValidationError
from app.domain.value_objects.enums import JobKind
from app.workers.analysis_handlers import AnalysisJobHandlers
from app.workers.handlers import DataJobHandlers
from app.workers.query_handlers import QueryJobHandlers
from app.workers.result_handlers import ResultJobHandlers

logger = get_logger(__name__)


class JobDispatcher:
    """Routes a claimed job to the handler family that owns its kind."""

    def __init__(self, container: Container) -> None:
        self._data = DataJobHandlers(container.data_services())
        self._analysis = AnalysisJobHandlers(container.analysis_services())
        self._results = ResultJobHandlers(container.result_services())
        self._queries = QueryJobHandlers(container.query_services())

    @property
    def supported_kinds(self) -> tuple[JobKind, ...]:
        return tuple(
            sorted(
                self._analysis.supported_kinds
                | self._data.supported_kinds
                | self._results.supported_kinds
                | self._queries.supported_kinds
            )
        )

    async def dispatch(self, job: JobRecord, *, worker_id: str | None = None) -> Any:
        if job.kind in self._analysis.supported_kinds:
            return await self._analysis.handle(
                job.kind,
                job.payload,
                correlation_id=job.correlation_id,
                job_id=job.id,
                worker_id=worker_id,
            )
        if job.kind in self._results.supported_kinds:
            return await self._results.handle(
                job.kind, job.payload, correlation_id=job.correlation_id
            )
        if job.kind in self._queries.supported_kinds:
            return await self._queries.handle(
                job.kind, job.payload, correlation_id=job.correlation_id
            )
        if job.kind in self._data.supported_kinds:
            return await self._data.handle(
                job.kind, job.payload, correlation_id=job.correlation_id
            )
        raise ValidationError(
            "no handler is registered for this job kind",
            details={"kind": job.kind.value, "job_id": job.id},
        )


__all__ = ["JobDispatcher"]
