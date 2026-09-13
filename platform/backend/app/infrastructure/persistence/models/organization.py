"""Organization, membership and invitation persistence.

Organization membership never implies access to every organization resource:
project access is a separate relationship (see ``project.py``).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import (
    DeletionState,
    InvitationState,
    MembershipState,
    OrganizationRole,
    OrganizationState,
)
from app.infrastructure.persistence.base import (
    Base,
    ConcurrencyMixin,
    RetentionMixin,
    TimestampMixin,
    fk_column,
    id_column,
    json_column,
    state_check,
)


class Organization(Base, TimestampMixin, ConcurrencyMixin, RetentionMixin):
    __tablename__ = "organizations"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_organizations_slug"),
        state_check("state", OrganizationState, "state_valid"),
        state_check("deletion_state", DeletionState, "deletion_state_valid"),
        Index("ix_organizations_state_deletion_state", "state", "deletion_state"),
    )

    id: Mapped[str] = id_column()
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=OrganizationState.REQUESTED.value
    )
    #: Requester is preserved for historical attribution even after they leave.
    requested_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_decided_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    approval_decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approval_decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metadata_json: Mapped[dict | None] = json_column()


class OrganizationSetting(Base, TimestampMixin, ConcurrencyMixin):
    """Organization-scoped settings. Precedence logic belongs to a later package."""

    __tablename__ = "organization_settings"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "setting_key", name="uq_organization_settings_organization_id_key"
        ),
    )

    id: Mapped[str] = id_column()
    organization_id: Mapped[str] = fk_column("app.organizations.id", ondelete="CASCADE")
    setting_key: Mapped[str] = mapped_column(String(128), nullable=False)
    setting_value: Mapped[dict | None] = json_column()
    updated_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)


class OrganizationMembership(Base, TimestampMixin, ConcurrencyMixin):
    __tablename__ = "organization_memberships"
    __table_args__ = (
        UniqueConstraint(
            "organization_id", "user_id", name="uq_organization_memberships_organization_id_user_id"
        ),
        state_check("role", OrganizationRole, "role_valid"),
        state_check("state", MembershipState, "state_valid"),
        Index("ix_organization_memberships_user_id_state", "user_id", "state"),
    )

    id: Mapped[str] = id_column()
    organization_id: Mapped[str] = fk_column("app.organizations.id")
    user_id: Mapped[str] = fk_column("app.users.id")
    role: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=OrganizationRole.MEMBER.value
    )
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=MembershipState.INVITED.value
    )
    invited_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: Leaving records a timestamp; it never deletes or transfers resources.
    left_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)


class OrganizationInvitation(Base, TimestampMixin, ConcurrencyMixin):
    __tablename__ = "organization_invitations"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_organization_invitations_token_hash"),
        state_check("role", OrganizationRole, "role_valid"),
        state_check("state", InvitationState, "state_valid"),
        Index(
            "ix_organization_invitations_organization_id_state",
            "organization_id",
            "state",
        ),
    )

    id: Mapped[str] = id_column()
    organization_id: Mapped[str] = fk_column("app.organizations.id", ondelete="CASCADE")
    invited_email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=InvitationState.PENDING.value
    )
    #: Only a hash of the invitation token is persisted.
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    invited_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_user_id: Mapped[str | None] = fk_column("app.users.id", nullable=True)
