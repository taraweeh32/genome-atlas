"""Project and project-membership repositories."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from sqlalchemy import insert, select

from app.application.repositories import Page, Paged
from app.domain.project.entities import Project, ProjectMembership
from app.domain.value_objects.enums import (
    DeletionState,
    MembershipState,
    ProjectRole,
    ProjectState,
)
from app.infrastructure.persistence.models.project import Project as ProjectModel
from app.infrastructure.persistence.models.project import (
    ProjectMembership as ProjectMembershipModel,
)
from app.infrastructure.persistence.repositories.base import SqlRepository

_PROJECTS = ProjectModel.__table__
_MEMBERSHIPS = ProjectMembershipModel.__table__


def to_project(row: Mapping[str, Any]) -> Project:
    return Project(
        id=row["id"],
        workspace_id=row["workspace_id"],
        name=row["name"],
        state=ProjectState(row["state"]),
        created_by=row["created_by"],
        owner_user_id=row["owner_user_id"],
        description=row["description"],
        deletion_state=DeletionState(row["deletion_state"]),
        archived_at=row["archived_at"],
        archived_by=row["archived_by"],
        reopened_at=row["reopened_at"],
        closed_at=row["closed_at"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def to_project_membership(row: Mapping[str, Any]) -> ProjectMembership:
    return ProjectMembership(
        id=row["id"],
        project_id=row["project_id"],
        user_id=row["user_id"],
        role=ProjectRole(row["role"]),
        state=MembershipState(row["state"]),
        granted_by=row["granted_by"],
        joined_at=row["joined_at"],
        left_at=row["left_at"],
        version=row["version"],
    )


class SqlProjectRepository(SqlRepository):
    async def add(self, project: Project) -> Project:
        await self._session.execute(
            insert(_PROJECTS).values(
                id=project.id,
                workspace_id=project.workspace_id,
                name=project.name,
                description=project.description,
                state=project.state.value,
                created_by=project.created_by,
                owner_user_id=project.owner_user_id,
                deletion_state=project.deletion_state.value,
                version=1,
            )
        )
        return project

    async def get(self, project_id: str) -> Project | None:
        row = await self._fetch_one(select(_PROJECTS).where(_PROJECTS.c.id == project_id))
        return to_project(row) if row else None

    async def save(self, project: Project) -> Project:
        version = await self._versioned_update(
            _PROJECTS,
            entity_id=project.id,
            expected_version=project.version,
            values={
                "name": project.name,
                "description": project.description,
                "state": project.state.value,
                "owner_user_id": project.owner_user_id,
                "deletion_state": project.deletion_state.value,
                "archived_at": project.archived_at,
                "archived_by": project.archived_by,
                "reopened_at": project.reopened_at,
                "closed_at": project.closed_at,
            },
        )
        return replace(project, version=version)

    async def list_for_workspaces(
        self, workspace_ids: tuple[str, ...], *, page: Page
    ) -> Paged[Project]:
        """Scope-explicit listing: an empty scope returns nothing, never everything."""
        if not workspace_ids:
            return Paged((), 0, page)
        statement = (
            select(_PROJECTS)
            .where(
                _PROJECTS.c.workspace_id.in_(workspace_ids),
                _PROJECTS.c.deletion_state == DeletionState.ACTIVE.value,
            )
            .order_by(_PROJECTS.c.created_at.desc())
        )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(tuple(to_project(row) for row in rows), total, page)


class SqlProjectMembershipRepository(SqlRepository):
    async def add(self, membership: ProjectMembership) -> ProjectMembership:
        await self._session.execute(
            insert(_MEMBERSHIPS).values(
                id=membership.id,
                project_id=membership.project_id,
                user_id=membership.user_id,
                role=membership.role.value,
                state=membership.state.value,
                granted_by=membership.granted_by,
                joined_at=membership.joined_at,
                version=1,
            )
        )
        return membership

    async def get(self, project_id: str, user_id: str) -> ProjectMembership | None:
        row = await self._fetch_one(
            select(_MEMBERSHIPS).where(
                _MEMBERSHIPS.c.project_id == project_id,
                _MEMBERSHIPS.c.user_id == user_id,
            )
        )
        return to_project_membership(row) if row else None

    async def save(self, membership: ProjectMembership) -> ProjectMembership:
        version = await self._versioned_update(
            _MEMBERSHIPS,
            entity_id=membership.id,
            expected_version=membership.version,
            values={
                "role": membership.role.value,
                "state": membership.state.value,
                "joined_at": membership.joined_at,
                "left_at": membership.left_at,
            },
        )
        return replace(membership, version=version)

    async def list_for_user(self, user_id: str) -> tuple[ProjectMembership, ...]:
        rows = await self._fetch_all(
            select(_MEMBERSHIPS).where(_MEMBERSHIPS.c.user_id == user_id)
        )
        return tuple(to_project_membership(row) for row in rows)

    async def list_for_project(self, project_id: str, *, page: Page) -> Paged[ProjectMembership]:
        statement = (
            select(_MEMBERSHIPS)
            .where(_MEMBERSHIPS.c.project_id == project_id)
            .order_by(_MEMBERSHIPS.c.created_at.asc())
        )
        total = await self._count(statement)
        rows = await self._fetch_all(statement.limit(page.size).offset(page.offset))
        return Paged(tuple(to_project_membership(row) for row in rows), total, page)

    async def count_active_with_role(self, project_id: str, role: str) -> int:
        return await self._count(
            select(_MEMBERSHIPS).where(
                _MEMBERSHIPS.c.project_id == project_id,
                _MEMBERSHIPS.c.role == role,
                _MEMBERSHIPS.c.state == MembershipState.ACTIVE.value,
            )
        )


__all__ = [
    "SqlProjectMembershipRepository",
    "SqlProjectRepository",
    "to_project",
    "to_project_membership",
]
