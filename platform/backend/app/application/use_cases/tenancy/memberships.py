"""Organization invitations and memberships.

Rules the backend owns here:

* An invitation carries a **hashed, single-use, expiring** token. Accepting one
  requires that the signed-in account's verified address matches the invited
  address — knowing the token is not enough.
* Membership is the only thing an invitation grants. It never grants project
  access: that is a separate relationship (see ``projects.py``).
* An organization must always retain at least one active owner, so the last
  owner cannot be removed, demoted, or allowed to leave.
* Leaving or being removed records a timestamp and preserves every resource the
  member created or owns. Nothing is deleted or reassigned here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.tenancy.dependencies import TenancyServices
from app.domain.authorization.context import ActorContext
from app.domain.authorization.permissions import Permission
from app.domain.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.domain.events import EventType
from app.domain.identity.email import clean_email
from app.domain.lifecycle import require_transition
from app.domain.organization.entities import OrganizationInvitation, OrganizationMembership
from app.domain.value_objects.enums import (
    AuditOutcome,
    EmailVerificationState,
    InvitationState,
    MembershipState,
    OrganizationRole,
)
from app.infrastructure.persistence.repositories.base import new_id

#: Roles that keep an organization administrable. At least one active owner must
#: always remain.
_OWNER_ROLE = OrganizationRole.OWNER


async def _assert_not_last_owner(
    repositories,
    membership: OrganizationMembership,
    *,
    operation: str,
) -> None:
    if membership.role is not _OWNER_ROLE or not membership.is_active:
        return
    remaining = await repositories.organization_memberships.count_active_with_role(
        membership.organization_id, _OWNER_ROLE.value
    )
    if remaining <= 1:
        raise ConflictError(
            "an organization must always keep at least one active owner",
            details={"operation": operation, "role": _OWNER_ROLE.value},
        )


@dataclass(frozen=True, slots=True)
class InviteMemberCommand:
    actor: ActorContext
    organization_id: str
    email: str
    role: OrganizationRole
    request: RequestContext


@dataclass(frozen=True, slots=True)
class InvitationResult:
    invitation: OrganizationInvitation
    #: Non-production only. In production the token is delivered out of band.
    development_only_token: str | None = None


class InviteMember:
    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, command: InviteMemberCommand) -> InvitationResult:
        if command.role is _OWNER_ROLE:
            # Ownership is transferred deliberately, never handed out by invitation.
            raise ValidationError(
                "an owner cannot be created by invitation", details={"field": "role"}
            )
        _, email_normalized = clean_email(command.email)
        now = self._services.clock.now()
        raw_token, token_hash = self._services.tokens.mint_with_hash()

        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            await self._services.authorization.require(
                command.actor,
                Permission.ORGANIZATION_MEMBER_INVITE,
                recorder=recorder,
                occurred_at=now,
                organization_id=command.organization_id,
            )
            invited_account = await repositories.users.get_by_email(email_normalized)
            if invited_account is not None:
                existing = await repositories.organization_memberships.get(
                    command.organization_id, invited_account.id
                )
                if existing is not None and existing.is_active:
                    raise ConflictError("that person is already a member of this organization")
            if await repositories.organization_invitations.get_open_for_email(
                command.organization_id, email_normalized
            ) is not None:
                raise ConflictError("an invitation for that address is already outstanding")

            invitation = await repositories.organization_invitations.add(
                OrganizationInvitation(
                    id=new_id("inv"),
                    organization_id=command.organization_id,
                    invited_email_normalized=email_normalized,
                    role=command.role,
                    state=InvitationState.PENDING,
                    expires_at=now
                    + timedelta(hours=self._services.policy.invitation_ttl_hours),
                    invited_by=command.actor.actor_id,
                ),
                token_hash=token_hash,
            )
            await recorder.audit(
                action="organization.member_invited",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="organization_invitation",
                resource_id=invitation.id,
                organization_id=command.organization_id,
                new_state=invitation.state.value,
                detail={"role": command.role.value},
            )
            await recorder.event(
                event_type=EventType.ORGANIZATION_MEMBER_INVITED,
                aggregate_type="organization",
                aggregate_id=command.organization_id,
                occurred_at=now,
                idempotency_suffix=invitation.id,
            )
            if invited_account is not None:
                # An in-app notification for an existing account; email delivery
                # is a later package's responsibility.
                await repositories.notifications.create(
                    recipient_user_id=invited_account.id,
                    notification_kind="organization.invitation",
                    subject="You have been invited to an organization",
                    body=None,
                    occurred_at=now,
                    organization_id=command.organization_id,
                    subject_resource_type="organization_invitation",
                    subject_resource_id=invitation.id,
                )
        return InvitationResult(
            invitation=invitation,
            development_only_token=(
                raw_token if self._services.expose_development_tokens else None
            ),
        )


@dataclass(frozen=True, slots=True)
class ListInvitationsQuery:
    actor: ActorContext
    organization_id: str
    page: Page
    request: RequestContext


class ListInvitations:
    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, query: ListInvitationsQuery) -> Paged[OrganizationInvitation]:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            await self._services.authorization.require(
                query.actor,
                Permission.ORGANIZATION_INVITATION_READ,
                recorder=recorder,
                occurred_at=now,
                organization_id=query.organization_id,
            )
            return await repositories.organization_invitations.list_for_organization(
                query.organization_id, page=query.page
            )


@dataclass(frozen=True, slots=True)
class RevokeInvitationCommand:
    actor: ActorContext
    organization_id: str
    invitation_id: str
    request: RequestContext


class RevokeInvitation:
    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, command: RevokeInvitationCommand) -> None:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            await self._services.authorization.require(
                command.actor,
                Permission.ORGANIZATION_INVITATION_REVOKE,
                recorder=recorder,
                occurred_at=now,
                organization_id=command.organization_id,
            )
            invitation = await repositories.organization_invitations.get(command.invitation_id)
            # A mismatched organization is reported as not found: an identifier
            # from another tenant must not be confirmed as existing.
            if invitation is None or invitation.organization_id != command.organization_id:
                raise NotFoundError("organization_invitation", command.invitation_id)
            state = require_transition("invitation", invitation.state, InvitationState.REVOKED)
            await repositories.organization_invitations.save(
                replace(invitation, state=state, responded_at=now)
            )
            await recorder.audit(
                action="organization.invitation_revoked",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="organization_invitation",
                resource_id=invitation.id,
                organization_id=command.organization_id,
                previous_state=invitation.state.value,
                new_state=state.value,
            )
            await recorder.event(
                event_type=EventType.ORGANIZATION_INVITATION_REVOKED,
                aggregate_type="organization",
                aggregate_id=command.organization_id,
                occurred_at=now,
                idempotency_suffix=invitation.id,
            )


@dataclass(frozen=True, slots=True)
class RespondToInvitationCommand:
    actor: ActorContext
    token: str
    accept: bool
    request: RequestContext


class RespondToInvitation:
    """Accept or decline an invitation as the signed-in account.

    The token alone never grants membership: the invited address must match the
    actor's own verified address.
    """

    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, command: RespondToInvitationCommand) -> OrganizationMembership | None:
        actor = command.actor
        if actor.actor_id is None:
            raise AuthorizationError("authentication is required")
        now = self._services.clock.now()
        token_hash = self._services.tokens.hash(command.token or "")

        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            invitation = await repositories.organization_invitations.get_by_token_hash(token_hash)
            account = await repositories.users.get(actor.actor_id)
            if invitation is None or account is None or not invitation.is_open_at(now):
                await recorder.security(
                    event_kind="organization_invitation.invalid_token",
                    outcome=AuditOutcome.FAILURE,
                    occurred_at=now,
                    subject_user_id=actor.actor_id,
                )
                raise ValidationError("the invitation is not valid or has expired")

            if invitation.invited_email_normalized != account.email_normalized:
                await recorder.security(
                    event_kind="organization_invitation.recipient_mismatch",
                    outcome=AuditOutcome.DENIED,
                    occurred_at=now,
                    subject_user_id=actor.actor_id,
                    detail={"invitation_id": invitation.id},
                )
                raise AuthorizationError("this invitation was issued to a different address")
            if account.email_verification_state is not EmailVerificationState.VERIFIED:
                raise AuthorizationError(
                    "verify your email address before joining an organization"
                )

            if not command.accept:
                state = require_transition("invitation", invitation.state, InvitationState.DECLINED)
                await repositories.organization_invitations.save(
                    replace(
                        invitation,
                        state=state,
                        responded_at=now,
                        accepted_user_id=None,
                    )
                )
                await recorder.audit(
                    action="organization.invitation_declined",
                    outcome=AuditOutcome.SUCCESS,
                    occurred_at=now,
                    actor_user_id=actor.actor_id,
                    resource_type="organization_invitation",
                    resource_id=invitation.id,
                    organization_id=invitation.organization_id,
                    new_state=state.value,
                )
                await recorder.event(
                    event_type=EventType.ORGANIZATION_MEMBER_DECLINED,
                    aggregate_type="organization",
                    aggregate_id=invitation.organization_id,
                    occurred_at=now,
                    idempotency_suffix=invitation.id,
                )
                return None

            organization = await repositories.organizations.get(invitation.organization_id)
            if organization is None or not organization.is_usable:
                raise ConflictError("this organization is not currently accepting members")

            accepted = require_transition("invitation", invitation.state, InvitationState.ACCEPTED)
            await repositories.organization_invitations.save(
                replace(
                    invitation,
                    state=accepted,
                    responded_at=now,
                    accepted_user_id=actor.actor_id,
                )
            )

            existing = await repositories.organization_memberships.get(
                invitation.organization_id, actor.actor_id
            )
            if existing is None:
                membership = await repositories.organization_memberships.add(
                    OrganizationMembership(
                        id=new_id("omb"),
                        organization_id=invitation.organization_id,
                        user_id=actor.actor_id,
                        role=invitation.role,
                        state=MembershipState.ACTIVE,
                        invited_by=invitation.invited_by,
                        joined_at=now,
                    )
                )
            else:
                # A previous membership is reinstated rather than duplicated, so
                # the historical record of leaving is preserved.
                state = require_transition("membership", existing.state, MembershipState.ACTIVE)
                membership = await repositories.organization_memberships.save(
                    replace(
                        existing,
                        state=state,
                        role=invitation.role,
                        joined_at=now,
                        left_at=None,
                        removed_by=None,
                    )
                )

            await recorder.audit(
                action="organization.member_joined",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=actor.actor_id,
                resource_type="organization_membership",
                resource_id=membership.id,
                organization_id=invitation.organization_id,
                new_state=membership.state.value,
                detail={"role": membership.role.value},
            )
            await recorder.event(
                event_type=EventType.ORGANIZATION_MEMBER_JOINED,
                aggregate_type="organization",
                aggregate_id=invitation.organization_id,
                occurred_at=now,
                idempotency_suffix=membership.id,
            )
            return membership


@dataclass(frozen=True, slots=True)
class ListMyInvitationsQuery:
    actor: ActorContext
    request: RequestContext


class ListMyInvitations:
    """Open invitations addressed to the signed-in account's own address."""

    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(
        self, query: ListMyInvitationsQuery
    ) -> tuple[OrganizationInvitation, ...]:
        if query.actor.actor_id is None:
            raise AuthorizationError("authentication is required")
        async with self._services.unit_of_work.begin() as repositories:
            account = await repositories.users.get(query.actor.actor_id)
            if account is None:
                raise AuthorizationError("authentication is required")
            return await repositories.organization_invitations.list_open_for_email(
                account.email_normalized
            )


