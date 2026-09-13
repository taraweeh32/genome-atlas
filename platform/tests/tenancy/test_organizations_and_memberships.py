"""Organization lifecycle, invitations and membership rules.

The emphasis is on the boundaries that must never be crossed: an organization
exists only after a platform decision, an organization administrator is not a
platform administrator, invitations are single-use and address-bound, and leaving
an organization destroys nothing.
"""

from __future__ import annotations

import pytest

from app.application.repositories import Page
from app.application.use_cases.tenancy.memberships import (
    ChangeMemberRole,
    ChangeMemberRoleCommand,
    EndMembership,
    EndMembershipCommand,
    InviteMember,
    InviteMemberCommand,
    ListMembers,
    ListMembersQuery,
    RespondToInvitation,
    RespondToInvitationCommand,
)
from app.application.use_cases.tenancy.organizations import (
    ChangeOrganizationLifecycle,
    ChangeOrganizationLifecycleCommand,
    DecideOrganizationRequest,
    DecideOrganizationRequestCommand,
    GetOrganization,
    GetOrganizationQuery,
    ListMyOrganizations,
    ListMyOrganizationsQuery,
    RequestOrganization,
    RequestOrganizationCommand,
    UpdateOrganization,
    UpdateOrganizationCommand,
)
from app.domain.errors import (
    AuthorizationError,
    ConcurrencyConflictError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.domain.value_objects.enums import (
    MembershipState,
    OrganizationRole,
    OrganizationState,
    PlatformRole,
    WorkspaceKind,
)
from tests.support.actors import actor_for, create_account, grant_platform_role
from tests.support.services import build_harness

PAGE = Page(number=1, size=25)


async def platform_admin(harness):
    user_id = await create_account(harness, "platform.admin@example.org", "Platform Admin")
    await grant_platform_role(harness, user_id, PlatformRole.PLATFORM_ADMINISTRATOR)
    return user_id


async def requested_organization(harness, owner_id: str, slug: str = "lab-alpha"):
    return await RequestOrganization(harness.tenancy).execute(
        RequestOrganizationCommand(
            actor=await actor_for(harness, owner_id),
            name="Lab Alpha",
            slug=slug,
            description=None,
            request=harness.request,
        )
    )


async def approved_organization(harness, owner_id: str, slug: str = "lab-alpha"):
    view = await requested_organization(harness, owner_id, slug)
    admin_id = await platform_admin(harness)
    return await DecideOrganizationRequest(harness.tenancy).execute(
        DecideOrganizationRequestCommand(
            actor=await actor_for(harness, admin_id),
            organization_id=view.organization.id,
            approve=True,
            reason=None,
            request=harness.request,
        )
    )


async def test_a_new_account_has_only_a_personal_workspace() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "solo@example.org")
    actor = await actor_for(harness, user_id)

    # Belonging to no organization is a normal, fully supported state.
    assert actor.usable_organization_ids() == frozenset()
    workspace = await harness.repositories.workspaces.get_personal_for_user(user_id)
    assert workspace.kind is WorkspaceKind.PERSONAL


async def test_requesting_an_organization_does_not_create_a_usable_one() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "requester@example.org")

    view = await requested_organization(harness, owner_id)

    assert view.organization.state is OrganizationState.REQUESTED
    # No workspace exists until a platform administrator approves the request.
    assert view.workspace_id is None


async def test_only_a_platform_administrator_may_decide_a_request() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "requester@example.org")
    other_id = await create_account(harness, "bystander@example.org")
    view = await requested_organization(harness, owner_id)

    for candidate in (owner_id, other_id):
        with pytest.raises(AuthorizationError):
            await DecideOrganizationRequest(harness.tenancy).execute(
                DecideOrganizationRequestCommand(
                    actor=await actor_for(harness, candidate),
                    organization_id=view.organization.id,
                    approve=True,
                    reason=None,
                    request=harness.request,
                )
            )


async def test_approval_provisions_the_organization_workspace_and_owner() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.org")

    view = await approved_organization(harness, owner_id)

    assert view.organization.state is OrganizationState.ACTIVE
    assert view.workspace_id is not None
    workspace = await harness.repositories.workspaces.get(view.workspace_id)
    assert workspace.kind is WorkspaceKind.ORGANIZATION
    assert workspace.organization_id == view.organization.id

    actor = await actor_for(harness, owner_id)
    assert actor.organization_role(view.organization.id) is OrganizationRole.OWNER


