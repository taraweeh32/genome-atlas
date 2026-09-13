"""Platform administration of accounts and platform roles.

These operations are platform-scoped: an organization administrator can never
reach them, however privileged they are inside their own organization. Each one
is checked as a *privileged* operation so a step-up (MFA) requirement can be
enforced by configuration without changing any call site.

Suspension and deactivation are reversible reachability changes. They never
delete an account's resources, and they always revoke live sessions so the
change takes effect immediately rather than at the next expiry.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.identity.dependencies import IdentityServices
from app.domain.authorization.context import ActorContext
from app.domain.authorization.permissions import Permission
from app.domain.errors import ConflictError, NotFoundError, ValidationError
from app.domain.events import EventType
from app.domain.identity.entities import UserAccount
from app.domain.lifecycle import require_transition
from app.domain.value_objects.enums import AccountState, AuditOutcome, PlatformRole


@dataclass(frozen=True, slots=True)
class ListAccountsQuery:
    actor: ActorContext
    page: Page
    request: RequestContext
    query: str | None = None


class ListAccounts:
    def __init__(self, services: IdentityServices) -> None:
        self._services = services

    async def execute(self, query: ListAccountsQuery) -> Paged[UserAccount]:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            await self._services.authorization.require(
                query.actor,
                Permission.PLATFORM_USER_READ,
                recorder=recorder,
                occurred_at=now,
            )
            return await repositories.users.list_accounts(page=query.page, query=query.query)


@dataclass(frozen=True, slots=True)
class ChangeAccountLifecycleCommand:
    actor: ActorContext
    user_id: str
    target_state: AccountState
    reason: str | None
    request: RequestContext


class ChangeAccountLifecycle:
    """Suspend, reactivate or deactivate an account."""

    _EVENTS = {
        AccountState.SUSPENDED: EventType.USER_SUSPENDED,
        AccountState.ACTIVE: EventType.USER_REACTIVATED,
        AccountState.DEACTIVATED: EventType.USER_DEACTIVATED,
    }

    def __init__(self, services: IdentityServices) -> None:
        self._services = services

    async def execute(self, command: ChangeAccountLifecycleCommand) -> UserAccount:
        if command.target_state not in self._EVENTS:
            raise ValidationError(
                "unsupported account lifecycle target",
                details={"field": "state", "allowed": sorted(s.value for s in self._EVENTS)},
            )
        if command.target_state is AccountState.SUSPENDED and not (command.reason or "").strip():
            raise ValidationError("a suspension reason is required", details={"field": "reason"})

        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            await self._services.authorization.require(
                command.actor,
                Permission.PLATFORM_USER_LIFECYCLE,
                recorder=recorder,
                occurred_at=now,
            )
            self._services.authorization.require_privileged(
                command.actor,
                Permission.PLATFORM_USER_LIFECYCLE,
                require_mfa=self._services.policy.require_mfa_for_platform_administration,
            )
            if command.actor.actor_id == command.user_id:
                # An administrator must not be able to lock themselves out, and
                # self-service state changes are not an administrative action.
                raise ConflictError("an administrator cannot change their own account state")

            account = await repositories.users.get(command.user_id)
            if account is None:
                raise NotFoundError("user", command.user_id)
            previous = account.account_state
            target = require_transition("account", previous, command.target_state)
            account = await repositories.users.save(
                replace(
                    account,
                    account_state=target,
                    suspended_at=now if target is AccountState.SUSPENDED else None,
                    suspension_reason=(
                        command.reason if target is AccountState.SUSPENDED else None
                    ),
                    deactivated_at=now if target is AccountState.DEACTIVATED else None,
                )
            )
            revoked = 0
            if target is not AccountState.ACTIVE:
                # The change must bite immediately, not at the next expiry.
                revoked = await self._services.sessions.revoke_every_session(
                    repositories, account.id, reason=f"account_{target.value}", moment=now
                )
            await recorder.audit(
                action=f"user.{target.value}",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="user",
                resource_id=account.id,
                previous_state=previous.value,
                new_state=target.value,
                reason=command.reason,
                detail={"revoked_sessions": revoked, "resources_preserved": True},
            )
            await recorder.security(
                event_kind=f"account.{target.value}",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                subject_user_id=account.id,
                detail={"actor_id": command.actor.actor_id},
            )
            await recorder.event(
                event_type=self._EVENTS[target],
                aggregate_type="user",
                aggregate_id=account.id,
                occurred_at=now,
            )
            return account


@dataclass(frozen=True, slots=True)
class ChangePlatformRoleCommand:
    actor: ActorContext
    user_id: str
    role: PlatformRole
    grant: bool
    request: RequestContext


class ChangePlatformRole:
    """Grant or revoke a platform role. The most privileged operation here."""

    def __init__(self, services: IdentityServices) -> None:
        self._services = services

    async def execute(self, command: ChangePlatformRoleCommand) -> None:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            await self._services.authorization.require(
                command.actor,
                Permission.PLATFORM_ROLE_MANAGE,
                recorder=recorder,
                occurred_at=now,
            )
            self._services.authorization.require_privileged(
                command.actor,
                Permission.PLATFORM_ROLE_MANAGE,
                require_mfa=self._services.policy.require_mfa_for_platform_administration,
            )
            if command.actor.actor_id == command.user_id:
                # Self-elevation and self-demotion are both refused: privilege
                # changes always involve a second person.
                raise ConflictError("an administrator cannot change their own platform roles")

            account = await repositories.users.get(command.user_id)
            if account is None:
                raise NotFoundError("user", command.user_id)
            if command.grant:
                await repositories.platform_roles.grant(
                    account.id,
                    command.role,
                    granted_by=command.actor.actor_id or "",
                    moment=now,
                )
            else:
                await repositories.platform_roles.revoke(account.id, command.role, moment=now)
                # A revoked privilege must not survive in a live session.
                await self._services.sessions.revoke_every_session(
                    repositories, account.id, reason="platform_role_revoked", moment=now
                )
            await recorder.audit(
                action="platform_role.granted" if command.grant else "platform_role.revoked",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="platform_role_assignment",
                resource_id=account.id,
                detail={"role": command.role.value},
            )
            await recorder.security(
                event_kind="platform_role.changed",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                subject_user_id=account.id,
                detail={
                    "role": command.role.value,
                    "granted": command.grant,
                    "actor_id": command.actor.actor_id,
                },
            )


__all__ = [
    "ChangeAccountLifecycle",
    "ChangeAccountLifecycleCommand",
    "ChangePlatformRole",
    "ChangePlatformRoleCommand",
    "ListAccounts",
    "ListAccountsQuery",
]
