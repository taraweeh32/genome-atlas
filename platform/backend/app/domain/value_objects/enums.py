"""Domain state vocabularies.

Every persisted state field is constrained to one of these vocabularies. They
live in the domain layer because they are domain facts; the persistence layer
renders them as ``VARCHAR + CHECK`` constraints (see
``infrastructure/persistence/base.py``) so that an invalid state value cannot
enter the database, while remaining trivially extensible by migration.

Package 2 defines the vocabularies and persists them. The state *machines* that
decide which transitions are legal are owned by the application layer in later
packages.
"""

from __future__ import annotations

import enum


class StrEnum(str, enum.Enum):
    """String-valued enumeration; the value is what is persisted."""

    def __str__(self) -> str:  # pragma: no cover - trivial
        return str(self.value)


# --------------------------------------------------------------------------- #
# Lifecycle / retention                                                       #
# --------------------------------------------------------------------------- #


class DeletionState(StrEnum):
    """Retention lifecycle, distinct from any operational/review state.

    Soft deletion never implies physical object deletion: an object-storage
    artifact is only removed once a resource reaches ``permanently_deleted``.
    """

    ACTIVE = "active"
    SOFT_DELETED = "soft_deleted"
    RETENTION = "retention"
    PURGE_PENDING = "purge_pending"
    PERMANENTLY_DELETED = "permanently_deleted"


class AccountState(StrEnum):
    PENDING_VERIFICATION = "pending_verification"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"
    LOCKED = "locked"


class EmailVerificationState(StrEnum):
    UNVERIFIED = "unverified"
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"


class OrganizationState(StrEnum):
    REQUESTED = "requested"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"


class MembershipState(StrEnum):
    INVITED = "invited"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    LEFT = "left"
    REMOVED = "removed"


