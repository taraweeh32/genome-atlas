"""Audit, security-event and domain-event recording.

One helper so every use case records the same shape, and so the four governance
concerns stay separate:

* ``audit`` — who did what to which resource, with the state transition,
* ``security`` — authentication/authorization/rate-limit facts,
* ``event`` — a domain fact other subsystems may react to (via the outbox),
* notifications — a *delivery* concern, requested explicitly, never implied.

Everything written here goes into the caller's transaction.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.application.repositories import AuditRecord, SecurityRecord
from app.application.services.context import RequestContext
from app.domain.events import DomainEvent
from app.domain.value_objects.enums import ActorType, AuditOutcome


class ActivityRecorder:
    def __init__(self, repositories: Any, request: RequestContext) -> None:
        self._repositories = repositories
        self._request = request

    async def audit(
        self,
        *,
        action: str,
        outcome: AuditOutcome,
        occurred_at: datetime,
        actor_user_id: str | None = None,
        actor_label: str | None = None,
        actor_type: ActorType = ActorType.USER,
        resource_type: str | None = None,
        resource_id: str | None = None,
        organization_id: str | None = None,
        workspace_id: str | None = None,
        project_id: str | None = None,
        previous_state: str | None = None,
        new_state: str | None = None,
        reason: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        await self._repositories.audit.record(
            AuditRecord(
                action=action,
                outcome=outcome,
                occurred_at=occurred_at,
                actor_type=actor_type,
                actor_user_id=actor_user_id,
                actor_label=actor_label,
                channel=self._request.channel,
                resource_type=resource_type,
                resource_id=resource_id,
                organization_id=organization_id,
                workspace_id=workspace_id,
                project_id=project_id,
                previous_state=previous_state,
                new_state=new_state,
                reason=reason,
                detail=detail or {},
                correlation_id=self._request.correlation_id,
                request_ip_hash=self._request.ip_hash,
                user_agent_summary=self._request.user_agent_summary,
            )
        )

    async def security(
        self,
        *,
        event_kind: str,
        outcome: AuditOutcome,
        occurred_at: datetime,
        subject_user_id: str | None = None,
        subject_identifier_hash: str | None = None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        await self._repositories.security_events.record(
            SecurityRecord(
                event_kind=event_kind,
                outcome=outcome,
                occurred_at=occurred_at,
                subject_user_id=subject_user_id,
                subject_identifier_hash=subject_identifier_hash,
                request_ip_hash=self._request.ip_hash,
                user_agent_summary=self._request.user_agent_summary,
                correlation_id=self._request.correlation_id,
                detail=detail or {},
            )
        )

    async def event(
        self,
        *,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        occurred_at: datetime,
        workspace_id: str | None = None,
        payload: dict[str, Any] | None = None,
        idempotency_suffix: str | None = None,
    ) -> None:
        event_key = f"{event_type}:{aggregate_id}:{idempotency_suffix or occurred_at.isoformat()}"
        await self._repositories.outbox.publish(
            DomainEvent(
                event_type=event_type,
                aggregate_type=aggregate_type,
                aggregate_id=aggregate_id,
                occurred_at=occurred_at,
                event_key=event_key,
                workspace_id=workspace_id,
                payload=payload or {},
                correlation_id=self._request.correlation_id,
            )
        )


__all__ = ["ActivityRecorder"]
