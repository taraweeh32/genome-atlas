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
from app.infrastructure.persistence.repositories.annotation import (
    SqlAnnotationProfileRepository,
    SqlAnnotationResourceRepository,
    SqlAnnotationResultRepository,
    SqlAnnotationRunRepository,
)
from app.infrastructure.persistence.repositories.analysis import (
    SqlAnalysisConfigurationRepository,
    SqlAnalysisExecutionRepository,
    SqlAnalysisRepository,
)
from app.infrastructure.persistence.repositories.datasets import (
    SqlDatasetRepository,
    SqlDatasetVersionRepository,
    SqlFileArtifactRepository,
    SqlUploadSessionRepository,
)
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
from app.infrastructure.persistence.repositories.ingest import (
    SqlColumnMappingRepository,
    SqlImportSessionRepository,
    SqlValidationIssueRepository,
    SqlValidationRunRepository,
)
from app.infrastructure.persistence.repositories.jobs import SqlJobRepository
from app.infrastructure.persistence.repositories.queries import (
    SqlFilterDefinitionRepository,
    SqlFilterPresetRepository,
    SqlQueryExecutionRepository,
    SqlRankingDefinitionRepository,
    SqlRankingPresetRepository,
    SqlSavedViewRepository,
)
from app.infrastructure.persistence.repositories.projects import (
    SqlProjectMembershipRepository,
    SqlProjectRepository,
)
from app.infrastructure.persistence.repositories.results import (
    SqlResultArtifactRepository,
    SqlResultIngestionRepository,
    SqlResultSetRepository,
)
from app.infrastructure.persistence.repositories.scheduling import (
    SqlComputeNodeRepository,
    SqlScheduleRepository,
)
from app.infrastructure.persistence.repositories.scientific import (
    SqlScientificExecutionRepository,
)
from app.infrastructure.persistence.repositories.tenancy import (
    SqlOrganizationInvitationRepository,
    SqlOrganizationMembershipRepository,
    SqlOrganizationRepository,
    SqlWorkspaceRepository,
)
from app.infrastructure.persistence.repositories.variants import (
    SqlDatasetVersionVariantRepository,
    SqlGeneTranscriptRepository,
    SqlSampleRepository,
    SqlVariantContextRepository,
    SqlVariantIdentifierRepository,
    SqlVariantRepository,
    SqlVariantRepresentationRepository,
    SqlVariantSourceRepresentationRepository,
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
    datasets: SqlDatasetRepository
    dataset_versions: SqlDatasetVersionRepository
    file_artifacts: SqlFileArtifactRepository
    upload_sessions: SqlUploadSessionRepository
    import_sessions: SqlImportSessionRepository
    column_mappings: SqlColumnMappingRepository
    validation_runs: SqlValidationRunRepository
    validation_issues: SqlValidationIssueRepository
    analyses: SqlAnalysisRepository
    analysis_configurations: SqlAnalysisConfigurationRepository
    analysis_executions: SqlAnalysisExecutionRepository
    schedules: SqlScheduleRepository
    compute_nodes: SqlComputeNodeRepository
    scientific_executions: SqlScientificExecutionRepository
    variants: SqlVariantRepository
    variant_representations: SqlVariantRepresentationRepository
    variant_source_representations: SqlVariantSourceRepresentationRepository
    variant_identifiers: SqlVariantIdentifierRepository
    variant_contexts: SqlVariantContextRepository
    dataset_version_variants: SqlDatasetVersionVariantRepository
    samples: SqlSampleRepository
    genes_transcripts: SqlGeneTranscriptRepository
    result_sets: SqlResultSetRepository
    result_artifacts: SqlResultArtifactRepository
    result_ingestions: SqlResultIngestionRepository
    filter_definitions: SqlFilterDefinitionRepository
    filter_presets: SqlFilterPresetRepository
    ranking_definitions: SqlRankingDefinitionRepository
    ranking_presets: SqlRankingPresetRepository
    query_executions: SqlQueryExecutionRepository
    saved_views: SqlSavedViewRepository
    annotation_resources: SqlAnnotationResourceRepository
    annotation_profiles: SqlAnnotationProfileRepository
    annotation_runs: SqlAnnotationRunRepository
    annotation_results: SqlAnnotationResultRepository
    jobs: SqlJobRepository
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
            datasets=SqlDatasetRepository(session),
            dataset_versions=SqlDatasetVersionRepository(session),
            file_artifacts=SqlFileArtifactRepository(session),
            upload_sessions=SqlUploadSessionRepository(session),
            import_sessions=SqlImportSessionRepository(session),
            column_mappings=SqlColumnMappingRepository(session),
            validation_runs=SqlValidationRunRepository(session),
            validation_issues=SqlValidationIssueRepository(session),
            analyses=SqlAnalysisRepository(session),
            analysis_configurations=SqlAnalysisConfigurationRepository(session),
            analysis_executions=SqlAnalysisExecutionRepository(session),
            schedules=SqlScheduleRepository(session),
            compute_nodes=SqlComputeNodeRepository(session),
            scientific_executions=SqlScientificExecutionRepository(session),
            variants=SqlVariantRepository(session),
            variant_representations=SqlVariantRepresentationRepository(session),
            variant_source_representations=SqlVariantSourceRepresentationRepository(session),
            variant_identifiers=SqlVariantIdentifierRepository(session),
            variant_contexts=SqlVariantContextRepository(session),
            dataset_version_variants=SqlDatasetVersionVariantRepository(session),
            samples=SqlSampleRepository(session),
            genes_transcripts=SqlGeneTranscriptRepository(session),
            result_sets=SqlResultSetRepository(session),
            result_artifacts=SqlResultArtifactRepository(session),
            result_ingestions=SqlResultIngestionRepository(session),
            filter_definitions=SqlFilterDefinitionRepository(session),
            filter_presets=SqlFilterPresetRepository(session),
            ranking_definitions=SqlRankingDefinitionRepository(session),
            ranking_presets=SqlRankingPresetRepository(session),
            query_executions=SqlQueryExecutionRepository(session),
            saved_views=SqlSavedViewRepository(session),
            annotation_resources=SqlAnnotationResourceRepository(session),
            annotation_profiles=SqlAnnotationProfileRepository(session),
            annotation_runs=SqlAnnotationRunRepository(session),
            annotation_results=SqlAnnotationResultRepository(session),
            jobs=SqlJobRepository(session),
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