async def test_rejection_leaves_no_workspace_and_no_membership_reach() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.org")
    view = await requested_organization(harness, owner_id)
    admin_id = await platform_admin(harness)

    decided = await DecideOrganizationRequest(harness.tenancy).execute(
        DecideOrganizationRequestCommand(
            actor=await actor_for(harness, admin_id),
            organization_id=view.organization.id,
            approve=False,
            reason="insufficient justification",
            request=harness.request,
        )
    )

    assert decided.organization.state is OrganizationState.REJECTED
    assert decided.workspace_id is None
    actor = await actor_for(harness, owner_id)
    assert view.organization.id not in actor.usable_organization_ids()


async def test_an_unrelated_account_cannot_read_an_organization_by_id() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.org")
    view = await approved_organization(harness, owner_id)
    outsider_id = await create_account(harness, "outsider@example.org")

    # Knowing the identifier grants nothing.
    with pytest.raises((NotFoundError, AuthorizationError)):
        await GetOrganization(harness.tenancy).execute(
            GetOrganizationQuery(
                actor=await actor_for(harness, outsider_id),
                organization_id=view.organization.id,
                request=harness.request,
            )
        )


async def test_organization_listing_is_scoped_to_membership() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.org")
    await approved_organization(harness, owner_id)
    outsider_id = await create_account(harness, "outsider@example.org")

    mine = await ListMyOrganizations(harness.tenancy).execute(
        ListMyOrganizationsQuery(
            actor=await actor_for(harness, owner_id), page=PAGE, request=harness.request
        )
    )
    theirs = await ListMyOrganizations(harness.tenancy).execute(
        ListMyOrganizationsQuery(
            actor=await actor_for(harness, outsider_id), page=PAGE, request=harness.request
        )
    )

    assert len(mine.items) == 1
    assert theirs.items == ()


async def test_a_stale_update_is_rejected_rather_than_overwriting() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.org")
    view = await approved_organization(harness, owner_id)
    stale_version = view.organization.version

    await UpdateOrganization(harness.tenancy).execute(
        UpdateOrganizationCommand(
            actor=await actor_for(harness, owner_id),
            organization_id=view.organization.id,
            name="Lab Alpha Renamed",
            description=None,
            expected_version=stale_version,
            request=harness.request,
        )
    )
    with pytest.raises(ConcurrencyConflictError):
        await UpdateOrganization(harness.tenancy).execute(
            UpdateOrganizationCommand(
                actor=await actor_for(harness, owner_id),
                organization_id=view.organization.id,
                name="Renamed Again",
                description=None,
                expected_version=stale_version,
                request=harness.request,
            )
        )


async def test_an_organization_owner_cannot_act_as_a_platform_administrator() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.org")
    await approved_organization(harness, owner_id)
    other_owner_id = await create_account(harness, "other.owner@example.org")
    other = await requested_organization(harness, other_owner_id, slug="lab-beta")

    # No reach into another organization's request, and none into platform state.
    with pytest.raises(AuthorizationError):
        await DecideOrganizationRequest(harness.tenancy).execute(
            DecideOrganizationRequestCommand(
                actor=await actor_for(harness, owner_id),
                organization_id=other.organization.id,
                approve=True,
                reason=None,
                request=harness.request,
            )
        )
    with pytest.raises(AuthorizationError):
        await ChangeOrganizationLifecycle(harness.tenancy).execute(
            ChangeOrganizationLifecycleCommand(
                actor=await actor_for(harness, owner_id),
                organization_id=other.organization.id,
                target_state=OrganizationState.SUSPENDED,
                reason=None,
                request=harness.request,
            )
        )


async def test_invitation_is_single_use_and_bound_to_the_invited_address() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.org")
    view = await approved_organization(harness, owner_id)
    invited_id = await create_account(harness, "invited@example.org")
    wrong_id = await create_account(harness, "wrong@example.org")

    result = await InviteMember(harness.tenancy).execute(
        InviteMemberCommand(
            actor=await actor_for(harness, owner_id),
            organization_id=view.organization.id,
            email="invited@example.org",
            role=OrganizationRole.MEMBER,
            request=harness.request,
        )
    )
    token = result.development_only_token

    # A different account may not redeem someone else's invitation.
    with pytest.raises((AuthorizationError, ValidationError)):
        await RespondToInvitation(harness.tenancy).execute(
            RespondToInvitationCommand(
                actor=await actor_for(harness, wrong_id),
                token=token,
                accept=True,
                request=harness.request,
            )
        )

    membership = await RespondToInvitation(harness.tenancy).execute(
        RespondToInvitationCommand(
            actor=await actor_for(harness, invited_id),
            token=token,
            accept=True,
            request=harness.request,
        )
    )
    assert membership.state is MembershipState.ACTIVE
    assert membership.role is OrganizationRole.MEMBER

    # The same token cannot be replayed.
    with pytest.raises((AuthorizationError, ValidationError)):
        await RespondToInvitation(harness.tenancy).execute(
            RespondToInvitationCommand(
                actor=await actor_for(harness, invited_id),
                token=token,
                accept=True,
                request=harness.request,
            )
        )


