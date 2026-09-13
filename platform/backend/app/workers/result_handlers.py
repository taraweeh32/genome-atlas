"""Job handlers for result-surface materialization.

Thin by design, like every handler family: the rules — verification, state
transitions, audit, provenance — live in the use case, so the same behaviour is
reachable from a test without a queue.

This family runs with no user actor. Authorization happened when the delivery was
accepted; a handler never widens scope and never treats a workspace identifier in
a payload as an instruction about whose data to touch. It resolves the subject
from the ingestion row it was given.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.application.services.context import RequestContext
from app.application.use_cases.results.dependencies import ResultServices
from app.application.use_cases.results.ingestion import (
    MaterializeResultSet,
    MaterializeResultSetCommand,
)
from app.core.logging import get_logger
from app.domain.errors import ValidationError
from app.domain.value_objects.enums import JobKind
from app.workers.handlers import _require, worker_request_context

logger = get_logger(__name__)


class ResultJobHandlers:
    """Dispatches result-ingestion job kinds to their use cases."""

    def __init__(self, services: ResultServices) -> None:
        self._services = services

    @property
    def supported_kinds(self) -> frozenset[JobKind]:
        return frozenset(self._table())

    def _table(
        self,
    ) -> dict[JobKind, Callable[[dict[str, Any], RequestContext], Awaitable[Any]]]:
        return {JobKind.RESULT_INGESTION: self._materialize}

    async def handle(
        self, kind: JobKind, payload: dict[str, Any], *, correlation_id: str
    ) -> Any:
        handler = self._table().get(kind)
        if handler is None:
            raise ValidationError(
                "no handler is registered for this job kind",
                details={"kind": kind.value},
            )
        context = worker_request_context(correlation_id)
        logger.info(
            "result job handler started",
            extra={"job_kind": kind.value, "correlation_id": correlation_id},
        )
        result = await handler(payload, context)
        logger.info(
            "result job handler finished",
            extra={"job_kind": kind.value, "correlation_id": correlation_id},
        )
        return result

    async def _materialize(
        self, payload: dict[str, Any], context: RequestContext
    ) -> Any:
        return await MaterializeResultSet(self._services).execute(
            MaterializeResultSetCommand(
                result_ingestion_id=_require(payload, "result_ingestion_id"),
                request=context,
            )
        )


__all__ = ["ResultJobHandlers"]