@dataclass(frozen=True, slots=True)
class ListMembersQuery:
    actor: ActorContext
    organization_id: str
    page: Page
    request: RequestContext


class ListMembers:
    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, query: ListMembersQuery) -> Paged[OrganizationMembership]:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            await self._services.authorization.require(
                query.actor,
                Permission.ORGANIZATION_MEMBER_READ,
                recorder=recorder,
                occurred_at=now,
                organization_id=query.organization_id,
            )
            return await repositories.organization_memberships.list_for_organization(
                query.organization_id, page=query.page
            )


@dataclass(frozen=True, slots=True)
class ChangeMemberRoleCommand:
    actor: ActorContext
    organization_id: str
    user_id: str
    role: OrganizationRole
    request: RequestContext


class ChangeMemberRole:
    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, command: ChangeMemberRoleCommand) -> OrganizationMembership:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            await self._services.authorization.require(
                command.actor,
                Permission.ORGANIZATION_MEMBER_ROLE_CHANGE,
                recorder=recorder,
                occurred_at=now,
                organization_id=command.organization_id,
            )
            membership = await repositories.organization_memberships.get(
                command.organization_id, command.user_id
            )
            if membership is None:
                raise NotFoundError("organization_membership", command.user_id)
            if membership.role is command.role:
                return membership
            if membership.role is _OWNER_ROLE:
                await _assert_not_last_owner(repositories, membership, operation="role_change")
            previous_role = membership.role
            membership = await repositories.organization_memberships.save(
                replace(membership, role=command.role)
            )
            await recorder.audit(
                action="organization.member_role_changed",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="organization_membership",
                resource_id=membership.id,
                organization_id=command.organization_id,
                detail={"previous_role": previous_role.value, "role": command.role.value},
            )
            await recorder.event(
                event_type=EventType.ORGANIZATION_ROLE_CHANGED,
                aggregate_type="organization",
                aggregate_id=command.organization_id,
                occurred_at=now,
                payload={"user_id": command.user_id, "role": command.role.value},
            )
            return membership


