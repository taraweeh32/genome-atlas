"""The unit of work: one transaction, one repository set.

A use case opens exactly one unit of work and performs the whole business
operation inside it — state change, audit record, security event and domain event
alike. That is what makes "no state change without its audit record" a structural
guarantee rather than a convention someone must remember.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.persistence.database import Database
from app.infrastructure.persistence.repositories.governance import (
    SqlAuditRepository,
    SqlNotificationRepository,
    SqlOutboxRepository,
    SqlSecurityEventRepository,
)
from app.infrastructure.persistence.repositories.identity import (
    SqlCredentialsRepository,
    SqlCredentialTokenRepository,
    SqlPlatformRoleRepository,
    SqlSessionRepository,
    SqlUserRepository,
)
from app.infrastructure.persistence.repositories.projects import (
    SqlProjectMembershipRepository,
    SqlProjectRepository,
)
from app.infrastructure.persistence.repositories.tenancy import (
    SqlOrganizationInvitationRepository,
    SqlOrganizationMembershipRepository,
    SqlOrganizationRepository,
    SqlWorkspaceRepository,
)


@dataclass(frozen=True)
class SqlRepositories:
    """Every repository bound to one transaction (see ``TransactionalRepositories``)."""

    users: SqlUserRepository
    credentials: SqlCredentialsRepository
    sessions: SqlSessionRepository
    credential_tokens: SqlCredentialTokenRepository
    workspaces: SqlWorkspaceRepository
    organizations: SqlOrganizationRepository
    organization_memberships: SqlOrganizationMembershipRepository
    organization_invitations: SqlOrganizationInvitationRepository
    projects: SqlProjectRepository
    project_memberships: SqlProjectMembershipRepository
    platform_roles: SqlPlatformRoleRepository
    audit: SqlAuditRepository
    security_events: SqlSecurityEventRepository
    outbox: SqlOutboxRepository
    notifications: SqlNotificationRepository

    @classmethod
    def bind(cls, session: AsyncSession) -> SqlRepositories:
        return cls(
            users=SqlUserRepository(session),
            credentials=SqlCredentialsRepository(session),
            sessions=SqlSessionRepository(session),
            credential_tokens=SqlCredentialTokenRepository(session),
            workspaces=SqlWorkspaceRepository(session),
            organizations=SqlOrganizationRepository(session),
            organization_memberships=SqlOrganizationMembershipRepository(session),
            organization_invitations=SqlOrganizationInvitationRepository(session),
            projects=SqlProjectRepository(session),
            project_memberships=SqlProjectMembershipRepository(session),
            platform_roles=SqlPlatformRoleRepository(session),
            audit=SqlAuditRepository(session),
            security_events=SqlSecurityEventRepository(session),
            outbox=SqlOutboxRepository(session),
            notifications=SqlNotificationRepository(session),
        )


class SqlUnitOfWorkFactory:
    """Opens a database transaction and yields the repositories bound to it."""

    def __init__(self, database: Database) -> None:
        self._database = database

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[SqlRepositories]:
        async with self._database.unit_of_work() as session:
            yield SqlRepositories.bind(session)


__all__ = ["SqlRepositories", "SqlUnitOfWorkFactory"]
