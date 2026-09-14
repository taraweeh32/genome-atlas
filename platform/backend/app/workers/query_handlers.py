"""Job handlers for deferred variant queries.

Thin like every other handler family: authorization, validation, materialization
and provenance all live in the use case, so the same behaviour is reachable from a
test without a queue.

The handler runs with no user actor. It resolves the requester's grants from the
database and re-checks them there; a workspace identifier in a payload is never
treated as an instruction about whose data may be read.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.application.services.context import RequestContext
from app.application.use_cases.query.deferred import (
    QUERY_JOB_KIND,
    RunDeferredVariantQuery,
)
from app.application.use_cases.query.dependencies import QueryServices
from app.core.logging import get_logger
from app.domain.errors import ValidationError
from app.domain.value_objects.enums import JobKind
from app.workers.handlers import worker_request_context

logger = get_logger(__name__)


class QueryJobHandlers:
    """Dispatches deferred query job kinds to their use case."""

    def __init__(self, services: QueryServices) -> None:
        self._services = services

    @property
    def supported_kinds(self) -> frozenset[JobKind]:
        return frozenset(self._table())

    def _table(
        self,
    ) -> dict[JobKind, Callable[[dict[str, Any], RequestContext], Awaitable[Any]]]:
        return {QUERY_JOB_KIND: self._materialize}

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
            "query job handler started",
            extra={"job_kind": kind.value, "correlation_id": correlation_id},
        )
        result = await handler(payload, context)
        logger.info(
            "query job handler finished",
            extra={"job_kind": kind.value, "correlation_id": correlation_id},
        )
        return result

    async def _materialize(
        self, payload: dict[str, Any], context: RequestContext
    ) -> Any:
        return await RunDeferredVariantQuery(self._services).execute(payload, context)


__all__ = ["QueryJobHandlers"]
