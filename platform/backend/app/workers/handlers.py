"""Job handlers for dataset ingestion work.

A handler is the *execution* side of a durable job: it takes a job kind and the
payload that was enqueued in the same transaction as the business change, and
invokes the use case that does the work. Handlers are deliberately thin — all
rules live in the use cases, so the same behaviour is reachable from a test
without a queue.

What is **not** here, on purpose: claiming, leasing, heartbeats, retry policy,
stale-job recovery and cancellation. Those belong to the job subsystem's own
package, and inventing a partial version of them here would produce a scheduler
nobody can reason about. Until then this dispatcher is invoked directly (by
tests, and by the operational commands documented in
``docs/development-commands.md``), and ``app/workers/worker.py`` claims no work.

Handlers run with no user actor. Authorization for this work was decided when the
request that enqueued it was authorized; a handler must therefore never widen
scope, and never accept a workspace or project identifier as an instruction about
*whose* data to touch — it resolves the subject from its own row.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from app.application.services.context import RequestContext
from app.application.use_cases.data.artifacts import VerifyArtifact, VerifyArtifactCommand
from app.application.use_cases.data.dependencies import DataServices
from app.application.use_cases.data.imports import ExecuteImport, ExecuteImportCommand
from app.application.use_cases.data.uploads import ExpireStaleUploadSessions
from app.core.logging import get_logger
from app.domain.errors import ValidationError
from app.domain.value_objects.enums import AuditChannel, JobKind

logger = get_logger(__name__)

#: Maintenance jobs identify themselves in audit records by label, never by
#: borrowing a user identity.
MAINTENANCE_ACTOR_LABEL = "platform-maintenance"


def worker_request_context(correlation_id: str) -> RequestContext:
    """The request context a job runs under.

    The correlation id is carried from the request that enqueued the job, so a UI
    action, its job, and the artifacts it produced share one trace.
    """
    return RequestContext(
        correlation_id=correlation_id,
        ip_hash=None,
        user_agent_summary=None,
        channel=AuditChannel.WORKER,
        rate_limit_key="job",
    )


def _require(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value:
        raise ValidationError(
            "the job payload is missing a required reference",
            details={"field": field},
        )
    return value


class DataJobHandlers:
    """Dispatches ingestion job kinds to their use cases."""

    def __init__(self, services: DataServices) -> None:
        self._services = services

    @property
    def supported_kinds(self) -> frozenset[JobKind]:
        return frozenset(self._table())

    def _table(self) -> dict[JobKind, Callable[[dict[str, Any], RequestContext], Awaitable[Any]]]:
        return {
            JobKind.DATASET_VALIDATION: self._verify_artifact,
            JobKind.DATASET_IMPORT: self._execute_import,
            JobKind.MAINTENANCE: self._sweep_upload_sessions,
        }

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
            "job handler started",
            extra={"job_kind": kind.value, "correlation_id": correlation_id},
        )
        result = await handler(payload, context)
        logger.info(
            "job handler finished",
            extra={"job_kind": kind.value, "correlation_id": correlation_id},
        )
        return result

    # -- handlers ---------------------------------------------------------- #

    async def _verify_artifact(self, payload: dict[str, Any], context: RequestContext) -> Any:
        return await VerifyArtifact(self._services).execute(
            VerifyArtifactCommand(
                upload_session_id=_require(payload, "upload_session_id"),
                request=context,
            )
        )

    async def _execute_import(self, payload: dict[str, Any], context: RequestContext) -> Any:
        return await ExecuteImport(self._services).execute(
            ExecuteImportCommand(
                import_session_id=_require(payload, "import_session_id"),
                request=context,
            )
        )

    async def _sweep_upload_sessions(
        self, payload: dict[str, Any], context: RequestContext
    ) -> Any:
        limit = payload.get("limit")
        return await ExpireStaleUploadSessions(self._services).execute(
            request=context, limit=int(limit) if isinstance(limit, int) else 100
        )


__all__ = ["MAINTENANCE_ACTOR_LABEL", "DataJobHandlers", "worker_request_context"]
