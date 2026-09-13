"""Organization, invitation and membership endpoints.

Creating an organization only *requests* one: approval is a platform-administrator
decision (see the administration routes) unless the deployment explicitly enables
auto-approval. Nothing here decides authorization; each handler hands the caller's
resolved actor context to a use case.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.authentication import CallerDep, RequestContextDep
from app.api.dependencies import ContainerDep
from app.api.v1.mapping import (
    PageDep,
    invitation_response,
    membership_response,
    my_invitation_response,
    organization_response,
    page_meta,
    parse_enum,
)
from app.api.v1.schemas.common import ERROR_RESPONSES
from app.api.v1.schemas.tenancy import (
    InvitationCollection,
    InvitationPayload,
    InvitationResponse,
    InvitationResponsePayload,
    MemberRolePayload,
    MembershipCollection,
    MembershipResponse,
    MyInvitationCollection,
    OrganizationCollection,
    OrganizationRequestPayload,
    OrganizationResponse,
    OrganizationUpdatePayload,
)
from app.application.use_cases.tenancy.memberships import (
    ChangeMemberRole,
    ChangeMemberRoleCommand,
    EndMembership,
    EndMembershipCommand,
    InviteMember,
    InviteMemberCommand,
    ListInvitations,
    ListInvitationsQuery,
    ListMembers,
    ListMembersQuery,
    ListMyInvitations,
    ListMyInvitationsQuery,
    RespondToInvitation,
    RespondToInvitationCommand,
    RevokeInvitation,
    RevokeInvitationCommand,
)
from app.application.use_cases.tenancy.organizations import (
    GetOrganization,
    GetOrganizationQuery,
    ListMyOrganizations,
    ListMyOrganizationsQuery,
    RequestOrganization,
    RequestOrganizationCommand,
    UpdateOrganization,
    UpdateOrganizationCommand,
)
from app.domain.value_objects.enums import OrganizationRole

router = APIRouter(prefix="/organizations", tags=["organizations"])
invitations_router = APIRouter(prefix="/invitations", tags=["organizations"])


@router.post(
    "",
    response_model=OrganizationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Request a new organization",
    description="Creates the organization in a requested state. It becomes usable "
    "only once a platform administrator approves it, at which point its workspace "
    "and owner membership are provisioned.",
    responses=ERROR_RESPONSES,
)
async def request_organization(
    payload: OrganizationRequestPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> OrganizationResponse:
    view = await RequestOrganization(container.tenancy_services()).execute(
        RequestOrganizationCommand(
            actor=caller.actor,
            name=payload.name,
            slug=payload.slug,
            description=payload.description,
            request=context,
        )
    )
    return organization_response(view)


@router.get(
    "",
    response_model=OrganizationCollection,
    summary="Organizations the caller belongs to",
    responses=ERROR_RESPONSES,
)
async def list_my_organizations(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
) -> OrganizationCollection:
    result = await ListMyOrganizations(container.tenancy_services()).execute(
        ListMyOrganizationsQuery(actor=caller.actor, page=page, request=context)
    )
    return OrganizationCollection(
        items=[organization_response(view) for view in result.items], page=page_meta(result)
    )


@router.get(
    "/{organization_id}",
    response_model=OrganizationResponse,
    summary="One organization",
    responses=ERROR_RESPONSES,
)
async def get_organization(
    organization_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> OrganizationResponse:
    view = await GetOrganization(container.tenancy_services()).execute(
        GetOrganizationQuery(
            actor=caller.actor, organization_id=organization_id, request=context
        )
    )
    return organization_response(view)


@router.patch(
    "/{organization_id}",
    response_model=OrganizationResponse,
    summary="Update an organization profile",
    description="Optimistically concurrent: send the version you last read. A "
    "concurrent change is reported as 409 rather than silently overwritten.",
    responses=ERROR_RESPONSES,
)
async def update_organization(
    organization_id: str,
    payload: OrganizationUpdatePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> OrganizationResponse:
    view = await UpdateOrganization(container.tenancy_services()).execute(
        UpdateOrganizationCommand(
            actor=caller.actor,
            organization_id=organization_id,
            name=payload.name,
            description=payload.description,
            expected_version=payload.expected_version,
            request=context,
        )
    )
    return organization_response(view)


# ---------------------------------------------------------------------- #
# Invitations                                                            #
# ---------------------------------------------------------------------- #


@router.post(
    "/{organization_id}/invitations",
    response_model=InvitationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Invite someone to an organization",
    description="Only a hash of the invitation token is stored. The owner role "
    "cannot be granted by invitation.",
    responses=ERROR_RESPONSES,
)
async def invite_member(
    organization_id: str,
    payload: InvitationPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> InvitationResponse:
    result = await InviteMember(container.tenancy_services()).execute(
        InviteMemberCommand(
            actor=caller.actor,
            organization_id=organization_id,
            email=payload.email,
            role=parse_enum(OrganizationRole, payload.role, field="role"),
            request=context,
        )
    )
    return invitation_response(result.invitation, token=result.development_only_token)


@router.get(
    "/{organization_id}/invitations",
    response_model=InvitationCollection,
    summary="Invitations issued by an organization",
    responses=ERROR_RESPONSES,
)
async def list_invitations(
    organization_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
) -> InvitationCollection:
    result = await ListInvitations(container.tenancy_services()).execute(
        ListInvitationsQuery(
            actor=caller.actor, organization_id=organization_id, page=page, request=context
        )
    )
    return InvitationCollection(
        items=[invitation_response(item) for item in result.items], page=page_meta(result)
    )


@router.delete(
    "/{organization_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an invitation",
    responses=ERROR_RESPONSES,
)
async def revoke_invitation(
    organization_id: str,
    invitation_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> None:
    await RevokeInvitation(container.tenancy_services()).execute(
        RevokeInvitationCommand(
            actor=caller.actor,
            organization_id=organization_id,
            invitation_id=invitation_id,
            request=context,
        )
    )


@invitations_router.get(
    "/mine",
    response_model=MyInvitationCollection,
    summary="Open invitations addressed to the caller",
    responses=ERROR_RESPONSES,
)
async def list_my_invitations(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> MyInvitationCollection:
    invitations = await ListMyInvitations(container.tenancy_services()).execute(
        ListMyInvitationsQuery(actor=caller.actor, request=context)
    )
    return MyInvitationCollection(
        items=[my_invitation_response(item) for item in invitations]
    )


@invitations_router.post(
    "/respond",
    response_model=MembershipResponse | None,
    summary="Accept or decline an invitation",
    description="The invitation must have been addressed to the signed-in "
    "account's own verified address. Declining returns no membership.",
    responses=ERROR_RESPONSES,
)
async def respond_to_invitation(
    payload: InvitationResponsePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> MembershipResponse | None:
    membership = await RespondToInvitation(container.tenancy_services()).execute(
        RespondToInvitationCommand(
            actor=caller.actor, token=payload.token, accept=payload.accept, request=context
        )
    )
    return membership_response(membership) if membership else None


# ---------------------------------------------------------------------- #
# Memberships                                                            #
# ---------------------------------------------------------------------- #


@router.get(
    "/{organization_id}/members",
    response_model=MembershipCollection,
    summary="Organization members",
    responses=ERROR_RESPONSES,
)
async def list_members(
    organization_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
) -> MembershipCollection:
    result = await ListMembers(container.tenancy_services()).execute(
        ListMembersQuery(
            actor=caller.actor, organization_id=organization_id, page=page, request=context
        )
    )
    return MembershipCollection(
        items=[membership_response(item) for item in result.items], page=page_meta(result)
    )


@router.patch(
    "/{organization_id}/members/{user_id}",
    response_model=MembershipResponse,
    summary="Change a member's organization role",
    description="The last owner cannot be demoted: an organization always retains "
    "an accountable owner.",
    responses=ERROR_RESPONSES,
)
async def change_member_role(
    organization_id: str,
    user_id: str,
    payload: MemberRolePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> MembershipResponse:
    membership = await ChangeMemberRole(container.tenancy_services()).execute(
        ChangeMemberRoleCommand(
            actor=caller.actor,
            organization_id=organization_id,
            user_id=user_id,
            role=parse_enum(OrganizationRole, payload.role, field="role"),
            request=context,
        )
    )
    return membership_response(membership)


@router.delete(
    "/{organization_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member from an organization",
    description="Recorded as a departure. It never deletes or reassigns the "
    "member's resources; ownership transfer is an explicit, separate action.",
    responses=ERROR_RESPONSES,
)
async def remove_member(
    organization_id: str,
    user_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> None:
    await EndMembership(container.tenancy_services()).execute(
        EndMembershipCommand(
            actor=caller.actor,
            organization_id=organization_id,
            user_id=user_id,
            request=context,
            voluntary=caller.actor.actor_id == user_id,
        )
    )


__all__ = ["invitations_router", "router"]
