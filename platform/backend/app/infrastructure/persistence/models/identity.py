"""Identity and account persistence.

Package 2 persists account structure only: no password verification, session,
MFA or RBAC *enforcement* logic lives here. Credential material is stored as a
hash reference in a dedicated table so the account row can be read by ordinary
account queries without touching secrets.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import (
    AccountState,
    ActorType,
    DeletionState,
    EmailVerificationState,
    PlatformRole,
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


class User(Base, TimestampMixin, ConcurrencyMixin, RetentionMixin):
    """A platform account. Exists independently of any organization."""

    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email_normalized", name="uq_users_email_normalized"),
        state_check("account_state", AccountState, "account_state_valid"),
        state_check(
            "email_verification_state",
            EmailVerificationState,
            "email_verification_state_valid",
        ),
        state_check("deletion_state", DeletionState, "deletion_state_valid"),
        Index("ix_users_account_state_deletion_state", "account_state", "deletion_state"),
    )

    id: Mapped[str] = id_column()
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    #: Case-folded email; the uniqueness authority.
    email_normalized: Mapped[str] = mapped_column(String(320), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=AccountState.PENDING_VERIFICATION.value
    )
    email_verification_state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=EmailVerificationState.UNVERIFIED.value
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspension_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    deactivated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Personal workspace pointer; set once the workspace row exists. The
    #: workspace side carries the authoritative ownership relationship.
    personal_workspace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict | None] = json_column()


class UserAuthenticationMetadata(Base, TimestampMixin, ConcurrencyMixin):
    """Authentication-related account metadata, isolated from the account row."""

    __tablename__ = "user_authentication_metadata"
    __table_args__ = (UniqueConstraint("user_id", name="uq_user_authentication_metadata_user_id"),)

    id: Mapped[str] = id_column()
    user_id: Mapped[str] = fk_column("app.users.id")
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    password_algorithm: Mapped[str | None] = mapped_column(String(64), nullable=True)
    password_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    mfa_enrolled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_successful_authentication_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class UserPreference(Base, TimestampMixin, ConcurrencyMixin):
    """Personal, non-authoritative account preferences."""

    __tablename__ = "user_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "preference_key", name="uq_user_preferences_user_id_key"),
    )

    id: Mapped[str] = id_column()
    user_id: Mapped[str] = fk_column("app.users.id", ondelete="CASCADE")
    preference_key: Mapped[str] = mapped_column(String(128), nullable=False)
    preference_value: Mapped[dict | None] = json_column()


class PlatformRoleAssignment(Base, TimestampMixin):
    """Platform-level (not organization-level) privileged role assignment."""

    __tablename__ = "platform_role_assignments"
    __table_args__ = (
        UniqueConstraint("user_id", "role", name="uq_platform_role_assignments_user_id_role"),
        state_check("role", PlatformRole, "role_valid"),
    )

    id: Mapped[str] = id_column()
    user_id: Mapped[str] = fk_column("app.users.id", ondelete="CASCADE")
    role: Mapped[str] = mapped_column(String(64), nullable=False)
    granted_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    granted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ServiceAccount(Base, TimestampMixin, ConcurrencyMixin, RetentionMixin):
    """Non-human actor. Audit records distinguish it via ``actor_type``."""

    __tablename__ = "service_accounts"
    __table_args__ = (
        UniqueConstraint("name", name="uq_service_accounts_name"),
        state_check("deletion_state", DeletionState, "deletion_state_valid"),
        state_check("actor_type", ActorType, "actor_type_valid"),
    )

    id: Mapped[str] = id_column()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_type: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=ActorType.SERVICE_ACCOUNT.value
    )
    organization_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str | None] = fk_column("app.users.id", nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
