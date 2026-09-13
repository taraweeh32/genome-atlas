"""Tenancy repositories: workspaces, organizations, memberships, invitations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime
from typing import Any

from sqlalchemy import insert, or_, select

from app.application.repositories import Page, Paged
from app.domain.organization.entities import (
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
)
from app.domain.value_objects.enums import (
    DeletionState,
    InvitationState,
    MembershipState,
    OrganizationRole,
    OrganizationState,
    WorkspaceKind,
)
from app.domain.workspace.entities import Workspace
from app.infrastructure.persistence.models.organization import (
    Organization as OrganizationModel,
)
from app.infrastructure.persistence.models.organization import (
    OrganizationInvitation as InvitationModel,
)
from app.infrastructure.persistence.models.organization import (
    OrganizationMembership as MembershipModel,
)
from app.infrastructure.persistence.models.workspace import Workspace as WorkspaceModel
from app.infrastructure.persistence.repositories.base import SqlRepository

_WORKSPACES = WorkspaceModel.__table__
_ORGANIZATIONS = OrganizationModel.__table__
_MEMBERSHIPS = MembershipModel.__table__
_INVITATIONS = InvitationModel.__table__


def to_workspace(row: Mapping[str, Any]) -> Workspace:
    return Workspace(
        id=row["id"],
        kind=WorkspaceKind(row["kind"]),
        name=row["name"],
        owner_user_id=row["owner_user_id"],
        organization_id=row["organization_id"],
        created_by=row["created_by"],
        deletion_state=DeletionState(row["deletion_state"]),
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def to_organization(row: Mapping[str, Any]) -> Organization:
    return Organization(
        id=row["id"],
        slug=row["slug"],
        name=row["name"],
        state=OrganizationState(row["state"]),
        deletion_state=DeletionState(row["deletion_state"]),
        description=row["description"],
        requested_by=row["requested_by"],
        requested_at=row["requested_at"],
        approval_decided_by=row["approval_decided_by"],
        approval_decided_at=row["approval_decided_at"],
        approval_decision_reason=row["approval_decision_reason"],
        suspended_at=row["suspended_at"],
        deactivated_at=row["deactivated_at"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def to_membership(row: Mapping[str, Any]) -> OrganizationMembership:
    return OrganizationMembership(
        id=row["id"],
        organization_id=row["organization_id"],
        user_id=row["user_id"],
        role=OrganizationRole(row["role"]),
        state=MembershipState(row["state"]),
        invited_by=row["invited_by"],
        joined_at=row["joined_at"],
        left_at=row["left_at"],
        removed_by=row["removed_by"],
        version=row["version"],
    )


def to_invitation(row: Mapping[str, Any]) -> OrganizationInvitation:
    return OrganizationInvitation(
        id=row["id"],
        organization_id=row["organization_id"],
        invited_email_normalized=row["invited_email_normalized"],
        role=OrganizationRole(row["role"]),
        state=InvitationState(row["state"]),
        expires_at=row["expires_at"],
        invited_by=row["invited_by"],
        responded_at=row["responded_at"],
        accepted_user_id=row["accepted_user_id"],
        version=row["version"],
        created_at=row["created_at"],
    )


class SqlWorkspaceRepository(SqlRepository):
    async def add(self, workspace: Workspace) -> Workspace:
        await self._session.execute(
            insert(_WORKSPACES).values(
                id=workspace.id,
                kind=workspace.kind.value,
                name=workspace.name,
                owner_user_id=workspace.owner_user_id,
                organization_id=workspace.organization_id,
                created_by=workspace.created_by,
                deletion_state=workspace.deletion_state.value,
                version=1,
            )
        )
        return workspace

    async def get(self, workspace_id: str) -> Workspace | None:
        row = await self._fetch_one(select(_WORKSPACES).where(_WORKSPACES.c.id == workspace_id))
        return to_workspace(row) if row else None

    async def get_personal_for_user(self, user_id: str) -> Workspace | None:
        row = await self._fetch_one(
            select(_WORKSPACES).where(
                _WORKSPACES.c.owner_user_id == user_id,
                _WORKSPACES.c.kind == WorkspaceKind.PERSONAL.value,
            )
        )
        return to_workspace(row) if row else None

    async def get_for_organization(self, organization_id: str) -> Workspace | None:
        row = await self._fetch_one(
            select(_WORKSPACES).where(_WORKSPACES.c.organization_id == organization_id)
        )
        return to_workspace(row) if row else None

    async def list_for_user(self, user_id: str) -> tuple[Workspace, ...]:
        """The user's personal workspace plus every workspace of an organization
        they are an *active* member of. Nothing else is ever returned."""
        organization_ids = select(_MEMBERSHIPS.c.organization_id).where(
            _MEMBERSHIPS.c.user_id == user_id,
            _MEMBERSHIPS.c.state == MembershipState.ACTIVE.value,
        )
        rows = await self._fetch_all(
            select(_WORKSPACES)
            .where(
                _WORKSPACES.c.deletion_state == DeletionState.ACTIVE.value,
                or_(
                    (_WORKSPACES.c.owner_user_id == user_id)
                    & (_WORKSPACES.c.kind == WorkspaceKind.PERSONAL.value),
                    _WORKSPACES.c.organization_id.in_(organization_ids),
                ),
            )
            .order_by(_WORKSPACES.c.kind.asc(), _WORKSPACES.c.name.asc())
        )
        return tuple(to_workspace(row) for row in rows)


class SqlOrganizationRepository(SqlRepository):
    async def add(self, organization: Organization) -> Organization:
        await self._session.execute(
            insert(_ORGANIZATIONS).values(
                id=organization.id,
                slug=organization.slug,
                name=organization.name,
                description=organization.description,
                state=organization.state.value,
                deletion_state=organization.deletion_state.value,
                requested_by=organization.requested_by,
                requested_at=organization.requested_at,
                version=1,
            )
        )
        return organization

    async def get(self, organization_id: str) -> Organization | None:
        row = await self._fetch_one(
            select(_ORGANIZATIONS).where(_ORGANIZATIONS.c.id == organization_id)
        )
        return to_organization(row) if row else None

    async def get_by_slug(self, slug: str) -> Organization | None:
        row = await self._fetch_one(select(_ORGANIZATIONS).where(_ORGANIZATIONS.c.slug == slug))
        return to_organization(row) if row else None

    async def save(self, organization: Organization) -> Organization:
        version = await self._versioned_update(
            _ORGANIZATIONS,
            entity_id=organization.id,
            expected_version=organization.version,
            values={
                "name": organization.name,
                "description": organization.description,
                "state": organization.state.value,
                "deletion_state": organization.deletion_state.value,
                "approval_decided_by": organization.approval_decided_by,
                "approval_decided_at": organization.approval_decided_at,
                "approval_decision_reason": organization.approval_decision_reason,
                "suspended_at": organization.suspended_at,
                "deactivated_at": organization.deactivated_at,
            },
        )
        return replace(organization, version=version)

    async def list_by_states(
        self, states: tuple[OrganizationState, ...], *, page: Page
    ) -> Paged[Organization]:
        statement = select(_ORGANIZATIONS).order_by(_ORGANIZATIONS.c.created_at.desc())
        if states:
            statement = statement.where(
                _ORGANIZATIONS.c.state.in_([state.value for state in states])
            )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(tuple(to_organization(row) for row in rows), total, page)

    async def list_for_user(self, user_id: str, *, page: Page) -> Paged[Organization]:
        organization_ids = select(_MEMBERSHIPS.c.organization_id).where(
            _MEMBERSHIPS.c.user_id == user_id,
            _MEMBERSHIPS.c.state.in_(
                [MembershipState.ACTIVE.value, MembershipState.INVITED.value]
            ),
        )
        statement = (
            select(_ORGANIZATIONS)
            .where(_ORGANIZATIONS.c.id.in_(organization_ids))
            .order_by(_ORGANIZATIONS.c.name.asc())
        )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(tuple(to_organization(row) for row in rows), total, page)


class SqlOrganizationMembershipRepository(SqlRepository):
    async def add(self, membership: OrganizationMembership) -> OrganizationMembership:
        await self._session.execute(
            insert(_MEMBERSHIPS).values(
                id=membership.id,
                organization_id=membership.organization_id,
                user_id=membership.user_id,
                role=membership.role.value,
                state=membership.state.value,
                invited_by=membership.invited_by,
                joined_at=membership.joined_at,
                version=1,
            )
        )
        return membership

    async def get(self, organization_id: str, user_id: str) -> OrganizationMembership | None:
        row = await self._fetch_one(
            select(_MEMBERSHIPS).where(
                _MEMBERSHIPS.c.organization_id == organization_id,
                _MEMBERSHIPS.c.user_id == user_id,
            )
        )
        return to_membership(row) if row else None

    async def save(self, membership: OrganizationMembership) -> OrganizationMembership:
        version = await self._versioned_update(
            _MEMBERSHIPS,
            entity_id=membership.id,
            expected_version=membership.version,
            values={
                "role": membership.role.value,
                "state": membership.state.value,
                "joined_at": membership.joined_at,
                "left_at": membership.left_at,
                "removed_by": membership.removed_by,
            },
        )
        return replace(membership, version=version)

    async def list_for_user(self, user_id: str) -> tuple[OrganizationMembership, ...]:
        rows = await self._fetch_all(
            select(_MEMBERSHIPS).where(_MEMBERSHIPS.c.user_id == user_id)
        )
        return tuple(to_membership(row) for row in rows)

    async def list_for_organization(
        self,
        organization_id: str,
        *,
        page: Page,
        states: tuple[MembershipState, ...] | None = None,
    ) -> Paged[OrganizationMembership]:
        statement = (
            select(_MEMBERSHIPS)
            .where(_MEMBERSHIPS.c.organization_id == organization_id)
            .order_by(_MEMBERSHIPS.c.created_at.asc())
        )
        if states:
            statement = statement.where(
                _MEMBERSHIPS.c.state.in_([state.value for state in states])
            )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(tuple(to_membership(row) for row in rows), total, page)

    async def count_active_with_role(self, organization_id: str, role: str) -> int:
        return await self._count(
            select(_MEMBERSHIPS).where(
                _MEMBERSHIPS.c.organization_id == organization_id,
                _MEMBERSHIPS.c.role == role,
                _MEMBERSHIPS.c.state == MembershipState.ACTIVE.value,
            )
        )


class SqlOrganizationInvitationRepository(SqlRepository):
    async def add(
        self, invitation: OrganizationInvitation, *, token_hash: str
    ) -> OrganizationInvitation:
        await self._session.execute(
            insert(_INVITATIONS).values(
                id=invitation.id,
                organization_id=invitation.organization_id,
                invited_email_normalized=invitation.invited_email_normalized,
                role=invitation.role.value,
                state=invitation.state.value,
                token_hash=token_hash,
                invited_by=invitation.invited_by,
                expires_at=invitation.expires_at,
                version=1,
            )
        )
        return invitation

    async def get(self, invitation_id: str) -> OrganizationInvitation | None:
        row = await self._fetch_one(
            select(_INVITATIONS).where(_INVITATIONS.c.id == invitation_id)
        )
        return to_invitation(row) if row else None

    async def get_by_token_hash(self, token_hash: str) -> OrganizationInvitation | None:
        row = await self._fetch_one(
            select(_INVITATIONS).where(_INVITATIONS.c.token_hash == token_hash)
        )
        return to_invitation(row) if row else None

    async def get_open_for_email(
        self, organization_id: str, email_normalized: str
    ) -> OrganizationInvitation | None:
        row = await self._fetch_one(
            select(_INVITATIONS).where(
                _INVITATIONS.c.organization_id == organization_id,
                _INVITATIONS.c.invited_email_normalized == email_normalized,
                _INVITATIONS.c.state == InvitationState.PENDING.value,
            )
        )
        return to_invitation(row) if row else None

    async def save(self, invitation: OrganizationInvitation) -> OrganizationInvitation:
        version = await self._versioned_update(
            _INVITATIONS,
            entity_id=invitation.id,
            expected_version=invitation.version,
            values={
                "role": invitation.role.value,
                "state": invitation.state.value,
                "responded_at": invitation.responded_at,
                "accepted_user_id": invitation.accepted_user_id,
            },
        )
        return replace(invitation, version=version)

    async def list_for_organization(
        self,
        organization_id: str,
        *,
        page: Page,
        states: tuple[InvitationState, ...] | None = None,
    ) -> Paged[OrganizationInvitation]:
        statement = (
            select(_INVITATIONS)
            .where(_INVITATIONS.c.organization_id == organization_id)
            .order_by(_INVITATIONS.c.created_at.desc())
        )
        if states:
            statement = statement.where(
                _INVITATIONS.c.state.in_([state.value for state in states])
            )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(tuple(to_invitation(row) for row in rows), total, page)

    async def list_open_for_email(
        self, email_normalized: str
    ) -> tuple[OrganizationInvitation, ...]:
        rows = await self._fetch_all(
            select(_INVITATIONS).where(
                _INVITATIONS.c.invited_email_normalized == email_normalized,
                _INVITATIONS.c.state == InvitationState.PENDING.value,
            )
        )
        return tuple(to_invitation(row) for row in rows)


__all__ = [
    "SqlOrganizationInvitationRepository",
    "SqlOrganizationMembershipRepository",
    "SqlOrganizationRepository",
    "SqlWorkspaceRepository",
    "to_invitation",
    "to_membership",
    "to_organization",
    "to_workspace",
]