@dataclass(frozen=True, slots=True)
class EndMembershipCommand:
    actor: ActorContext
    organization_id: str
    user_id: str
    request: RequestContext
    #: True when the actor is leaving of their own accord.
    voluntary: bool = False


class EndMembership:
    """Remove a member, or leave. Resources are always preserved."""

    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, command: EndMembershipCommand) -> None:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            if command.voluntary:
                if command.actor.actor_id != command.user_id:
                    raise AuthorizationError("you may only leave on your own behalf")
            else:
                await self._services.authorization.require(
                    command.actor,
                    Permission.ORGANIZATION_MEMBER_REMOVE,
                    recorder=recorder,
                    occurred_at=now,
                    organization_id=command.organization_id,
                )
            membership = await repositories.organization_memberships.get(
                command.organization_id, command.user_id
            )
            if membership is None or not membership.is_active:
                raise NotFoundError("organization_membership", command.user_id)
            await _assert_not_last_owner(
                repositories, membership, operation="leave" if command.voluntary else "remove"
            )
            target = MembershipState.LEFT if command.voluntary else MembershipState.REMOVED
            state = require_transition("membership", membership.state, target)
            await repositories.organization_memberships.save(
                replace(
                    membership,
                    state=state,
                    left_at=now,
                    removed_by=None if command.voluntary else command.actor.actor_id,
                )
            )
            await recorder.audit(
                action="organization.member_left" if command.voluntary else "organization.member_removed",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="organization_membership",
                resource_id=membership.id,
                organization_id=command.organization_id,
                previous_state=membership.state.value,
                new_state=state.value,
                # Membership ended; owned and created resources are untouched.
                detail={"resources_preserved": True},
            )
            await recorder.event(
                event_type=EventType.ORGANIZATION_MEMBER_REMOVED,
                aggregate_type="organization",
                aggregate_id=command.organization_id,
                occurred_at=now,
                payload={"user_id": command.user_id, "voluntary": command.voluntary},
            )


__all__ = [
    "ChangeMemberRole",
    "ChangeMemberRoleCommand",
    "EndMembership",
    "EndMembershipCommand",
    "InvitationResult",
    "InviteMember",
    "InviteMemberCommand",
    "ListInvitations",
    "ListInvitationsQuery",
    "ListMembers",
    "ListMembersQuery",
    "ListMyInvitations",
    "ListMyInvitationsQuery",
    "RespondToInvitation",
    "RespondToInvitationCommand",
    "RevokeInvitation",
    "RevokeInvitationCommand",
]
