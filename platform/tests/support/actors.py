"""Helpers that build real actor contexts for tenancy tests.

Every actor is resolved through the production ``AuthorizationService`` against
the in-memory repositories, so no test invents an identity or a permission set.
"""

from __future__ import annotations

from app.application.use_cases.identity.registration import (
    RegisterUser,
    RegisterUserCommand,
    VerifyEmail,
    VerifyEmailCommand,
)
from app.domain.authorization.context import ActorContext
from app.domain.value_objects.enums import PlatformRole
from tests.support.services import STRONG_PASSWORD, Harness


async def create_account(harness: Harness, email: str, display_name: str = "Member") -> str:
    """Register and verify an account through the real use cases."""
    result = await RegisterUser(harness.identity).execute(
        RegisterUserCommand(
            email=email,
            password=STRONG_PASSWORD,
            display_name=display_name,
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


async def grant_platform_role(harness: Harness, user_id: str, role: PlatformRole) -> None:
    await harness.repositories.platform_roles.grant(
        user_id, role, granted_by=user_id, moment=harness.clock.now()
    )


async def actor_for(harness: Harness, user_id: str) -> ActorContext:
    """Resolve the current, authoritative context for an account."""
    async with harness.unit_of_work.begin() as repositories:
        account = await repositories.users.get(user_id)
        return await harness.authorization.resolve(repositories, account)


__all__ = ["actor_for", "create_account", "grant_platform_role"]
