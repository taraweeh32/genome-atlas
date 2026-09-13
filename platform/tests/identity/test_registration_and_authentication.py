"""Registration, verification and authentication behaviour.

These assert the security properties, not just the happy path: uniform responses
that cannot be used to enumerate accounts, single-use tokens, no session before
verification, lockout, and session revocation on password change.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.application.use_cases.identity.authentication import (
    AuthenticateUser,
    AuthenticateUserCommand,
    ChangePassword,
    ChangePasswordCommand,
    CompletePasswordReset,
    CompletePasswordResetCommand,
    RequestPasswordReset,
    RequestPasswordResetCommand,
)
from app.application.use_cases.identity.registration import (
    RegisterUser,
    RegisterUserCommand,
    ResendVerification,
    ResendVerificationCommand,
    VerifyEmail,
    VerifyEmailCommand,
)
from app.domain.errors import AuthenticationError, ValidationError
from app.domain.value_objects.enums import (
    AccountState,
    EmailVerificationState,
    SessionState,
    WorkspaceKind,
)
from tests.support.services import STRONG_PASSWORD, build_harness


async def register(harness, email: str = "scientist@example.org") -> str:
    """Register and verify an account; returns its id."""
    result = await RegisterUser(harness.identity).execute(
        RegisterUserCommand(
            email=email,
            password=STRONG_PASSWORD,
            display_name="A Scientist",
            request=harness.request,
        )
    )
    await VerifyEmail(harness.identity).execute(
        VerifyEmailCommand(
            token=result.development_only_verification_token, request=harness.request
        )
    )
    account = await harness.repositories.users.get_by_email(email.lower())
    return account.id


async def test_registration_creates_pending_account_and_personal_workspace() -> None:
    harness = build_harness()

    await RegisterUser(harness.identity).execute(
        RegisterUserCommand(
            email="New.User@Example.org",
            password=STRONG_PASSWORD,
            display_name="New User",
            request=harness.request,
        )
    )

    account = await harness.repositories.users.get_by_email("new.user@example.org")
    assert account is not None
    # The address is normalized for uniqueness but the original is preserved.
    assert account.email == "New.User@Example.org"
    assert account.account_state is AccountState.PENDING_VERIFICATION
    assert account.email_verification_state is EmailVerificationState.PENDING

    workspace = await harness.repositories.workspaces.get_personal_for_user(account.id)
    assert workspace is not None
    assert workspace.kind is WorkspaceKind.PERSONAL
    assert workspace.organization_id is None
    # Registration alone never establishes a session.
    assert harness.repositories.sessions.rows == {}


async def test_registration_stores_no_recoverable_password() -> None:
    harness = build_harness()
    await RegisterUser(harness.identity).execute(
        RegisterUserCommand(
            email="hashed@example.org",
            password=STRONG_PASSWORD,
            display_name="Hashed",
            request=harness.request,
        )
    )

    account = await harness.repositories.users.get_by_email("hashed@example.org")
    credentials = await harness.repositories.credentials.get(account.id)
    assert credentials.password_hash is not None
    assert STRONG_PASSWORD not in credentials.password_hash
    assert credentials.password_hash.startswith("$argon2")


async def test_duplicate_registration_is_indistinguishable_from_a_new_one() -> None:
    harness = build_harness()
    command = RegisterUserCommand(
        email="taken@example.org",
        password=STRONG_PASSWORD,
        display_name="Taken",
        request=harness.request,
    )
    first = await RegisterUser(harness.identity).execute(command)
    second = await RegisterUser(harness.identity).execute(command)

    # Same accepted response: the endpoint cannot be used to discover accounts.
    assert first.accepted and second.accepted
    assert len(harness.repositories.users.rows) == 1


async def test_weak_password_is_rejected_before_any_account_exists() -> None:
    harness = build_harness()
    with pytest.raises(ValidationError):
        await RegisterUser(harness.identity).execute(
            RegisterUserCommand(
                email="weak@example.org",
                password="short",
                display_name="Weak",
                request=harness.request,
            )
        )
    assert harness.repositories.users.rows == {}


async def test_verification_token_is_single_use() -> None:
    harness = build_harness()
    result = await RegisterUser(harness.identity).execute(
        RegisterUserCommand(
            email="once@example.org",
            password=STRONG_PASSWORD,
            display_name="Once",
            request=harness.request,
        )
    )
    token = result.development_only_verification_token

    await VerifyEmail(harness.identity).execute(
        VerifyEmailCommand(token=token, request=harness.request)
    )
    with pytest.raises((AuthenticationError, ValidationError)):
        await VerifyEmail(harness.identity).execute(
            VerifyEmailCommand(token=token, request=harness.request)
        )


async def test_resending_verification_invalidates_the_previous_token() -> None:
    harness = build_harness()
    first = await RegisterUser(harness.identity).execute(
        RegisterUserCommand(
            email="resend@example.org",
            password=STRONG_PASSWORD,
            display_name="Resend",
            request=harness.request,
        )
    )
    second = await ResendVerification(harness.identity).execute(
        ResendVerificationCommand(email="resend@example.org", request=harness.request)
    )
    assert second.development_only_verification_token != (
        first.development_only_verification_token
    )

    with pytest.raises((AuthenticationError, ValidationError)):
        await VerifyEmail(harness.identity).execute(
            VerifyEmailCommand(
                token=first.development_only_verification_token, request=harness.request
            )
        )


async def test_resending_verification_for_an_unknown_address_reveals_nothing() -> None:
    harness = build_harness()
    result = await ResendVerification(harness.identity).execute(
        ResendVerificationCommand(email="nobody@example.org", request=harness.request)
    )
    assert result.accepted
    assert result.development_only_verification_token is None


async def test_unverified_account_cannot_authenticate() -> None:
    harness = build_harness()
    await RegisterUser(harness.identity).execute(
        RegisterUserCommand(
            email="unverified@example.org",
            password=STRONG_PASSWORD,
            display_name="Unverified",
            request=harness.request,
        )
    )
    with pytest.raises(AuthenticationError):
        await AuthenticateUser(harness.identity).execute(
            AuthenticateUserCommand(
                email="unverified@example.org",
                password=STRONG_PASSWORD,
                request=harness.request,
            )
        )


async def test_authentication_issues_an_opaque_session_with_a_csrf_secret() -> None:
    harness = build_harness()
    await register(harness, "signin@example.org")

    result = await AuthenticateUser(harness.identity).execute(
        AuthenticateUserCommand(
            email="signin@example.org", password=STRONG_PASSWORD, request=harness.request
        )
    )

    assert result.issued.session_token
    assert result.issued.csrf_token
    stored = harness.repositories.sessions.rows[result.issued.session.id]
    # Only hashes are persisted; the raw tokens exist solely in this response.
    assert result.issued.session_token not in harness.repositories.sessions.token_hashes
    assert stored.csrf_token_hash != result.issued.csrf_token


async def test_wrong_password_and_unknown_account_fail_identically() -> None:
    harness = build_harness()
    await register(harness, "known@example.org")

    with pytest.raises(AuthenticationError) as wrong:
        await AuthenticateUser(harness.identity).execute(
            AuthenticateUserCommand(
                email="known@example.org", password="Wrong-Password-1234", request=harness.request
            )
        )
    with pytest.raises(AuthenticationError) as unknown:
        await AuthenticateUser(harness.identity).execute(
            AuthenticateUserCommand(
                email="ghost@example.org", password=STRONG_PASSWORD, request=harness.request
            )
        )
    assert str(wrong.value) == str(unknown.value)


async def test_repeated_failures_lock_the_account() -> None:
    harness = build_harness()
    await register(harness, "lockme@example.org")

    for _ in range(harness.policy.max_failed_authentication_attempts):
        with pytest.raises(AuthenticationError):
            await AuthenticateUser(harness.identity).execute(
                AuthenticateUserCommand(
                    email="lockme@example.org",
                    password="Wrong-Password-1234",
                    request=harness.request,
                )
            )

    # Even the correct password is refused while the lock stands.
    with pytest.raises(AuthenticationError):
        await AuthenticateUser(harness.identity).execute(
            AuthenticateUserCommand(
                email="lockme@example.org", password=STRONG_PASSWORD, request=harness.request
            )
        )


async def test_password_reset_consumes_the_token_and_revokes_sessions() -> None:
    harness = build_harness()
    await register(harness, "reset@example.org")
    signed_in = await AuthenticateUser(harness.identity).execute(
        AuthenticateUserCommand(
            email="reset@example.org", password=STRONG_PASSWORD, request=harness.request
        )
    )

    requested = await RequestPasswordReset(harness.identity).execute(
        RequestPasswordResetCommand(email="reset@example.org", request=harness.request)
    )
    await CompletePasswordReset(harness.identity).execute(
        CompletePasswordResetCommand(
            token=requested.development_only_reset_token,
            new_password="Replacement-Passphrase-7",
            request=harness.request,
        )
    )

    assert (
        harness.repositories.sessions.rows[signed_in.issued.session.id].state
        is SessionState.REVOKED
    )
    # The old password no longer works; the new one does.
    with pytest.raises(AuthenticationError):
        await AuthenticateUser(harness.identity).execute(
            AuthenticateUserCommand(
                email="reset@example.org", password=STRONG_PASSWORD, request=harness.request
            )
        )
    await AuthenticateUser(harness.identity).execute(
        AuthenticateUserCommand(
            email="reset@example.org",
            password="Replacement-Passphrase-7",
            request=harness.request,
        )
    )


async def test_password_reset_for_an_unknown_address_reveals_nothing() -> None:
    harness = build_harness()
    result = await RequestPasswordReset(harness.identity).execute(
        RequestPasswordResetCommand(email="nobody@example.org", request=harness.request)
    )
    assert result.accepted
    assert result.development_only_reset_token is None


async def test_password_change_requires_the_current_password() -> None:
    harness = build_harness()
    user_id = await register(harness, "change@example.org")
    signed_in = await AuthenticateUser(harness.identity).execute(
        AuthenticateUserCommand(
            email="change@example.org", password=STRONG_PASSWORD, request=harness.request
        )
    )

    with pytest.raises(ValidationError):
        await ChangePassword(harness.identity).execute(
            ChangePasswordCommand(
                user_id=user_id,
                session_id=signed_in.issued.session.id,
                current_password="Not-The-Current-One-1",
                new_password="Replacement-Passphrase-7",
                request=harness.request,
            )
        )


async def test_password_change_keeps_the_current_session_and_drops_the_others() -> None:
    harness = build_harness()
    user_id = await register(harness, "sessions@example.org")
    first = await AuthenticateUser(harness.identity).execute(
        AuthenticateUserCommand(
            email="sessions@example.org", password=STRONG_PASSWORD, request=harness.request
        )
    )
    harness.advance_to(harness.clock.now() + timedelta(minutes=1))
    second = await AuthenticateUser(harness.identity).execute(
        AuthenticateUserCommand(
            email="sessions@example.org", password=STRONG_PASSWORD, request=harness.request
        )
    )

    await ChangePassword(harness.identity).execute(
        ChangePasswordCommand(
            user_id=user_id,
            session_id=second.issued.session.id,
            current_password=STRONG_PASSWORD,
            new_password="Replacement-Passphrase-7",
            request=harness.request,
        )
    )

    rows = harness.repositories.sessions.rows
    assert rows[second.issued.session.id].state is SessionState.ACTIVE
    assert rows[first.issued.session.id].state is SessionState.REVOKED
