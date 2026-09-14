"""SQLAlchemy repository implementations.

Deliberately written against SQLAlchemy *Core* statements over the declarative
tables rather than through the ORM identity map. Two reasons:

* repositories return framework-free domain entities, so an ORM identity map
  would add a second, silently divergent copy of the same state;
* optimistic concurrency is expressed as ``UPDATE ... WHERE version = :expected``,
  which is explicit, reviewable and impossible to bypass by accident.
"""

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
from app.infrastructure.persistence.repositories.queries import (
    SqlFilterDefinitionRepository,
    SqlFilterPresetRepository,
    SqlQueryExecutionRepository,
    SqlRankingDefinitionRepository,
    SqlRankingPresetRepository,
    SqlSavedViewRepository,
)
from app.infrastructure.persistence.repositories.tenancy import (
    SqlOrganizationInvitationRepository,
    SqlOrganizationMembershipRepository,
    SqlOrganizationRepository,
    SqlWorkspaceRepository,
)

__all__ = [
    "SqlAuditRepository",
    "SqlFilterDefinitionRepository",
    "SqlFilterPresetRepository",
    "SqlQueryExecutionRepository",
    "SqlRankingDefinitionRepository",
    "SqlRankingPresetRepository",
    "SqlSavedViewRepository",
    "SqlCredentialTokenRepository",
    "SqlCredentialsRepository",
    "SqlNotificationRepository",
    "SqlOrganizationInvitationRepository",
    "SqlOrganizationMembershipRepository",
    "SqlOrganizationRepository",
    "SqlOutboxRepository",
    "SqlPlatformRoleRepository",
    "SqlProjectMembershipRepository",
    "SqlProjectRepository",
    "SqlSecurityEventRepository",
    "SqlSessionRepository",
    "SqlUserRepository",
    "SqlWorkspaceRepository",
]
