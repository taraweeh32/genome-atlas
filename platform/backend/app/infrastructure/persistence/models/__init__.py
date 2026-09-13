"""Persistence models.

Importing this package registers every table on ``Base.metadata``, which is what
Alembic's autogenerate support and the schema tests rely on. Import order is
irrelevant because relationships are declared by string target.
"""

from __future__ import annotations

from app.infrastructure.persistence.base import Base
from app.infrastructure.persistence.models.analysis import (
    Analysis,
    AnalysisConfiguration,
    AnalysisConfigurationInput,
    AnalysisExecution,
    AnalysisExecutionInput,
)
from app.infrastructure.persistence.models.annotation import (
    ClinicalAssertion,
    ExternalAssertionSource,
    Population,
    PopulationFrequencyObservation,
    VariantAnnotation,
)
from app.infrastructure.persistence.models.dataset import (
    Dataset,
    DatasetVersion,
    FileArtifact,
)
from app.infrastructure.persistence.models.governance import (
    AuditEvent,
    ConfigurationSetting,
    ConfigurationSettingVersion,
    DomainEventOutbox,
    ProvenanceEntry,
    ProvenanceManifest,
    ResourceUsageRecord,
    RetentionAction,
    RetentionPolicy,
    SecurityEvent,
)
from app.infrastructure.persistence.models.identity import (
    PlatformRoleAssignment,
    ServiceAccount,
    User,
    UserAuthenticationMetadata,
    UserPreference,
)
from app.infrastructure.persistence.models.ingest import (
    ImportSession,
    ValidationIssue,
    ValidationRule,
    ValidationRun,
)
from app.infrastructure.persistence.models.interpretation import (
    CriterionEvaluation,
    CriterionEvaluationEvidence,
    EvidenceItem,
    Interpretation,
    InterpretationVersion,
    ReviewAssignment,
    ReviewDecision,
)
from app.infrastructure.persistence.models.jobs import (
    Job,
    JobAttempt,
    ScheduledJob,
    ScheduleTrigger,
    WorkerNode,
)
from app.infrastructure.persistence.models.notification import (
    Notification,
    NotificationDelivery,
    NotificationPreference,
)
from app.infrastructure.persistence.models.organization import (
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
    OrganizationSetting,
)
from app.infrastructure.persistence.models.project import (
    DiscussionComment,
    Project,
    ProjectInvitation,
    ProjectMembership,
    ResourceAssignment,
)
from app.infrastructure.persistence.models.reporting import (
    ExportRequest,
    Report,
    ReportTemplate,
    ReportVersion,
    ReportVersionInterpretation,
)
from app.infrastructure.persistence.models.results import (
    FilterDefinition,
    FilterDefinitionVersion,
    RankingConfiguration,
    RankingConfigurationVersion,
    ResultSet,
    SavedView,
)
from app.infrastructure.persistence.models.scientific import (
    ScientificArtifact,
    ScientificExecution,
    ScientificResource,
    ScientificResourceCompatibility,
)
from app.infrastructure.persistence.models.session import (
    UserCredentialToken,
    UserSession,
)
from app.infrastructure.persistence.models.uploads import (
    DatasetColumnMapping,
    UploadSession,
)
from app.infrastructure.persistence.models.variant import (
    Gene,
    Sample,
    Transcript,
    Variant,
    VariantExternalIdentifier,
    VariantObservation,
    VariantSourceRepresentation,
    VariantTranscriptConsequence,
)
from app.infrastructure.persistence.models.workspace import Workspace

__all__ = [
    "Analysis",
    "AnalysisConfiguration",
    "AnalysisConfigurationInput",
    "AnalysisExecution",
    "AnalysisExecutionInput",
    "AuditEvent",
    "Base",
    "ClinicalAssertion",
    "ConfigurationSetting",
    "ConfigurationSettingVersion",
    "CriterionEvaluation",
    "CriterionEvaluationEvidence",
    "Dataset",
    "DatasetColumnMapping",
    "DatasetVersion",
    "DiscussionComment",
    "DomainEventOutbox",
    "EvidenceItem",
    "ExportRequest",
    "ExternalAssertionSource",
    "FileArtifact",
    "FilterDefinition",
    "FilterDefinitionVersion",
    "Gene",
    "ImportSession",
    "Interpretation",
    "InterpretationVersion",
    "Job",
    "JobAttempt",
    "Notification",
    "NotificationDelivery",
    "NotificationPreference",
    "Organization",
    "OrganizationInvitation",
    "OrganizationMembership",
    "OrganizationSetting",
    "PlatformRoleAssignment",
    "Population",
    "PopulationFrequencyObservation",
    "Project",
    "ProjectInvitation",
    "ProjectMembership",
    "ProvenanceEntry",
    "ProvenanceManifest",
    "RankingConfiguration",
    "RankingConfigurationVersion",
    "Report",
    "ReportTemplate",
    "ReportVersion",
    "ReportVersionInterpretation",
    "ResourceAssignment",
    "ResourceUsageRecord",
    "ResultSet",
    "RetentionAction",
    "RetentionPolicy",
    "ReviewAssignment",
    "ReviewDecision",
    "Sample",
    "SavedView",
    "ScheduleTrigger",
    "ScheduledJob",
    "ScientificArtifact",
    "ScientificExecution",
    "ScientificResource",
    "ScientificResourceCompatibility",
    "SecurityEvent",
    "ServiceAccount",
    "Transcript",
    "UploadSession",
    "User",
    "UserAuthenticationMetadata",
    "UserCredentialToken",
    "UserPreference",
    "UserSession",
    "ValidationIssue",
    "ValidationRule",
    "ValidationRun",
    "Variant",
    "VariantAnnotation",
    "VariantExternalIdentifier",
    "VariantObservation",
    "VariantSourceRepresentation",
    "VariantTranscriptConsequence",
    "WorkerNode",
    "Workspace",
]
