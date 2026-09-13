"""Authentication, sign-out, password reset and password change.

Security properties enforced here:

* **Uniform failure.** Unknown address, wrong password, unverified email, locked
  or suspended account all produce the same ``AuthenticationError``. An unknown
  address still spends a full password verification so response time does not
  reveal existence.
* **Lockout.** Consecutive failures are counted server-side and lock the
  credential for a configured period; a successful authentication clears them.
* **Rate limiting** by origin, before any database work.
* **Credential change invalidates sessions.** A password reset revokes every
  session; a voluntary change keeps only the session that performed it.
* **Reset tokens are single-use, hash-stored and mutually invalidating**, and a
  reset never reveals whether the address exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.identity.dependencies import IdentityServices
from app.domain.errors import AuthenticationError, RateLimitedError, ValidationError
from app.domain.events import EventType
from app.domain.identity.email import clean_email
from app.domain.identity.entities import CredentialToken, IssuedSession, UserAccount
from app.domain.value_objects.enums import (
    AuditOutcome,
    CredentialTokenKind,
    CredentialTokenState,
    EmailVerificationState,
)
from app.infrastructure.persistence.repositories.base import new_id

#: One message for every authentication failure mode.
_GENERIC_FAILURE = "the email address or password is not correct"


@dataclass(frozen=True, slots=True)
class AuthenticateUserCommand:
    email: str
    password: str
    request: RequestContext


@dataclass(frozen=True, slots=True)
class AuthenticationResult:
    account: UserAccount
    issued: IssuedSession


class AuthenticateUser:
    def __init__(self, services: IdentityServices) -> None:
        self._services = services

    async def execute(self, command: AuthenticateUserCommand) -> AuthenticationResult:
        policy = self._services.policy
        _, email_normalized = clean_email(command.email)
        origin = command.request.rate_limit_key or "unknown"
        for key in (
            f"authentication:origin:{origin}",
            f"authentication:subject:{self._services.tokens.hash(email_normalized)}",
        ):
            decision = await self._services.rate_limiter.check(
                key,
                limit=policy.authentication_rate_limit_attempts,
                window_seconds=policy.authentication_rate_limit_window_seconds,
            )
            if not decision.allowed:
                raise RateLimitedError(decision.retry_after_seconds)

        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            account = await repositories.users.get_by_email(email_normalized)
            credentials = (
                await repositories.credentials.get(account.id) if account is not None else None
            )

            if account is None or credentials is None or credentials.password_hash is None:
                # Spend comparable work, then fail exactly like a wrong password.
                self._services.passwords.dummy_verify()
                await self._fail(
                    recorder,
                    now,
                    reason="unknown_account",
                    subject_identifier_hash=self._services.tokens.hash(email_normalized),
                )

            if credentials.is_locked_at(now):
                await self._fail(
                    recorder, now, reason="account_locked", subject_user_id=account.id
                )

            verification = self._services.passwords.verify(
                command.password, credentials.password_hash
            )
            if not verification.valid:
                attempts = credentials.failed_attempt_count + 1
                lock_until = (
                    now + timedelta(minutes=policy.account_lockout_minutes)
                    if attempts >= policy.max_failed_authentication_attempts
                    else None
                )
                await repositories.credentials.register_failure(
                    account.id, moment=now, lock_until=lock_until
                )
                await self._fail(
                    recorder,
                    now,
                    reason="invalid_password",
                    subject_user_id=account.id,
                    detail={"locked": lock_until is not None},
                )

            if not account.can_authenticate:
                await self._fail(
                    recorder,
                    now,
                    reason=f"account_state:{account.account_state.value}",
                    subject_user_id=account.id,
                )
            if (
                policy.require_email_verification_for_login
                and account.email_verification_state is not EmailVerificationState.VERIFIED
            ):
                await self._fail(
                    recorder, now, reason="email_unverified", subject_user_id=account.id
                )

            if verification.needs_rehash:
                # Transparently upgrade the stored hash to current parameters.
                await repositories.credentials.replace_password(
                    account.id,
                    password_hash=self._services.passwords.hash(command.password),
                    algorithm=self._services.passwords.algorithm,
                    moment=now,
                )
            await repositories.credentials.register_success(account.id, moment=now)
            await repositories.users.touch_activity(account.id, now)

            issued = await self._services.sessions.issue(
                repositories,
                account,
                moment=now,
                request=command.request,
                mfa_satisfied=not credentials.mfa_enabled,
            )

            await recorder.audit(
                action="user.authenticated",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=account.id,
                actor_label=account.email_normalized,
                resource_type="session",
                resource_id=issued.session.id,
            )
            await recorder.security(
                event_kind="authentication.succeeded",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                subject_user_id=account.id,
                detail={"session_id": issued.session.id},
            )
            await recorder.event(
                event_type=EventType.USER_AUTHENTICATED,
                aggregate_type="user",
                aggregate_id=account.id,
                occurred_at=now,
                idempotency_suffix=issued.session.id,
            )
        return AuthenticationResult(account=account, issued=issued)

    async def _fail(
        self,
        recorder: ActivityRecorder,
        moment: datetime,
        *,
        reason: str,
        subject_user_id: str | None = None,
        subject_identifier_hash: str | None = None,
        detail: dict | None = None,
    ) -> None:
        """Record the real reason, then raise the uniform failure."""
        await recorder.security(
            event_kind="authentication.failed",
            outcome=AuditOutcome.FAILURE,
            occurred_at=moment,
            subject_user_id=subject_user_id,
            subject_identifier_hash=subject_identifier_hash,
            detail={"reason": reason, **(detail or {})},
        )
        raise AuthenticationError(_GENERIC_FAILURE)


@dataclass(frozen=True, slots=True)
class SignOutCommand:
    session_id: str
    user_id: str
    request: RequestContext
    #: Sign out everywhere, not just this device.
    all_sessions: bool = False


class SignOut:
    def __init__(self, services: IdentityServices) -> None:
        self._services = services

    async def execute(self, command: SignOutCommand) -> None:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            if command.all_sessions:
                revoked = await self._services.sessions.revoke_every_session(
                    repositories, command.user_id, reason="user_signed_out_everywhere", moment=now
                )
            else:
                await self._services.sessions.revoke(
                    repositories, command.session_id, reason="user_signed_out", moment=now
                )
                revoked = 1
            await recorder.audit(
                action="user.signed_out",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.user_id,
                resource_type="session",
                resource_id=command.session_id,
                detail={"revoked_sessions": revoked, "scope": "all" if command.all_sessions else "current"},
            )


@dataclass(frozen=True, slots=True)
class RequestPasswordResetCommand:
    email: str
    request: RequestContext


@dataclass(frozen=True, slots=True)
class PasswordResetRequestResult:
    accepted: bool = True
    development_only_reset_token: str | None = None


class RequestPasswordReset:
    def __init__(self, services: IdentityServices) -> None:
        self._services = services

    async def execute(self, command: RequestPasswordResetCommand) -> PasswordResetRequestResult:
        decision = await self._services.rate_limiter.check(
            f"password-reset:{command.request.rate_limit_key or 'unknown'}",
            limit=self._services.policy.registration_rate_limit_attempts,
            window_seconds=self._services.policy.registration_rate_limit_window_seconds,
        )
        if not decision.allowed:
            raise RateLimitedError(decision.retry_after_seconds)

        _, email_normalized = clean_email(command.email)
        now = self._services.clock.now()
        raw_token, token_hash = self._services.tokens.mint_with_hash()
        issued = False

        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            account = await repositories.users.get_by_email(email_normalized)
            if account is not None and account.can_authenticate:
                await repositories.credential_tokens.invalidate_active(
                    account.id,
                    CredentialTokenKind.PASSWORD_RESET,
                    reason="superseded_by_new_request",
                    moment=now,
                )
                await repositories.credential_tokens.create(
                    CredentialToken(
                        id=new_id("ctk"),
                        user_id=account.id,
                        kind=CredentialTokenKind.PASSWORD_RESET,
                        state=CredentialTokenState.ACTIVE,
                        expires_at=now
                        + timedelta(minutes=self._services.policy.password_reset_ttl_minutes),
                    ),
                    token_hash=token_hash,
                )
                issued = True
                await recorder.event(
                    event_type=EventType.USER_PASSWORD_RESET_REQUESTED,
                    aggregate_type="user",
                    aggregate_id=account.id,
                    occurred_at=now,
                )
            await recorder.security(
                event_kind="password_reset.requested",
                outcome=AuditOutcome.SUCCESS if issued else AuditOutcome.DENIED,
                occurred_at=now,
                subject_user_id=account.id if account else None,
                subject_identifier_hash=self._services.tokens.hash(email_normalized),
            )
        return PasswordResetRequestResult(
            accepted=True,
            development_only_reset_token=(
                raw_token if issued and self._services.expose_development_tokens else None
            ),
        )


@dataclass(frozen=True, slots=True)
class CompletePasswordResetCommand:
    token: str
    new_password: str
    request: RequestContext


class CompletePasswordReset:
    """Consumes the token, replaces the password and ends every session."""

    def __init__(self, services: IdentityServices) -> None:
        self._services = services

    async def execute(self, command: CompletePasswordResetCommand) -> None:
        now = self._services.clock.now()
        token_hash = self._services.tokens.hash(command.token or "")
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            token = await repositories.credential_tokens.get_by_token_hash(token_hash)
            if (
                token is None
                or token.kind is not CredentialTokenKind.PASSWORD_RESET
                or not token.is_usable_at(now)
            ):
                await recorder.security(
                    event_kind="password_reset.invalid_token",
                    outcome=AuditOutcome.FAILURE,
                    occurred_at=now,
                )
                raise ValidationError("the password reset link is not valid or has expired")

            account = await repositories.users.get(token.user_id)
            if account is None or not account.can_authenticate:
                raise ValidationError("the password reset link is not valid or has expired")

            self._services.password_policy.validate(
                command.new_password, email=account.email_normalized
            )
            await repositories.credential_tokens.consume(token.id, moment=now)
            await repositories.credentials.replace_password(
                account.id,
                password_hash=self._services.passwords.hash(command.new_password),
                algorithm=self._services.passwords.algorithm,
                moment=now,
            )
            revoked = await self._services.sessions.revoke_every_session(
                repositories, account.id, reason="password_reset", moment=now
            )
            await recorder.audit(
                action="user.password_reset",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=account.id,
                resource_type="user",
                resource_id=account.id,
                detail={"revoked_sessions": revoked},
            )
            await recorder.event(
                event_type=EventType.USER_PASSWORD_RESET_COMPLETED,
                aggregate_type="user",
                aggregate_id=account.id,
                occurred_at=now,
                idempotency_suffix=token.id,
            )


@dataclass(frozen=True, slots=True)
class ChangePasswordCommand:
    user_id: str
    session_id: str
    current_password: str
    new_password: str
    request: RequestContext


class ChangePassword:
    """A signed-in change. The current password is always required."""

    def __init__(self, services: IdentityServices) -> None:
        self._services = services

    async def execute(self, command: ChangePasswordCommand) -> None:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            account = await repositories.users.get(command.user_id)
            credentials = await repositories.credentials.get(command.user_id)
            if account is None or credentials is None or credentials.password_hash is None:
                raise AuthenticationError("authentication is required")
            if not self._services.passwords.verify(
                command.current_password, credentials.password_hash
            ).valid:
                await recorder.security(
                    event_kind="password_change.invalid_current_password",
                    outcome=AuditOutcome.FAILURE,
                    occurred_at=now,
                    subject_user_id=account.id,
                )
                raise ValidationError(
                    "the current password is not correct",
                    details={"field": "current_password"},
                )
            self._services.password_policy.validate(
                command.new_password, email=account.email_normalized
            )
            await repositories.credentials.replace_password(
                account.id,
                password_hash=self._services.passwords.hash(command.new_password),
                algorithm=self._services.passwords.algorithm,
                moment=now,
            )
            # Other devices lose their session; this one keeps working.
            revoked = await self._services.sessions.revoke_every_session(
                repositories,
                account.id,
                reason="password_changed",
                moment=now,
                keep_session_id=command.session_id,
            )
            await recorder.audit(
                action="user.password_changed",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=account.id,
                resource_type="user",
                resource_id=account.id,
                detail={"revoked_other_sessions": revoked},
            )


@dataclass(frozen=True, slots=True)
class CurrentIdentity:
    account: UserAccount
    personal_workspace_id: str | None
    platform_roles: tuple[str, ...]
    capabilities: tuple[str, ...]
    requires_reauthentication: bool


__all__ = [
    "AuthenticateUser",
    "AuthenticateUserCommand",
    "AuthenticationResult",
    "ChangePassword",
    "ChangePasswordCommand",
    "CompletePasswordReset",
    "CompletePasswordResetCommand",
    "CurrentIdentity",
    "PasswordResetRequestResult",
    "RequestPasswordReset",
    "RequestPasswordResetCommand",
    "SignOut",
    "SignOutCommand",
]
