"""Domain event names and the in-domain event record.

Events are published through the Package 2 transactional outbox
(``platform.domain_event_outbox``) in the same transaction as the state change
that caused them. They are *not* audit records and *not* notifications: audit
answers "who did what", notifications are a delivery concern, and an event is a
fact other parts of the platform may react to.

Naming convention (already established by the audit ``action`` column): dotted,
lowercase, ``<aggregate>.<past-tense-verb>``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


class EventType:
    USER_REGISTERED = "user.registered"
    USER_EMAIL_VERIFIED = "user.email_verified"
    USER_AUTHENTICATED = "user.authenticated"
    USER_PASSWORD_RESET_REQUESTED = "user.password_reset_requested"
    USER_PASSWORD_RESET_COMPLETED = "user.password_reset_completed"
    USER_SUSPENDED = "user.suspended"
    USER_REACTIVATED = "user.reactivated"
    USER_DEACTIVATED = "user.deactivated"

    ORGANIZATION_REQUESTED = "organization.requested"
    ORGANIZATION_APPROVED = "organization.approved"
    ORGANIZATION_REJECTED = "organization.rejected"
    ORGANIZATION_ACTIVATED = "organization.activated"
    ORGANIZATION_SUSPENDED = "organization.suspended"
    ORGANIZATION_REACTIVATED = "organization.reactivated"
    ORGANIZATION_DEACTIVATED = "organization.deactivated"
    ORGANIZATION_MEMBER_INVITED = "organization.member_invited"
    ORGANIZATION_MEMBER_JOINED = "organization.member_joined"
    ORGANIZATION_MEMBER_DECLINED = "organization.member_declined"
    ORGANIZATION_INVITATION_REVOKED = "organization.invitation_revoked"
    ORGANIZATION_MEMBER_REMOVED = "organization.member_removed"
    ORGANIZATION_ROLE_CHANGED = "organization.role_changed"

    WORKSPACE_CREATED = "workspace.created"

    PROJECT_CREATED = "project.created"
    PROJECT_ARCHIVED = "project.archived"
    PROJECT_REOPENED = "project.reopened"
    PROJECT_MEMBER_ADDED = "project.member_added"
    PROJECT_MEMBER_REMOVED = "project.member_removed"
    PROJECT_ROLE_CHANGED = "project.role_changed"


@dataclass(frozen=True, slots=True)
class DomainEvent:
    """One fact, ready to be written to the outbox.

    ``event_key`` is the idempotency key enforced by a unique index, so a retried
    use case cannot publish the same fact twice.
    """

    event_type: str
    aggregate_type: str
    aggregate_id: str
    occurred_at: datetime
    event_key: str
    workspace_id: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None


__all__ = ["DomainEvent", "EventType"]
