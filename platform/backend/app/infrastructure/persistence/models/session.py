"""Session and credential-token persistence (Package 3).

Sessions are server-authoritative: the browser holds an opaque token, the
platform stores only its hash, and every request re-resolves the session from the
database. Revocation is therefore immediate and does not depend on token
expiry, which is exactly what a stateless JWT could not provide.

Credential tokens (email verification, password reset) follow the same rule: only
a hash is persisted, single-use consumption is recorded, and superseding a token
invalidates the previous one.

These tables live in the ``app`` schema because they are account state, not
operational bookkeeping; the security *event* trail stays in ``platform``.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.domain.value_objects.enums import (
    CredentialTokenKind,
    CredentialTokenState,
    SessionState,
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


class UserSession(Base, TimestampMixin, ConcurrencyMixin):
    """One authenticated session."""

    __tablename__ = "user_sessions"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
        state_check("state", SessionState, "state_valid"),
        Index("ix_user_sessions_user_id_state", "user_id", "state"),
        Index("ix_user_sessions_expires_at", "expires_at"),
    )

    id: Mapped[str] = id_column()
    user_id: Mapped[str] = fk_column("app.users.id")
    #: SHA-256 of the opaque session token. The token itself is never stored.
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    #: Double-submit CSRF secret, bound to this session and hashed like the token.
    csrf_token_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=SessionState.ACTIVE.value
    )
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Idle expiry, extended by activity within the absolute lifetime.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Hard ceiling; never extended, so a session cannot live forever.
    absolute_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: Set only by a real second-factor verification (MFA package), never by input.
    mfa_satisfied: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    reauthenticated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Hashed client attributes: enough to spot session anomalies, not a log of
    #: personal network identifiers.
    ip_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_agent_summary: Mapped[str | None] = mapped_column(String(255), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[dict | None] = json_column()


class UserCredentialToken(Base, TimestampMixin, ConcurrencyMixin):
    """A single-use email-verification or password-reset token (hash only)."""

    __tablename__ = "user_credential_tokens"
    __table_args__ = (
        UniqueConstraint("token_hash", name="uq_user_credential_tokens_token_hash"),
        state_check("kind", CredentialTokenKind, "kind_valid"),
        state_check("state", CredentialTokenState, "state_valid"),
        Index("ix_user_credential_tokens_user_id_kind_state", "user_id", "kind", "state"),
        Index("ix_user_credential_tokens_expires_at", "expires_at"),
    )

    id: Mapped[str] = id_column()
    user_id: Mapped[str] = fk_column("app.users.id")
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=CredentialTokenState.ACTIVE.value
    )
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    #: How many times this token was presented; a high count is a security signal.
    presentation_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    requested_ip_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: Why the token was invalidated (e.g. superseded by a newer request).
    invalidation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


__all__ = ["UserCredentialToken", "UserSession"]