class InvitationState(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    REVOKED = "revoked"
    EXPIRED = "expired"


class WorkspaceKind(StrEnum):
    PERSONAL = "personal"
    ORGANIZATION = "organization"


class OrganizationRole(StrEnum):
    """Organization-scoped role. Never implies project access by itself."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    BILLING = "billing"
    GUEST = "guest"


class ProjectRole(StrEnum):
    """Project-scoped role, granted independently of organization membership."""

    OWNER = "owner"
    MANAGER = "manager"
    ANALYST = "analyst"
    REVIEWER = "reviewer"
    VIEWER = "viewer"


class PlatformRole(StrEnum):
    PLATFORM_ADMINISTRATOR = "platform_administrator"
    PLATFORM_OPERATOR = "platform_operator"
    USER = "user"


class ProjectState(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"
    SUSPENDED = "suspended"
    CLOSED = "closed"


# --------------------------------------------------------------------------- #
# Datasets / files / ingest                                                   #
# --------------------------------------------------------------------------- #


class DatasetKind(StrEnum):
    VARIANT_CALLS = "variant_calls"
    ALIGNMENT = "alignment"
    SAMPLE_MANIFEST = "sample_manifest"
    PHENOTYPE = "phenotype"
    ANNOTATION_INPUT = "annotation_input"
    DERIVED_RESULT = "derived_result"
    OTHER = "other"


class DatasetState(StrEnum):
    DRAFT = "draft"
    VALIDATING = "validating"
    READY = "ready"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class DatasetVersionState(StrEnum):
    """A version is an immutable scientific input once accepted."""

    CREATED = "created"
    UPLOADING = "uploading"
    VALIDATING = "validating"
    VALIDATED = "validated"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class FileUploadState(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    UPLOADED = "uploaded"
    FAILED = "failed"
    ABORTED = "aborted"


class FileValidationState(StrEnum):
    NOT_VALIDATED = "not_validated"
    VALIDATING = "validating"
    VALID = "valid"
    INVALID = "invalid"
    QUARANTINED = "quarantined"


class ChecksumAlgorithm(StrEnum):
    SHA256 = "sha256"
    SHA512 = "sha512"
    MD5 = "md5"
    CRC32C = "crc32c"


class ImportSessionState(StrEnum):
    OPEN = "open"
    SUBMITTED = "submitted"
    VALIDATING = "validating"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ABANDONED = "abandoned"


class ValidationRunState(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    PASSED_WITH_WARNINGS = "passed_with_warnings"
    FAILED = "failed"
    ERRORED = "errored"


class ValidationSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKING = "blocking"


class ValueSemantics(StrEnum):
    """Explicit semantics so ``missing``/``unknown``/``na``/``zero``/``false``
    are never conflated by the persistence layer."""

    PRESENT = "present"
    MISSING = "missing"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"
    ZERO = "zero"
    FALSE = "false"


# --------------------------------------------------------------------------- #
# Analysis / jobs / scientific execution                                      #
# --------------------------------------------------------------------------- #


class AnalysisState(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    ACTIVE = "active"
    ARCHIVED = "archived"


class AnalysisKind(StrEnum):
    VARIANT_PRIORITIZATION = "variant_prioritization"
    ANNOTATION = "annotation"
    FILTERING = "filtering"
    RANKING = "ranking"
    INTERPRETATION = "interpretation"
    QUALITY_CONTROL = "quality_control"
    CUSTOM = "custom"


class ExecutionState(StrEnum):
    REQUESTED = "requested"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class JobState(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    DEAD_LETTER = "dead_letter"


class JobKind(StrEnum):
    ANALYSIS_EXECUTION = "analysis_execution"
    DATASET_IMPORT = "dataset_import"
    DATASET_VALIDATION = "dataset_validation"
    SCIENTIFIC_EXECUTION = "scientific_execution"
    EXPORT = "export"
    REPORT_GENERATION = "report_generation"
    NOTIFICATION_DELIVERY = "notification_delivery"
    RETENTION = "retention"
    MAINTENANCE = "maintenance"


class ScheduleState(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class ScientificExecutionState(StrEnum):
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ScientificResourceKind(StrEnum):
    REFERENCE_GENOME = "reference_genome"
    ANNOTATION_RESOURCE = "annotation_resource"
    POPULATION_RESOURCE = "population_resource"
    CLINICAL_DATABASE = "clinical_database"
    EVIDENCE_RESOURCE = "evidence_resource"
    RULESET = "ruleset"
    ENVIRONMENT = "environment"
    ENGINE = "engine"
    PIPELINE = "pipeline"
    EXECUTION_PROFILE = "execution_profile"


class ScientificResourceState(StrEnum):
    REGISTERED = "registered"
    VALIDATING = "validating"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"
    INVALIDATED = "invalidated"


# --------------------------------------------------------------------------- #
# Variants / annotation / evidence                                            #
# --------------------------------------------------------------------------- #


class VariantClass(StrEnum):
    SNV = "snv"
    MNV = "mnv"
    INSERTION = "insertion"
    DELETION = "deletion"
    INDEL = "indel"
    SYMBOLIC = "symbolic"
    STRUCTURAL = "structural"
    COMPLEX = "complex"


class NormalizationState(StrEnum):
    NOT_NORMALIZED = "not_normalized"
    NORMALIZED = "normalized"
    NORMALIZATION_FAILED = "normalization_failed"


class Zygosity(StrEnum):
    HOMOZYGOUS_REFERENCE = "homozygous_reference"
    HETEROZYGOUS = "heterozygous"
    HOMOZYGOUS_ALTERNATE = "homozygous_alternate"
    HEMIZYGOUS = "hemizygous"
    UNKNOWN = "unknown"


class DataOrigin(StrEnum):
    """How a piece of information came to exist. Never inferred, always stored."""

    IMPORTED = "imported"
    RETRIEVED = "retrieved"
    GENERATED = "generated"
    MACHINE_GENERATED = "machine_generated"
    HUMAN_ENTERED = "human_entered"
    HUMAN_EVALUATED = "human_evaluated"


class AnnotationValueType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    DATE = "date"
    JSON = "json"


class EvidenceCategory(StrEnum):
    POPULATION = "population"
    COMPUTATIONAL = "computational"
    FUNCTIONAL = "functional"
    SEGREGATION = "segregation"
    DE_NOVO = "de_novo"
    ALLELIC = "allelic"
    PHENOTYPE = "phenotype"
    LITERATURE = "literature"
    CLINICAL_DATABASE = "clinical_database"
    OTHER = "other"


class EvidenceStrength(StrEnum):
    STANDALONE = "standalone"
    VERY_STRONG = "very_strong"
    STRONG = "strong"
    MODERATE = "moderate"
    SUPPORTING = "supporting"
    NOT_APPLICABLE = "not_applicable"


class CriterionFamily(StrEnum):
    PVS = "PVS"
    PS = "PS"
    PM = "PM"
    PP = "PP"
    BA = "BA"
    BS = "BS"
    BP = "BP"


class CriterionOutcome(StrEnum):
    MET = "met"
    NOT_MET = "not_met"
    INDETERMINATE = "indeterminate"
    NOT_EVALUATED = "not_evaluated"


class CriterionStrength(StrEnum):
    """Strength assigned to an applied criterion, independent of its family.

    A reviewer may apply a criterion at a strength other than its default, so the
    strength is stored per evaluation rather than derived from the criterion key.
    """

    STANDALONE = "standalone"
    VERY_STRONG = "very_strong"
    STRONG = "strong"
    MODERATE = "moderate"
    SUPPORTING = "supporting"
    NOT_APPLICABLE = "not_applicable"


class CriterionDirection(StrEnum):
    PATHOGENIC = "pathogenic"
    BENIGN = "benign"
    NEUTRAL = "neutral"


class Classification(StrEnum):
    PATHOGENIC = "pathogenic"
    LIKELY_PATHOGENIC = "likely_pathogenic"
    UNCERTAIN_SIGNIFICANCE = "uncertain_significance"
    LIKELY_BENIGN = "likely_benign"
    BENIGN = "benign"
    #: Explicitly *not* a classification: distinguishes "no value yet" from VUS.
    NOT_CLASSIFIED = "not_classified"


class InterpretationState(StrEnum):
    DRAFT = "draft"
    AUTOMATED = "automated"
    IN_REVIEW = "in_review"
    ADJUDICATION = "adjudication"
    APPROVED = "approved"
    FINALIZED = "finalized"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class ReviewState(StrEnum):
    NOT_STARTED = "not_started"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    WITHDRAWN = "withdrawn"


class ReviewDecision(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    MODIFY = "modify"
    ADD_CRITERION = "add_criterion"
    REMOVE_CRITERION = "remove_criterion"
    OVERRIDE = "override"
    ABSTAIN = "abstain"
    ADJUDICATE = "adjudicate"


# --------------------------------------------------------------------------- #
# Results / reports / exports / notifications                                 #
# --------------------------------------------------------------------------- #


class ResultSetState(StrEnum):
    PENDING = "pending"
    GENERATING = "generating"
    AVAILABLE = "available"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"


class ReportState(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    FINALIZED = "finalized"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"


class ExportState(StrEnum):
    REQUESTED = "requested"
    GENERATING = "generating"
    AVAILABLE = "available"
    FAILED = "failed"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ExportFormat(StrEnum):
    CSV = "csv"
    TSV = "tsv"
    JSON = "json"
    XLSX = "xlsx"
    VCF = "vcf"
    PDF = "pdf"
    PARQUET = "parquet"


class NotificationState(StrEnum):
    UNREAD = "unread"
    READ = "read"
    ARCHIVED = "archived"


class DeliveryChannel(StrEnum):
    IN_APP = "in_app"
    EMAIL = "email"
    WEBHOOK = "webhook"


class DeliveryState(StrEnum):
    PENDING = "pending"
    SENDING = "sending"
    DELIVERED = "delivered"
    FAILED = "failed"
    SUPPRESSED = "suppressed"


class OutboxState(StrEnum):
    PENDING = "pending"
    DISPATCHING = "dispatching"
    DISPATCHED = "dispatched"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


# --------------------------------------------------------------------------- #
# Audit / configuration                                                       #
# --------------------------------------------------------------------------- #


class ActorType(StrEnum):
    USER = "user"
    SERVICE_ACCOUNT = "service_account"
    SYSTEM = "system"
    SCHEDULER = "scheduler"
    WORKER = "worker"


class AuditOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"


class AuditChannel(StrEnum):
    WEB = "web"
    API = "api"
    WORKER = "worker"
    SCHEDULER = "scheduler"
    ADMIN = "admin"
    SYSTEM = "system"


class ConfigurationScope(StrEnum):
    PLATFORM = "platform"
    ORGANIZATION = "organization"
    PROJECT = "project"
    PERSONAL = "personal"


class ConfigurationState(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETIRED = "retired"


# --------------------------------------------------------------------------- #
# Sessions / credential tokens (Package 3)                                    #
# --------------------------------------------------------------------------- #


class SessionState(StrEnum):
    """Server-authoritative session lifecycle.

    A session is never "deleted" on sign-out: it is revoked, so the record
    remains available to security review.
    """

    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    SUPERSEDED = "superseded"


class CredentialTokenKind(StrEnum):
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"


class CredentialTokenState(StrEnum):
    ACTIVE = "active"
    CONSUMED = "consumed"
    EXPIRED = "expired"
    INVALIDATED = "invalidated"
