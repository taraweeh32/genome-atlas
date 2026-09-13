"""Session lifecycle, CSRF binding and platform administration.

Sessions are server-authoritative: the client holds an opaque token and nothing
else. Administration is platform-scoped and cannot be reached from an
organization role.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.application.repositories import Page
from app.application.use_cases.identity.administration import (
    ChangeAccountLifecycle,
    ChangeAccountLifecycleCommand,
    ChangePlatformRole,
    ChangePlatformRoleCommand,
    ListAccounts,
    ListAccountsQuery,
)
from app.application.use_cases.identity.authentication import (
    AuthenticateUser,
    AuthenticateUserCommand,
)
from app.domain.errors import AuthenticationError, AuthorizationError, ConflictError
from app.domain.value_objects.enums import AccountState, PlatformRole, SessionState
from tests.support.actors import actor_for, create_account, grant_platform_role
from tests.support.services import STRONG_PASSWORD, build_harness

PAGE = Page(number=1, size=25)


async def sign_in(harness, email: str):
    return await AuthenticateUser(harness.identity).execute(
        AuthenticateUserCommand(
            email=email, password=STRONG_PASSWORD, request=harness.request
        )
    )


async def test_a_session_token_resolves_only_while_it_is_valid() -> None:
    harness = build_harness()
    await create_account(harness, "session@example.org")
    issued = (await sign_in(harness, "session@example.org")).issued

    async with harness.unit_of_work.begin() as repositories:
        resolved = await harness.sessions.resolve(
            repositories, issued.session_token, moment=harness.clock.now()
        )
        assert resolved.session.id == issued.session.id

    # An unknown token fails exactly like a revoked one.
    async with harness.unit_of_work.begin() as repositories:
        with pytest.raises(AuthenticationError):
            await harness.sessions.resolve(
                repositories, "not-a-real-token", moment=harness.clock.now()
            )


async def test_an_expired_session_is_refused() -> None:
    harness = build_harness()
    await create_account(harness, "expiry@example.org")
    issued = (await sign_in(harness, "expiry@example.org")).issued

    harness.advance_to(
        issued.session.absolute_expires_at + timedelta(minutes=1)
    )
    async with harness.unit_of_work.begin() as repositories:
        with pytest.raises(AuthenticationError):
            await harness.sessions.resolve(
                repositories, issued.session_token, moment=harness.clock.now()
            )


async def test_idle_expiry_slides_but_never_past_the_absolute_limit() -> None:
    harness = build_harness()
    await create_account(harness, "sliding@example.org")
    issued = (await sign_in(harness, "sliding@example.org")).issued

    # Keep using the session inside the idle window; the idle expiry moves with
    # activity but is capped by the absolute limit.
    while harness.clock.now() < issued.session.absolute_expires_at - timedelta(minutes=30):
        harness.advance_to(harness.clock.now() + timedelta(minutes=30))
        async with harness.unit_of_work.begin() as repositories:
            await harness.sessions.resolve(
                repositories, issued.session_token, moment=harness.clock.now()
            )

    refreshed = harness.repositories.sessions.rows[issued.session.id]
    assert refreshed.expires_at > harness.clock.now()
    assert refreshed.expires_at <= refreshed.absolute_expires_at


async def test_csrf_verification_is_bound_to_the_session() -> None:
    harness = build_harness()
    await create_account(harness, "csrf@example.org")
    first = (await sign_in(harness, "csrf@example.org")).issued
    harness.advance_to(harness.clock.now() + timedelta(minutes=1))
    second = (await sign_in(harness, "csrf@example.org")).issued

    harness.sessions.verify_csrf(first.session, first.csrf_token)
    # Another session's token is not accepted, and neither is a missing one.
    with pytest.raises(AuthenticationError):
        harness.sessions.verify_csrf(first.session, second.csrf_token)
    with pytest.raises(AuthenticationError):
        harness.sessions.verify_csrf(first.session, None)


async def test_a_suspended_account_loses_its_session_on_the_next_request() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "suspended@example.org")
    issued = (await sign_in(harness, "suspended@example.org")).issued

    admin_id = await create_account(harness, "admin@example.org", "Admin")
    await grant_platform_role(harness, admin_id, PlatformRole.PLATFORM_ADMINISTRATOR)
    await ChangeAccountLifecycle(harness.identity).execute(
        ChangeAccountLifecycleCommand(
            actor=await actor_for(harness, admin_id),
            user_id=user_id,
            target_state=AccountState.SUSPENDED,
            reason="policy violation under investigation",
            request=harness.request,
        )
    )

    async with harness.unit_of_work.begin() as repositories:
        with pytest.raises(AuthenticationError):
            await harness.sessions.resolve(
                repositories, issued.session_token, moment=harness.clock.now()
            )
    assert (
        harness.repositories.sessions.rows[issued.session.id].state is SessionState.REVOKED
    )


async def test_reauthentication_is_required_once_the_window_passes() -> None:
    harness = build_harness()
    await create_account(harness, "reauth@example.org")
    issued = (await sign_in(harness, "reauth@example.org")).issued

    assert not harness.sessions.requires_reauthentication(
        issued.session, moment=harness.clock.now()
    )
    later = harness.clock.now() + timedelta(
        minutes=harness.policy.reauthentication_window_minutes + 1
    )
    assert harness.sessions.requires_reauthentication(issued.session, moment=later)


async def test_only_a_platform_administrator_may_list_or_change_accounts() -> None:
    harness = build_harness()
    ordinary_id = await create_account(harness, "ordinary@example.org")
    actor = await actor_for(harness, ordinary_id)

    with pytest.raises(AuthorizationError):
        await ListAccounts(harness.identity).execute(
            ListAccountsQuery(actor=actor, page=PAGE, request=harness.request)
        )
    with pytest.raises(AuthorizationError):
        await ChangeAccountLifecycle(harness.identity).execute(
            ChangeAccountLifecycleCommand(
                actor=actor,
                user_id=ordinary_id,
                target_state=AccountState.SUSPENDED,
                reason="attempted self-service suspension",
                request=harness.request,
            )
        )
    with pytest.raises(AuthorizationError):
        await ChangePlatformRole(harness.identity).execute(
            ChangePlatformRoleCommand(
                actor=actor,
                user_id=ordinary_id,
                role=PlatformRole.PLATFORM_ADMINISTRATOR,
                grant=True,
                request=harness.request,
            )
        )


async def test_a_platform_administrator_cannot_lock_themselves_out() -> None:
    harness = build_harness()
    admin_id = await create_account(harness, "admin@example.org", "Admin")
    await grant_platform_role(harness, admin_id, PlatformRole.PLATFORM_ADMINISTRATOR)
    actor = await actor_for(harness, admin_id)

    with pytest.raises(ConflictError):
        await ChangeAccountLifecycle(harness.identity).execute(
            ChangeAccountLifecycleCommand(
                actor=actor,
                user_id=admin_id,
                target_state=AccountState.SUSPENDED,
                reason="mistake",
                request=harness.request,
            )
        )
    with pytest.raises(ConflictError):
        await ChangePlatformRole(harness.identity).execute(
            ChangePlatformRoleCommand(
                actor=actor,
                user_id=admin_id,
                role=PlatformRole.PLATFORM_ADMINISTRATOR,
                grant=False,
                request=harness.request,
            )
        )


async def test_granting_a_platform_role_is_visible_in_the_next_resolution() -> None:
    harness = build_harness()
    admin_id = await create_account(harness, "admin@example.org", "Admin")
    await grant_platform_role(harness, admin_id, PlatformRole.PLATFORM_ADMINISTRATOR)
    target_id = await create_account(harness, "operator@example.org")

    await ChangePlatformRole(harness.identity).execute(
        ChangePlatformRoleCommand(
            actor=await actor_for(harness, admin_id),
            user_id=target_id,
            role=PlatformRole.PLATFORM_OPERATOR,
            grant=True,
            request=harness.request,
        )
    )

    actor = await actor_for(harness, target_id)
    assert PlatformRole.PLATFORM_OPERATOR in actor.platform_roles
    # An operator is still not an administrator.
    with pytest.raises(AuthorizationError):
        await ChangePlatformRole(harness.identity).execute(
            ChangePlatformRoleCommand(
                actor=actor,
                user_id=admin_id,
                role=PlatformRole.PLATFORM_ADMINISTRATOR,
                grant=False,
                request=harness.request,
            )
        )


async def test_administrative_actions_are_written_to_the_audit_trail() -> None:
    harness = build_harness()
    admin_id = await create_account(harness, "admin@example.org", "Admin")
    await grant_platform_role(harness, admin_id, PlatformRole.PLATFORM_ADMINISTRATOR)
    target_id = await create_account(harness, "target@example.org")

    await ChangeAccountLifecycle(harness.identity).execute(
        ChangeAccountLifecycleCommand(
            actor=await actor_for(harness, admin_id),
            user_id=target_id,
            target_state=AccountState.SUSPENDED,
            reason="under investigation",
            request=harness.request,
        )
    )

    actions = [record.action for record in harness.repositories.audit.records]
    assert any("suspend" in action or "state" in action for action in actions)
