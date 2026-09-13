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

    DATASET_CREATED = "dataset.created"
    DATASET_UPDATED = "dataset.updated"
    DATASET_ARCHIVED = "dataset.archived"
    DATASET_RESTORED = "dataset.restored"
    DATASET_SOFT_DELETED = "dataset.soft_deleted"
    DATASET_VERSION_CREATED = "dataset_version.created"
    DATASET_VERSION_ACCEPTED = "dataset_version.accepted"
    DATASET_VERSION_REJECTED = "dataset_version.rejected"
    DATASET_VERSION_SUPERSEDED = "dataset_version.superseded"

    UPLOAD_SESSION_CREATED = "upload_session.created"
    UPLOAD_SESSION_COMPLETED = "upload_session.completed"
    UPLOAD_SESSION_REJECTED = "upload_session.rejected"
    UPLOAD_SESSION_CANCELLED = "upload_session.cancelled"
    FILE_ARTIFACT_QUARANTINED = "file_artifact.quarantined"
    FILE_ARTIFACT_DOWNLOAD_AUTHORIZED = "file_artifact.download_authorized"

    IMPORT_SESSION_OPENED = "import_session.opened"
    IMPORT_SESSION_MAPPING_CONFIRMED = "import_session.mapping_confirmed"
    IMPORT_SESSION_SUBMITTED = "import_session.submitted"
    IMPORT_SESSION_ACCEPTED = "import_session.accepted"
    IMPORT_SESSION_REJECTED = "import_session.rejected"
    IMPORT_SESSION_ABANDONED = "import_session.abandoned"

    VALIDATION_RUN_STARTED = "validation_run.started"
    VALIDATION_RUN_COMPLETED = "validation_run.completed"

    ANALYSIS_CREATED = "analysis.created"
    ANALYSIS_UPDATED = "analysis.updated"
    ANALYSIS_ARCHIVED = "analysis.archived"
    ANALYSIS_SOFT_DELETED = "analysis.soft_deleted"
    ANALYSIS_CONFIGURATION_CREATED = "analysis_configuration.created"
    ANALYSIS_CONFIGURATION_ACTIVATED = "analysis_configuration.activated"

    ANALYSIS_EXECUTION_REQUESTED = "analysis_execution.requested"
    ANALYSIS_EXECUTION_QUEUED = "analysis_execution.queued"
    ANALYSIS_EXECUTION_STARTED = "analysis_execution.started"
    ANALYSIS_EXECUTION_SUBMITTED = "analysis_execution.submitted"
    ANALYSIS_EXECUTION_SUCCEEDED = "analysis_execution.succeeded"
    ANALYSIS_EXECUTION_FAILED = "analysis_execution.failed"
    ANALYSIS_EXECUTION_CANCEL_REQUESTED = "analysis_execution.cancel_requested"
    ANALYSIS_EXECUTION_CANCELLED = "analysis_execution.cancelled"

    JOB_ENQUEUED = "job.enqueued"
    JOB_CANCEL_REQUESTED = "job.cancel_requested"
    JOB_RECOVERED = "job.recovered"
    JOB_DEAD_LETTERED = "job.dead_lettered"

    SCHEDULE_CREATED = "schedule.created"
    SCHEDULE_UPDATED = "schedule.updated"
    SCHEDULE_ENABLED = "schedule.enabled"
    SCHEDULE_DISABLED = "schedule.disabled"
    SCHEDULE_ARCHIVED = "schedule.archived"
    SCHEDULE_TRIGGERED = "schedule.triggered"

    COMPUTE_NODE_REGISTERED = "compute_node.registered"
    COMPUTE_NODE_DRAINED = "compute_node.drained"
    COMPUTE_NODE_UNHEALTHY = "compute_node.unhealthy"


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
