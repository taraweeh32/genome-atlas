"""Registration, email verification and verification resend.

Security properties enforced here, not by the caller:

* **No account enumeration.** Registering an address that already exists returns
  the same generic acknowledgement as a new registration, and records a security
  event instead of telling the caller.
* **Registration never signs anyone in.** A new account is
  ``pending_verification`` and holds no session until verification succeeds.
* **Every account gets a personal workspace** in the same transaction, so a user
  who belongs to no organization still has somewhere to work.
* **Tokens are single-use and hash-stored**, and issuing a new one invalidates the
  previous one.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.identity.dependencies import IdentityServices
from app.domain.errors import RateLimitedError, ValidationError
from app.domain.events import EventType
from app.domain.identity.email import clean_email
from app.domain.identity.entities import Credentials, CredentialToken, UserAccount
from app.domain.lifecycle import require_transition
from app.domain.value_objects.enums import (
    AccountState,
    AuditOutcome,
    CredentialTokenKind,
    CredentialTokenState,
    DeletionState,
    EmailVerificationState,
    WorkspaceKind,
)
from app.domain.workspace.entities import Workspace
from app.infrastructure.persistence.repositories.base import new_id


@dataclass(frozen=True, slots=True)
class RegisterUserCommand:
    email: str
    password: str
    display_name: str
    request: RequestContext


@dataclass(frozen=True, slots=True)
class RegistrationResult:
    """Deliberately uninformative about whether an account was created."""

    accepted: bool = True
    #: Present only in non-production environments, where no mail transport is
    #: configured. Clearly named so it can never be mistaken for a normal field.
    development_only_verification_token: str | None = None


class RegisterUser:
    def __init__(self, services: IdentityServices) -> None:
        self._services = services

    async def execute(self, command: RegisterUserCommand) -> RegistrationResult:
        limiter_key = f"registration:{command.request.rate_limit_key or 'unknown'}"
        decision = await self._services.rate_limiter.check(
            limiter_key,
            limit=self._services.policy.registration_rate_limit_attempts,
            window_seconds=self._services.policy.registration_rate_limit_window_seconds,
        )
        if not decision.allowed:
            raise RateLimitedError(decision.retry_after_seconds)

        email, email_normalized = clean_email(command.email)
        display_name = (command.display_name or "").strip()
        if not display_name:
            raise ValidationError("a display name is required", details={"field": "display_name"})
        self._services.password_policy.validate(command.password, email=email_normalized)

        now = self._services.clock.now()
        password_hash = self._services.passwords.hash(command.password)
        raw_token, token_hash = self._services.tokens.mint_with_hash()

        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            existing = await repositories.users.get_by_email(email_normalized)
            if existing is not None:
                await recorder.security(
                    event_kind="registration.duplicate_email",
                    outcome=AuditOutcome.DENIED,
                    occurred_at=now,
                    subject_identifier_hash=self._services.tokens.hash(email_normalized),
                )
                return RegistrationResult(accepted=True)

            account = UserAccount(
                id=new_id("usr"),
                email=email,
                email_normalized=email_normalized,
                display_name=display_name,
                account_state=AccountState.PENDING_VERIFICATION,
                email_verification_state=EmailVerificationState.PENDING,
                deletion_state=DeletionState.ACTIVE,
            )
            account = await repositories.users.add(account)
            await repositories.credentials.create(
                Credentials(
                    user_id=account.id,
                    password_hash=password_hash,
                    password_algorithm=self._services.passwords.algorithm,
                    password_updated_at=now,
                )
            )

            workspace = Workspace(
                id=new_id("wsp"),
                kind=WorkspaceKind.PERSONAL,
                name=f"{display_name}'s workspace",
                owner_user_id=account.id,
                created_by=account.id,
            )
            await repositories.workspaces.add(workspace)
            await repositories.users.set_personal_workspace(account.id, workspace.id)

            await repositories.credential_tokens.create(
                CredentialToken(
                    id=new_id("ctk"),
                    user_id=account.id,
                    kind=CredentialTokenKind.EMAIL_VERIFICATION,
                    state=CredentialTokenState.ACTIVE,
                    expires_at=now
                    + timedelta(hours=self._services.policy.email_verification_ttl_hours),
                ),
                token_hash=token_hash,
            )

            await recorder.audit(
                action="user.registered",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=account.id,
                actor_label=account.email_normalized,
                resource_type="user",
                resource_id=account.id,
                new_state=account.account_state.value,
            )
            await recorder.audit(
                action="workspace.created",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=account.id,
                resource_type="workspace",
                resource_id=workspace.id,
                workspace_id=workspace.id,
                detail={"kind": WorkspaceKind.PERSONAL.value},
            )
            await recorder.event(
                event_type=EventType.USER_REGISTERED,
                aggregate_type="user",
                aggregate_id=account.id,
                occurred_at=now,
                idempotency_suffix=account.id,
            )

        return RegistrationResult(
            accepted=True,
            development_only_verification_token=(
                raw_token if self._services.expose_development_tokens else None
            ),
        )


@dataclass(frozen=True, slots=True)
class VerifyEmailCommand:
    token: str
    request: RequestContext


@dataclass(frozen=True, slots=True)
class VerifyEmailResult:
    verified: bool
    #: Organization invitations waiting for this address, so the UI can offer
    #: them. Accepting one is always a separate, explicit action.
    pending_invitation_count: int = 0


class VerifyEmail:
    def __init__(self, services: IdentityServices) -> None:
        self._services = services

    async def execute(self, command: VerifyEmailCommand) -> VerifyEmailResult:
        now = self._services.clock.now()
        token_hash = self._services.tokens.hash(command.token or "")
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            token = await repositories.credential_tokens.get_by_token_hash(token_hash)
            if (
                token is None
                or token.kind is not CredentialTokenKind.EMAIL_VERIFICATION
                or not token.is_usable_at(now)
            ):
                await recorder.security(
                    event_kind="email_verification.invalid_token",
                    outcome=AuditOutcome.FAILURE,
                    occurred_at=now,
                )
                # One generic failure for unknown, expired and already-used tokens.
                raise ValidationError("the verification link is not valid or has expired")

            account = await repositories.users.get(token.user_id)
            if account is None:
                raise ValidationError("the verification link is not valid or has expired")

            await repositories.credential_tokens.consume(token.id, moment=now)

            if account.email_verification_state is not EmailVerificationState.VERIFIED:
                verification_state = require_transition(
                    "email_verification",
                    account.email_verification_state,
                    EmailVerificationState.VERIFIED,
                )
                account_state = account.account_state
                if account_state is AccountState.PENDING_VERIFICATION:
                    account_state = require_transition(
                        "account", account_state, AccountState.ACTIVE
                    )
                account = await repositories.users.save(
                    replace(
                        account,
                        email_verification_state=verification_state,
                        account_state=account_state,
                        email_verified_at=now,
                    )
                )
                await recorder.audit(
                    action="user.email_verified",
                    outcome=AuditOutcome.SUCCESS,
                    occurred_at=now,
                    actor_user_id=account.id,
                    resource_type="user",
                    resource_id=account.id,
                    previous_state=AccountState.PENDING_VERIFICATION.value,
                    new_state=account.account_state.value,
                )
                await recorder.event(
                    event_type=EventType.USER_EMAIL_VERIFIED,
                    aggregate_type="user",
                    aggregate_id=account.id,
                    occurred_at=now,
                    idempotency_suffix=token.id,
                )

            invitations = await repositories.organization_invitations.list_open_for_email(
                account.email_normalized
            )
        return VerifyEmailResult(verified=True, pending_invitation_count=len(invitations))


@dataclass(frozen=True, slots=True)
class ResendVerificationCommand:
    email: str
    request: RequestContext


class ResendVerification:
    """Always reports success; only actually re-issues for an unverified account."""

    def __init__(self, services: IdentityServices) -> None:
        self._services = services

    async def execute(self, command: ResendVerificationCommand) -> RegistrationResult:
        limiter_key = f"verification-resend:{command.request.rate_limit_key or 'unknown'}"
        decision = await self._services.rate_limiter.check(
            limiter_key,
            limit=self._services.policy.registration_rate_limit_attempts,
            window_seconds=self._services.policy.registration_rate_limit_window_seconds,
        )
        if not decision.allowed:
            raise RateLimitedError(decision.retry_after_seconds)

        _, email_normalized = clean_email(command.email)
        now = self._services.clock.now()
        raw_token, token_hash = self._services.tokens.mint_with_hash()

        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            account = await repositories.users.get_by_email(email_normalized)
            if account is None or (
                account.email_verification_state is EmailVerificationState.VERIFIED
            ):
                await recorder.security(
                    event_kind="email_verification.resend_ignored",
                    outcome=AuditOutcome.DENIED,
                    occurred_at=now,
                    subject_identifier_hash=self._services.tokens.hash(email_normalized),
                )
                return RegistrationResult(accepted=True)

            await repositories.credential_tokens.invalidate_active(
                account.id,
                CredentialTokenKind.EMAIL_VERIFICATION,
                reason="superseded_by_resend",
                moment=now,
            )
            await repositories.credential_tokens.create(
                CredentialToken(
                    id=new_id("ctk"),
                    user_id=account.id,
                    kind=CredentialTokenKind.EMAIL_VERIFICATION,
                    state=CredentialTokenState.ACTIVE,
                    expires_at=now
                    + timedelta(hours=self._services.policy.email_verification_ttl_hours),
                ),
                token_hash=token_hash,
            )
            await recorder.security(
                event_kind="email_verification.resent",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                subject_user_id=account.id,
            )
        return RegistrationResult(
            accepted=True,
            development_only_verification_token=(
                raw_token if self._services.expose_development_tokens else None
            ),
        )


__all__ = [
    "RegisterUser",
    "RegisterUserCommand",
    "RegistrationResult",
    "ResendVerification",
    "ResendVerificationCommand",
    "VerifyEmail",
    "VerifyEmailCommand",
    "VerifyEmailResult",
]
