"""Job handlers for automated classification evaluation.

Thin by design, like every handler family: submission, provenance, audit and state
transitions live in the use cases, so the same behaviour is reachable from a test
without a queue.

This family runs with no user actor. Authorization happened when the evaluation was
requested; the handler resolves its subject from the evaluation row it was given and
never treats an identifier in a payload as an instruction about whose data to touch.

Nothing here evaluates a criterion or decides a classification: the handler only
hands a structured request to the existing scientific gateway.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.application.services.context import RequestContext
from app.application.use_cases.interpretation.dependencies import InterpretationServices
from app.application.use_cases.interpretation.evaluations import (
    SubmitClassificationEvaluation,
)
from app.core.logging import get_logger
from app.domain.errors import ValidationError
from app.domain.value_objects.enums import JobKind
from app.workers.handlers import _require, worker_request_context

logger = get_logger(__name__)


class InterpretationJobHandlers:
    """Dispatches interpretation job kinds to their use cases."""

    def __init__(self, services: InterpretationServices) -> None:
        self._services = services

    @property
    def supported_kinds(self) -> frozenset[JobKind]:
        return frozenset(self._table())

    def _table(
        self,
    ) -> dict[JobKind, Callable[[dict[str, Any], RequestContext], Awaitable[Any]]]:
        return {JobKind.CLASSIFICATION_EVALUATION: self._submit}

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
            "interpretation job handler started",
            extra={"job_kind": kind.value, "correlation_id": correlation_id},
        )
        result = await handler(payload, context)
        logger.info(
            "interpretation job handler finished",
            extra={"job_kind": kind.value, "correlation_id": correlation_id},
        )
        return result

    async def _submit(self, payload: dict[str, Any], context: RequestContext) -> Any:
        return await SubmitClassificationEvaluation(self._services).execute(
            classification_evaluation_id=_require(
                payload, "classification_evaluation_id"
            ),
            request=context,
        )


__all__ = ["InterpretationJobHandlers"]
