"""Transport mapping helpers: pagination, enum parsing and response shaping.

Kept out of the route modules so handlers stay thin, and out of the application
layer so domain code never depends on transport types.
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, TypeVar

from fastapi import Depends, Query

from app.api.v1.schemas.tenancy import (
    InvitationResponse,
    MembershipResponse,
    MyInvitationResponse,
    OrganizationResponse,
    OrganizationReviewResponse,
    PageMeta,
    ProjectMemberResponse,
    ProjectResponse,
    WorkspaceResponse,
)
from app.application.repositories import Page, Paged
from app.domain.errors import ValidationError
from app.domain.organization.entities import (
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
)
from app.domain.project.entities import ProjectMembership

EnumT = TypeVar("EnumT", bound=Enum)

#: Hard ceiling regardless of what a client asks for, so a listing endpoint can
#: never be turned into a bulk export.
MAX_PAGE_SIZE = 100


def page_params(
    number: Annotated[int, Query(ge=1, le=10_000)] = 1,
    size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 25,
) -> Page:
    return Page(number=number, size=size)


PageDep = Annotated[Page, Depends(page_params)]


def page_meta(paged: Paged) -> PageMeta:
    return PageMeta(number=paged.page.number, size=paged.page.size, total=paged.total)


def parse_enum(enum_type: type[EnumT], raw: str, *, field: str) -> EnumT:
    """Reject an unknown value as a 400 with the allowed set, never a 500."""
    try:
        return enum_type(raw)
    except ValueError as exc:
        raise ValidationError(
            f"unsupported {field}",
            details={"field": field, "allowed": sorted(item.value for item in enum_type)},
        ) from exc


def workspace_response(view) -> WorkspaceResponse:  # noqa: ANN001 - WorkspaceView
    workspace = view.workspace
    return WorkspaceResponse(
        id=workspace.id,
        kind=workspace.kind.value,
        name=workspace.name,
        organization_id=workspace.organization_id,
        owner_user_id=workspace.owner_user_id,
        capabilities=list(view.capabilities),
    )


def organization_response(view) -> OrganizationResponse:  # noqa: ANN001 - OrganizationView
    organization = view.organization
    return OrganizationResponse(
        id=organization.id,
        slug=organization.slug,
        name=organization.name,
        description=organization.description,
        state=organization.state.value,
        workspace_id=view.workspace_id,
        role=view.role.value if view.role else None,
        capabilities=list(view.capabilities),
        requested_at=organization.requested_at,
        approval_decided_at=organization.approval_decided_at,
        approval_decision_reason=organization.approval_decision_reason,
        version=organization.version,
    )


def organization_review_response(organization: Organization) -> OrganizationReviewResponse:
    return OrganizationReviewResponse(
        id=organization.id,
        slug=organization.slug,
        name=organization.name,
        description=organization.description,
        state=organization.state.value,
        requested_by=organization.requested_by,
        requested_at=organization.requested_at,
    )


def invitation_response(
    invitation: OrganizationInvitation, *, token: str | None = None
) -> InvitationResponse:
    return InvitationResponse(
        id=invitation.id,
        organization_id=invitation.organization_id,
        invited_email=invitation.invited_email_normalized,
        role=invitation.role.value,
        state=invitation.state.value,
        expires_at=invitation.expires_at,
        responded_at=invitation.responded_at,
        development_only_token=token,
    )


def my_invitation_response(invitation: OrganizationInvitation) -> MyInvitationResponse:
    """Deliberately narrow: the recipient's own listing exposes no inviter identity."""
    return MyInvitationResponse(
        id=invitation.id,
        organization_id=invitation.organization_id,
        role=invitation.role.value,
        expires_at=invitation.expires_at,
    )


def membership_response(membership: OrganizationMembership) -> MembershipResponse:
    return MembershipResponse(
        id=membership.id,
        organization_id=membership.organization_id,
        user_id=membership.user_id,
        role=membership.role.value,
        state=membership.state.value,
        joined_at=membership.joined_at,
        left_at=membership.left_at,
    )


def project_response(view) -> ProjectResponse:  # noqa: ANN001 - ProjectView
    project = view.project
    return ProjectResponse(
        id=project.id,
        workspace_id=project.workspace_id,
        name=project.name,
        description=project.description,
        state=project.state.value,
        created_by=project.created_by,
        owner_user_id=project.owner_user_id,
        role=view.role.value if view.role else None,
        capabilities=list(view.capabilities),
        created_at=project.created_at,
        version=project.version,
    )


def project_member_response(membership: ProjectMembership) -> ProjectMemberResponse:
    return ProjectMemberResponse(
        id=membership.id,
        project_id=membership.project_id,
        user_id=membership.user_id,
        role=membership.role.value,
        state=membership.state.value,
        joined_at=membership.joined_at,
    )


__all__ = [
    "MAX_PAGE_SIZE",
    "PageDep",
    "invitation_response",
    "membership_response",
    "my_invitation_response",
    "organization_response",
    "organization_review_response",
    "page_meta",
    "page_params",
    "parse_enum",
    "project_member_response",
    "project_response",
    "workspace_response",
]
