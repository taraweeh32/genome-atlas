"""Audit, security-event, outbox and notification repositories.

All four are append-only from the application's point of view: there is no update
or delete method, because rewriting history is not an operation this platform
offers. They are written inside the *same* transaction as the state change that
caused them, so a committed change is always accompanied by its record.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import insert

from app.application.repositories import AuditRecord, SecurityRecord
from app.domain.events import DomainEvent
from app.domain.value_objects.enums import NotificationState, OutboxState
from app.infrastructure.persistence.models.governance import (
    AuditEvent,
    DomainEventOutbox,
    SecurityEvent,
)
from app.infrastructure.persistence.models.notification import Notification
from app.infrastructure.persistence.repositories.base import SqlRepository, new_id

_AUDIT = AuditEvent.__table__
_SECURITY = SecurityEvent.__table__
_OUTBOX = DomainEventOutbox.__table__
_NOTIFICATIONS = Notification.__table__


class SqlAuditRepository(SqlRepository):
    async def record(self, record: AuditRecord) -> None:
        await self._session.execute(
            insert(_AUDIT).values(
                id=new_id("aud"),
                occurred_at=record.occurred_at,
                action=record.action,
                actor_type=record.actor_type.value,
                actor_user_id=record.actor_user_id,
                actor_label=record.actor_label,
                channel=record.channel.value,
                outcome=record.outcome.value,
                resource_type=record.resource_type,
                resource_id=record.resource_id,
                organization_id=record.organization_id,
                workspace_id=record.workspace_id,
                project_id=record.project_id,
                previous_state=record.previous_state,
                new_state=record.new_state,
                detail=record.detail or None,
                reason=record.reason,
                correlation_id=record.correlation_id,
                request_ip_hash=record.request_ip_hash,
                user_agent_summary=record.user_agent_summary,
            )
        )


class SqlSecurityEventRepository(SqlRepository):
    async def record(self, record: SecurityRecord) -> None:
        await self._session.execute(
            insert(_SECURITY).values(
                id=new_id("sec"),
                occurred_at=record.occurred_at,
                event_kind=record.event_kind,
                outcome=record.outcome.value,
                subject_user_id=record.subject_user_id,
                subject_identifier_hash=record.subject_identifier_hash,
                request_ip_hash=record.request_ip_hash,
                detail=record.detail or None,
            )
        )


class SqlOutboxRepository(SqlRepository):
    async def publish(self, event: DomainEvent) -> None:
        await self._session.execute(
            insert(_OUTBOX).values(
                id=new_id("evt"),
                event_key=event.event_key,
                event_type=event.event_type,
                event_version=1,
                occurred_at=event.occurred_at,
                aggregate_type=event.aggregate_type,
                aggregate_id=event.aggregate_id,
                workspace_id=event.workspace_id,
                payload=event.payload or None,
                state=OutboxState.PENDING.value,
                available_at=event.occurred_at,
                correlation_id=event.correlation_id,
            )
        )


class SqlNotificationRepository(SqlRepository):
    async def create(
        self,
        *,
        recipient_user_id: str,
        notification_kind: str,
        subject: str,
        body: str | None,
        occurred_at: datetime,
        organization_id: str | None = None,
        workspace_id: str | None = None,
        project_id: str | None = None,
        subject_resource_type: str | None = None,
        subject_resource_id: str | None = None,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> str:
        identifier = new_id("ntf")
        await self._session.execute(
            insert(_NOTIFICATIONS).values(
                id=identifier,
                recipient_user_id=recipient_user_id,
                workspace_id=workspace_id,
                project_id=project_id,
                notification_kind=notification_kind,
                state=NotificationState.UNREAD.value,
                subject=subject,
                body=body,
                subject_resource_type=subject_resource_type,
                subject_resource_id=subject_resource_id,
                # Payload carries identifiers only — never a token, never content.
                payload=payload or None,
                correlation_id=correlation_id,
                version=1,
            )
        )
        return identifier


__all__ = [
    "SqlAuditRepository",
    "SqlNotificationRepository",
    "SqlOutboxRepository",
    "SqlSecurityEventRepository",
]
