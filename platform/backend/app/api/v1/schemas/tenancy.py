"""Request/response schemas for workspaces, organizations and projects.

Every resource response carries the caller's ``capabilities`` for that resource
so the UI can present only usable controls. The list is derived server-side from
the caller's grants and is advisory only — it is never accepted as input.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.v1.schemas.common import ApiModel


class PageMeta(ApiModel):
    """Page-number pagination, used by administrative and membership listings."""

    number: int
    size: int
    total: int


class WorkspaceResponse(ApiModel):
    id: str
    kind: str
    name: str
    organization_id: str | None
    owner_user_id: str | None
    capabilities: list[str]


class WorkspaceCollection(ApiModel):
    items: list[WorkspaceResponse]


class OrganizationRequestPayload(ApiModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=2, max_length=64)
    description: str | None = Field(default=None, max_length=2000)


class OrganizationUpdatePayload(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)
    expected_version: int = Field(
        ge=1,
        description="The version the caller last read. A mismatch is rejected with "
        "409 so concurrent edits cannot silently overwrite each other.",
    )


class OrganizationResponse(ApiModel):
    id: str
    slug: str
    name: str
    description: str | None
    state: str
    workspace_id: str | None
    role: str | None
    capabilities: list[str]
    requested_at: datetime | None
    approval_decided_at: datetime | None
    approval_decision_reason: str | None
    version: int


class OrganizationCollection(ApiModel):
    items: list[OrganizationResponse]
    page: PageMeta


class OrganizationReviewResponse(ApiModel):
    id: str
    slug: str
    name: str
    description: str | None
    state: str
    requested_by: str | None
    requested_at: datetime | None


class OrganizationReviewCollection(ApiModel):
    items: list[OrganizationReviewResponse]
    page: PageMeta


class OrganizationDecisionPayload(ApiModel):
    approve: bool
    reason: str | None = Field(default=None, max_length=1000)


class OrganizationLifecyclePayload(ApiModel):
    state: str = Field(description="Target state: active, suspended or deactivated.")
    reason: str | None = Field(default=None, max_length=1000)


class InvitationPayload(ApiModel):
    email: str = Field(max_length=320)
    role: str = Field(description="Organization role: admin, member, billing or guest.")


class InvitationResponse(ApiModel):
    id: str
    organization_id: str
    invited_email: str
    role: str
    state: str
    expires_at: datetime
    responded_at: datetime | None
    development_only_token: str | None = Field(
        default=None,
        description="Present only in non-production environments, where no mail "
        "transport is configured.",
    )


class InvitationCollection(ApiModel):
    items: list[InvitationResponse]
    page: PageMeta


class MyInvitationResponse(ApiModel):
    id: str
    organization_id: str
    role: str
    expires_at: datetime


class MyInvitationCollection(ApiModel):
    items: list[MyInvitationResponse]


class InvitationResponsePayload(ApiModel):
    token: str = Field(min_length=8, max_length=512)
    accept: bool


class MembershipResponse(ApiModel):
    id: str
    organization_id: str
    user_id: str
    role: str
    state: str
    joined_at: datetime | None
    left_at: datetime | None


class MembershipCollection(ApiModel):
    items: list[MembershipResponse]
    page: PageMeta


class MemberRolePayload(ApiModel):
    role: str


class ProjectCreatePayload(ApiModel):
    workspace_id: str
    name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)


class ProjectUpdatePayload(ApiModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)


class ProjectLifecyclePayload(ApiModel):
    state: str = Field(description="Target state: active or archived.")
    reason: str | None = Field(default=None, max_length=1000)


class ProjectResponse(ApiModel):
    id: str
    workspace_id: str
    name: str
    description: str | None
    state: str
    created_by: str
    owner_user_id: str | None
    role: str | None
    capabilities: list[str]
    created_at: datetime | None
    version: int


class ProjectCollection(ApiModel):
    items: list[ProjectResponse]
    page: PageMeta


class ProjectMemberPayload(ApiModel):
    user_id: str
    role: str = Field(description="Project role: manager, analyst, reviewer or viewer.")


class ProjectMemberRolePayload(ApiModel):
    role: str


class ProjectMemberResponse(ApiModel):
    id: str
    project_id: str
    user_id: str
    role: str
    state: str
    joined_at: datetime | None


class ProjectMemberCollection(ApiModel):
    items: list[ProjectMemberResponse]
    page: PageMeta


__all__ = [
    "InvitationCollection",
    "InvitationPayload",
    "InvitationResponse",
    "InvitationResponsePayload",
    "MemberRolePayload",
    "MembershipCollection",
    "MembershipResponse",
    "MyInvitationCollection",
    "MyInvitationResponse",
    "OrganizationCollection",
    "OrganizationDecisionPayload",
    "OrganizationLifecyclePayload",
    "OrganizationRequestPayload",
    "OrganizationResponse",
    "OrganizationReviewCollection",
    "OrganizationReviewResponse",
    "OrganizationUpdatePayload",
    "PageMeta",
    "ProjectCollection",
    "ProjectCreatePayload",
    "ProjectLifecyclePayload",
    "ProjectMemberCollection",
    "ProjectMemberPayload",
    "ProjectMemberResponse",
    "ProjectMemberRolePayload",
    "ProjectResponse",
    "ProjectUpdatePayload",
    "WorkspaceCollection",
    "WorkspaceResponse",
]