async def test_a_plain_member_cannot_invite_or_change_roles() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.org")
    view = await approved_organization(harness, owner_id)
    member_id = await create_account(harness, "member@example.org")
    invitation = await InviteMember(harness.tenancy).execute(
        InviteMemberCommand(
            actor=await actor_for(harness, owner_id),
            organization_id=view.organization.id,
            email="member@example.org",
            role=OrganizationRole.MEMBER,
            request=harness.request,
        )
    )
    await RespondToInvitation(harness.tenancy).execute(
        RespondToInvitationCommand(
            actor=await actor_for(harness, member_id),
            token=invitation.development_only_token,
            accept=True,
            request=harness.request,
        )
    )

    member_actor = await actor_for(harness, member_id)
    with pytest.raises(AuthorizationError):
        await InviteMember(harness.tenancy).execute(
            InviteMemberCommand(
                actor=member_actor,
                organization_id=view.organization.id,
                email="another@example.org",
                role=OrganizationRole.MEMBER,
                request=harness.request,
            )
        )
    with pytest.raises(AuthorizationError):
        await ChangeMemberRole(harness.tenancy).execute(
            ChangeMemberRoleCommand(
                actor=member_actor,
                organization_id=view.organization.id,
                user_id=member_id,
                role=OrganizationRole.OWNER,
                request=harness.request,
            )
        )
    # A member can still see the member list of their own organization.
    members = await ListMembers(harness.tenancy).execute(
        ListMembersQuery(
            actor=member_actor,
            organization_id=view.organization.id,
            page=PAGE,
            request=harness.request,
        )
    )
    assert {row.user_id for row in members.items} == {owner_id, member_id}


async def test_the_last_owner_cannot_be_removed_or_demoted() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.org")
    view = await approved_organization(harness, owner_id)
    owner_actor = await actor_for(harness, owner_id)

    with pytest.raises(ConflictError):
        await ChangeMemberRole(harness.tenancy).execute(
            ChangeMemberRoleCommand(
                actor=owner_actor,
                organization_id=view.organization.id,
                user_id=owner_id,
                role=OrganizationRole.MEMBER,
                request=harness.request,
            )
        )
    with pytest.raises(ConflictError):
        await EndMembership(harness.tenancy).execute(
            EndMembershipCommand(
                actor=owner_actor,
                organization_id=view.organization.id,
                user_id=owner_id,
                request=harness.request,
                voluntary=True,
            )
        )


async def test_leaving_an_organization_removes_reach_but_deletes_nothing() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.org")
    view = await approved_organization(harness, owner_id)
    member_id = await create_account(harness, "leaver@example.org")
    invitation = await InviteMember(harness.tenancy).execute(
        InviteMemberCommand(
            actor=await actor_for(harness, owner_id),
            organization_id=view.organization.id,
            email="leaver@example.org",
            role=OrganizationRole.MEMBER,
            request=harness.request,
        )
    )
    await RespondToInvitation(harness.tenancy).execute(
        RespondToInvitationCommand(
            actor=await actor_for(harness, member_id),
            token=invitation.development_only_token,
            accept=True,
            request=harness.request,
        )
    )

    await EndMembership(harness.tenancy).execute(
        EndMembershipCommand(
            actor=await actor_for(harness, member_id),
            organization_id=view.organization.id,
            user_id=member_id,
            request=harness.request,
            voluntary=True,
        )
    )

    actor = await actor_for(harness, member_id)
    assert view.organization.id not in actor.usable_organization_ids()
    # The organization, its workspace and the membership record all survive.
    assert await harness.repositories.organizations.get(view.organization.id) is not None
    assert await harness.repositories.workspaces.get(view.workspace_id) is not None
    membership = await harness.repositories.organization_memberships.get(
        view.organization.id, member_id
    )
    assert membership is not None
    assert membership.state is not MembershipState.ACTIVE
