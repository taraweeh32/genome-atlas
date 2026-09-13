"""Identity domain entities.

Framework-free records the application layer works with. Repositories translate
between these and the Package 2 persistence models; nothing here imports
SQLAlchemy, and nothing here carries a cleartext secret.

Note what is *not* on ``UserAccount``: no role, no organization, no workspace
membership. Identity, roles and membership are separate concepts and are
resolved separately (see ``domain/authorization``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.domain.value_objects.enums import (
    AccountState,
    CredentialTokenKind,
    CredentialTokenState,
    DeletionState,
    EmailVerificationState,
    PlatformRole,
    SessionState,
)


@dataclass(frozen=True, slots=True)
class UserAccount:
    id: str
    email: str
    email_normalized: str
    display_name: str
    account_state: AccountState
    email_verification_state: EmailVerificationState
    deletion_state: DeletionState = DeletionState.ACTIVE
    personal_workspace_id: str | None = None
    email_verified_at: datetime | None = None
    suspended_at: datetime | None = None
    suspension_reason: str | None = None
    deactivated_at: datetime | None = None
    last_activity_at: datetime | None = None
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def can_authenticate(self) -> bool:
        """Only an active, non-deleted account may hold a session.

        A pending-verification account may sign in *only* to complete
        verification; that narrower rule is enforced by the authentication use
        case, which is where the policy belongs.
        """
        return (
            self.account_state is AccountState.ACTIVE
            and self.deletion_state is DeletionState.ACTIVE
        )


@dataclass(frozen=True, slots=True)
class Credentials:
    """Authentication material metadata. Never the password, never the hash's use."""

    user_id: str
    password_hash: str | None
    password_algorithm: str | None
    password_updated_at: datetime | None = None
    mfa_enabled: bool = False
    mfa_enrolled_at: datetime | None = None
    failed_attempt_count: int = 0
    locked_until: datetime | None = None
    last_successful_authentication_at: datetime | None = None
    version: int = 1

    def is_locked_at(self, moment: datetime) -> bool:
        return self.locked_until is not None and self.locked_until > moment


@dataclass(frozen=True, slots=True)
class Session:
    """A server-authoritative session.

    The client only ever holds an opaque token; the platform stores its hash, so
    a database disclosure does not yield usable session credentials.
    """

    id: str
    user_id: str
    state: SessionState
    issued_at: datetime
    expires_at: datetime
    absolute_expires_at: datetime
    last_seen_at: datetime | None = None
    revoked_at: datetime | None = None
    revocation_reason: str | None = None
    mfa_satisfied: bool = False
    reauthenticated_at: datetime | None = None
    ip_hash: str | None = None
    user_agent_summary: str | None = None
    #: Double-submit CSRF secret bound to this session.
    csrf_token_hash: str | None = None

    def is_valid_at(self, moment: datetime | None = None) -> bool:
        moment = moment or datetime.now(UTC)
        return (
            self.state is SessionState.ACTIVE
            and self.expires_at > moment
            and self.absolute_expires_at > moment
        )


@dataclass(frozen=True, slots=True)
class CredentialToken:
    """An email-verification or password-reset token, stored only as a hash."""

    id: str
    user_id: str
    kind: CredentialTokenKind
    state: CredentialTokenState
    expires_at: datetime
    consumed_at: datetime | None = None
    created_at: datetime | None = None

    def is_usable_at(self, moment: datetime) -> bool:
        return self.state is CredentialTokenState.ACTIVE and self.expires_at > moment


@dataclass(frozen=True, slots=True)
class PlatformRoleGrant:
    user_id: str
    role: PlatformRole
    granted_at: datetime | None = None
    revoked_at: datetime | None = None

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """Result of creating a session: the record plus the one-time secrets."""

    session: Session
    #: Returned to the transport layer once, to be set as an HttpOnly cookie.
    session_token: str = field(repr=False, default="")
    csrf_token: str = field(repr=False, default="")


__all__ = [
    "CredentialToken",
    "Credentials",
    "IssuedSession",
    "PlatformRoleGrant",
    "Session",
    "UserAccount",
]
