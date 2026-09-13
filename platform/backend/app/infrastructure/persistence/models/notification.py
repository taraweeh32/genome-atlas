"""Durable notifications and their delivery attempts.

This is the *domain* notification concern — durable, authorization-scoped and
auditable — and is unrelated to the frontend's transient toast infrastructure.
Delivery per channel is tracked separately from the notification itself, so a
failed email never destroys the in-app record.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import (
    DeliveryChannel,
    DeliveryState,
    NotificationState,
)
from app.infrastructure.persistence.base import (
    Base,
    ConcurrencyMixin,
    TimestampMixin,
    fk_column,
    id_column,
    json_column,
    state_check,
)


class Notification(Base, TimestampMixin, ConcurrencyMixin):
    __tablename__ = "notifications"
    __table_args__ = (
        state_check("state", NotificationState, "state_valid"),
        Index("ix_notifications_recipient_user_id_state", "recipient_user_id", "state"),
        Index("ix_notifications_created_at", "created_at"),
    )

    id: Mapped[str] = id_column()
    recipient_user_id: Mapped[str] = fk_column("app.users.id")
    #: Tenancy scope, so a notification is authorized like any other resource.
    workspace_id: Mapped[str | None] = fk_column("app.workspaces.id", nullable=True)
    project_id: Mapped[str | None] = fk_column("app.projects.id", nullable=True)
    #: Event category, e.g. ``analysis_completed``, ``review_assigned``.
    notification_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=NotificationState.UNREAD.value
    )
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Reference to the subject resource; never genomic content.
    subject_resource_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    subject_resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict | None] = json_column()
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class NotificationDelivery(Base, TimestampMixin):
    """One delivery attempt of one notification over one channel."""

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("notification_id", "channel", "attempt_number",
                         name="uq_notification_deliveries_notification_channel_attempt"),
        state_check("channel", DeliveryChannel, "channel_valid"),
        state_check("state", DeliveryState, "state_valid"),
        Index("ix_notification_deliveries_state", "state"),
    )

    id: Mapped[str] = id_column()
    notification_id: Mapped[str] = fk_column("app.notifications.id", ondelete="CASCADE")
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=DeliveryState.PENDING.value
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    job_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)


class NotificationPreference(Base, TimestampMixin, ConcurrencyMixin):
    """Per-user, per-kind, per-channel preference."""

    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "notification_kind", "channel",
                         name="uq_notification_preferences_user_id_kind_channel"),
        state_check("channel", DeliveryChannel, "channel_valid"),
    )

    id: Mapped[str] = id_column()
    user_id: Mapped[str] = fk_column("app.users.id", ondelete="CASCADE")
    notification_kind: Mapped[str] = mapped_column(String(128), nullable=False)
    channel: Mapped[str] = mapped_column(String(64), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, server_default="true")
