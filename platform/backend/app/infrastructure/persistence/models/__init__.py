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
from app.infrastructure.persistence.models.annotation_registry import (
    AnnotationProfile,
    AnnotationProfileVersion,
    AnnotationResourceProfileField,
    AnnotationResultVersion,
    AnnotationRun,
    AnnotationValidationFindingRow,
)
from app.infrastructure.persistence.models.dataset import (
    Dataset,
    DatasetVersion,
    FileArtifact,
)
from app.infrastructure.persistence.models.evidence_registry import (
    EvidenceIngestionBatchRow,
    EvidenceValidationFindingRow,
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
from app.infrastructure.persistence.models.interpretation_rulesets import (
    AutomatedClassificationRow,
    ClassificationEvaluationRow,
    InterpretationCombinationRuleRow,
    InterpretationCriterionRow,
    InterpretationRulesetRow,
    RulesetBenchmarkCaseRow,
    RulesetBenchmarkRunRow,
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
from app.infrastructure.persistence.models.queries import (
    FilterExecution,
    FilterPreset,
    FilterPresetVersion,
    RankingExecution,
    RankingPreset,
    RankingPresetVersion,
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
from app.infrastructure.persistence.models.review import (
    InterpretationVersionCriterion,
    InterpretationVersionEvidence,
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
from app.infrastructure.persistence.models.variant_results import (
    DatasetVersionVariant,
    ResultArtifact,
    ResultIngestionRequest,
    VariantRepresentation,
)
from app.infrastructure.persistence.models.workspace import Workspace

__all__ = [
    "Analysis",
    "AnalysisConfiguration",
    "AnalysisConfigurationInput",
    "AnalysisExecution",
    "AnalysisExecutionInput",
    "AnnotationProfile",
    "AnnotationProfileVersion",
    "AnnotationResourceProfileField",
    "AnnotationResultVersion",
    "AnnotationRun",
    "AnnotationValidationFindingRow",
    "AuditEvent",
    "AutomatedClassificationRow",
    "Base",
    "ClassificationEvaluationRow",
    "ClinicalAssertion",
    "ConfigurationSetting",
    "ConfigurationSettingVersion",
    "CriterionEvaluation",
    "CriterionEvaluationEvidence",
    "Dataset",
    "DatasetColumnMapping",
    "DatasetVersion",
    "DatasetVersionVariant",
    "DiscussionComment",
    "DomainEventOutbox",
    "EvidenceIngestionBatchRow",
    "EvidenceItem",
    "EvidenceValidationFindingRow",
    "ExportRequest",
    "ExternalAssertionSource",
    "FileArtifact",
    "FilterDefinition",
    "FilterDefinitionVersion",
    "FilterExecution",
    "FilterPreset",
    "FilterPresetVersion",
    "Gene",
    "ImportSession",
    "Interpretation",
    "InterpretationCombinationRuleRow",
    "InterpretationCriterionRow",
    "InterpretationRulesetRow",
    "InterpretationVersion",
    "InterpretationVersionCriterion",
    "InterpretationVersionEvidence",
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
    "RankingExecution",
    "RankingPreset",
    "RankingPresetVersion",
    "Report",
    "ReportTemplate",
    "ReportVersion",
    "ReportVersionInterpretation",
    "ResourceAssignment",
    "ResourceUsageRecord",
    "ResultArtifact",
    "ResultIngestionRequest",
    "ResultSet",
    "RetentionAction",
    "RetentionPolicy",
    "ReviewAssignment",
    "ReviewDecision",
    "RulesetBenchmarkCaseRow",
    "RulesetBenchmarkRunRow",
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
    "VariantRepresentation",
    "VariantSourceRepresentation",
    "VariantTranscriptConsequence",
    "WorkerNode",
    "Workspace",
]
