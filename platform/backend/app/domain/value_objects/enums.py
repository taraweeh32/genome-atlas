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
    #: An explicit null marker in the source, distinct from an absent field.
    NULL = "null"
    #: Present but empty (e.g. ``""``), distinct from absent and from null.
    EMPTY = "empty"
    #: A literal ``NA``/``N/A`` marker, which is not the same as "unknown".
    NA = "na"
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
    """Application-level analysis *type*, never an implementation of science.

    A kind selects which scientific capabilities an analysis may request and how
    the UI groups it. Extending the vocabulary is a migration plus a constraint
    replacement; no application branch may assume every analysis performs the
    same scientific steps.
    """

    VARIANT_PRIORITIZATION = "variant_prioritization"
    ANNOTATION = "annotation"
    FILTERING = "filtering"
    RANKING = "ranking"
    INTERPRETATION = "interpretation"
    QUALITY_CONTROL = "quality_control"
    CUSTOM = "custom"
    #: Package 5 additions: capability-driven types that carry no assumption
    #: about which scientific steps run inside the compute subsystem.
    GENOMIC_ANALYSIS = "genomic_analysis"
    ANNOTATED_DATA_ANALYSIS = "annotated_data_analysis"
    IMPORT_PROCESSING = "import_processing"
    SCIENTIFIC_PIPELINE = "scientific_pipeline"


class ConfigurationValidationState(StrEnum):
    """Validation outcome of one immutable analysis configuration version."""

    UNVALIDATED = "unvalidated"
    VALID = "valid"
    INVALID = "invalid"


class ExecutionState(StrEnum):
    """One concrete invocation of an analysis configuration version.

    ``cancel_requested`` is deliberately distinct from ``cancelled``: a request
    to stop is not evidence that work stopped.
    """

    DRAFT = "draft"
    VALIDATING = "validating"
    VALIDATED = "validated"
    SUBMITTED = "submitted"
    REQUESTED = "requested"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class JobState(StrEnum):
    PENDING = "pending"
    QUEUED = "queued"
    CLAIMED = "claimed"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    #: A cancellation was requested; the worker has not yet acknowledged it.
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    #: Waiting out a retry backoff. Distinct from ``queued`` so a backoff is
    #: visible instead of looking like ordinary queue latency.
    RETRY_WAITING = "retry_waiting"
    #: The lease expired without a heartbeat: the worker is presumed gone.
    STALE = "stale"
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
    #: Fires a schedule; each firing creates a *new* analysis execution.
    SCHEDULE_TRIGGER = "schedule_trigger"
    #: Recovers jobs whose lease expired without a heartbeat.
    STALE_RECOVERY = "stale_recovery"
    #: Validates, materializes and accepts a scientific result payload.
    RESULT_INGESTION = "result_ingestion"


class JobQueue(StrEnum):
    """Logical queues. Extensible: queue assignment is always explicit."""

    DEFAULT = "default"
    SCIENTIFIC = "scientific"
    IMPORT = "import"
    VALIDATION = "validation"
    MAINTENANCE = "maintenance"
    EXPORT = "export"


class JobErrorClass(StrEnum):
    """Structured job failure taxonomy.

    Retryability is a property of the class (see
    ``domain/analysis/policies.py``), never a guess made at the call site.
    """

    VALIDATION_ERROR = "validation_error"
    AUTHORIZATION_ERROR = "authorization_error"
    CONFIGURATION_ERROR = "configuration_error"
    RESOURCE_UNAVAILABLE = "resource_unavailable"
    SCIENTIFIC_CAPABILITY_UNAVAILABLE = "scientific_capability_unavailable"
    SCIENTIFIC_EXECUTION_ERROR = "scientific_execution_error"
    TRANSIENT_INFRASTRUCTURE_ERROR = "transient_infrastructure_error"
    TIMEOUT = "timeout"
    CANCELLATION = "cancellation"
    INTERNAL_ERROR = "internal_error"


class ScheduleState(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    ARCHIVED = "archived"


class ScheduleConcurrencyPolicy(StrEnum):
    ALLOW_CONCURRENT = "allow_concurrent"
    SKIP_IF_RUNNING = "skip_if_running"
    QUEUE_IF_RUNNING = "queue_if_running"


class MissedSchedulePolicy(StrEnum):
    """What happens to firings that never ran (downtime, disabled schedule)."""

    SKIP = "skip"
    RUN_ONCE_AFTER_RECOVERY = "run_once_after_recovery"
    CATCH_UP = "catch_up"


class ScheduleTriggerOutcome(StrEnum):
    TRIGGERED = "triggered"
    SKIPPED_CONCURRENCY = "skipped_concurrency"
    SKIPPED_MISSED = "skipped_missed"
    SKIPPED_DISABLED = "skipped_disabled"
    FAILED = "failed"


class NodeClass(StrEnum):
    APPLICATION_WORKER = "application_worker"
    SCIENTIFIC_WORKER = "scientific_worker"


class NodeHealthState(StrEnum):
    """Observed health. ``unknown`` is never treated as healthy."""

    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNAVAILABLE = "unavailable"
    MAINTENANCE = "maintenance"


class NodeLifecycleState(StrEnum):
    """Administrative intent for a node, separate from its observed health."""

    ACTIVE = "active"
    DRAINING = "draining"
    MAINTENANCE = "maintenance"
    UNAVAILABLE = "unavailable"


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
    """Variant type as *declared by the source or the scientific engine*.

    The application never derives a class from allele strings: deciding that a
    record is an indel rather than an MNV is a scientific judgement made outside
    this codebase. ``UNKNOWN`` exists so an undeclared class stays undeclared
    instead of being guessed.
    """

    SNV = "snv"
    MNV = "mnv"
    INSERTION = "insertion"
    DELETION = "deletion"
    INDEL = "indel"
    SYMBOLIC = "symbolic"
    STRUCTURAL = "structural"
    COPY_NUMBER = "copy_number"
    COMPLEX = "complex"
    UNKNOWN = "unknown"


class NormalizationState(StrEnum):
    """Whether a representation has been through scientific normalization.

    ``NOT_NORMALIZED`` means "not yet"; ``NORMALIZATION_UNAVAILABLE`` means the
    engine capability was not available at all. Collapsing the two would hide
    an operational gap behind a scientific-looking statement.
    """

    NOT_NORMALIZED = "not_normalized"
    NORMALIZED = "normalized"
    NORMALIZATION_FAILED = "normalization_failed"
    NORMALIZATION_UNAVAILABLE = "normalization_unavailable"


class Zygosity(StrEnum):
    """Zygosity exactly as reported. Never inferred from a genotype string."""

    HOMOZYGOUS_REFERENCE = "homozygous_reference"
    HETEROZYGOUS = "heterozygous"
    HOMOZYGOUS_ALTERNATE = "homozygous_alternate"
    HEMIZYGOUS = "hemizygous"
    UNKNOWN = "unknown"
    #: Reported, but not expressible in the categories above (e.g. polyploid).
    OTHER = "other"


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
    """Operational state of a result surface.

    Content immutability is a separate property from state: an ``AVAILABLE``
    result set is never edited, and a corrected run produces a *new* result set
    that supersedes it.
    """

    PENDING = "pending"
    GENERATING = "generating"
    #: Payload received, structurally validated, not yet materialized/accepted.
    VALIDATED = "validated"
    AVAILABLE = "available"
    #: Ingestion or materialization failed; no scientific content is claimed.
    FAILED = "failed"
    #: Replaced by a newer result set for the same result key. History is kept.
    SUPERSEDED = "superseded"
    INVALIDATED = "invalidated"
    EXPIRED = "expired"


class ResultCompleteness(StrEnum):
    """How complete the scientific engine declared its own output to be.

    Declared by the engine, never computed here, and never conflated with
    ``ResultSetState``: a *complete* payload can still fail materialization, and
    a *partial* payload can be perfectly available.
    """

    COMPLETE = "complete"
    PARTIAL = "partial"
    EMPTY = "empty"
    UNKNOWN = "unknown"


class ResultArtifactFormat(StrEnum):
    """Physical format of a stored result artifact."""

    PARQUET = "parquet"
    JSON = "json"
    JSONL = "jsonl"
    CSV = "csv"
    TSV = "tsv"
    VCF = "vcf"
    BINARY = "binary"
    OTHER = "other"


class ResultArtifactKind(StrEnum):
    """What a result artifact *is*, independent of its format."""

    VARIANT_TABLE = "variant_table"
    ANNOTATION_TABLE = "annotation_table"
    FREQUENCY_TABLE = "frequency_table"
    SUMMARY = "summary"
    MANIFEST = "manifest"
    LOG = "log"
    OTHER = "other"


class ResultArtifactState(StrEnum):
    """Lifecycle of one artifact belonging to a result set."""

    REGISTERED = "registered"
    VERIFYING = "verifying"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    #: Kept for lineage, no longer the current artifact for its key.
    SUPERSEDED = "superseded"
    MISSING = "missing"


class ResultIngestionState(StrEnum):
    """Lifecycle of a result-ingestion request.

    Deliberately separate from ``ResultSetState``: the request is an application
    workflow, the result set is the durable scientific surface it produces.
    """

    RECEIVED = "received"
    VALIDATING = "validating"
    VALIDATED = "validated"
    MATERIALIZING = "materializing"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"




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


# --------------------------------------------------------------------------- #
# Datasets, uploads, import and validation (Package 4)                        #
# --------------------------------------------------------------------------- #


class UploadSessionState(StrEnum):
    """Server-authoritative upload lifecycle.

    An upload session is the *permission to transfer bytes*, not the artifact
    itself. It is created before any byte is accepted, and its state is only ever
    advanced by the backend: a client that possesses a presigned URL still cannot
    make an artifact usable, because usability is decided by transfer-integrity
    verification, scanning and validation recorded here.
    """

    CREATED = "created"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    SCANNING = "scanning"
    QUARANTINED = "quarantined"
    VALIDATING = "validating"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"
    FAILED = "failed"


class InputFormat(StrEnum):
    """Declared or detected container format of an uploaded artifact.

    This is a *file format* fact, not a scientific interpretation: recognising
    that a file is a VCF says nothing about whether its variants are valid.
    """

    CSV = "csv"
    TSV = "tsv"
    VCF = "vcf"
    BCF = "bcf"
    TEXT = "text"
    JSON = "json"
    UNKNOWN = "unknown"


class CompressionKind(StrEnum):
    NONE = "none"
    GZIP = "gzip"
    BGZF = "bgzf"
    ZIP = "zip"
    UNKNOWN = "unknown"


class MalwareScanState(StrEnum):
    """Scanning is an integration boundary, and it fails closed.

    ``unavailable`` is deliberately distinct from ``clean``: an artifact that
    could not be scanned is never treated as safe.
    """

    NOT_SCANNED = "not_scanned"
    SCANNING = "scanning"
    CLEAN = "clean"
    INFECTED = "infected"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class MappingStatus(StrEnum):
    """Per-column outcome of an import mapping decision."""

    MAPPED = "mapped"
    UNMAPPED = "unmapped"
    AMBIGUOUS = "ambiguous"
    IGNORED = "ignored"


class MappingOrigin(StrEnum):
    """Whether a mapping decision came from a human or from a suggestion.

    Suggested and confirmed mappings are never conflated: an import that ran on
    unconfirmed suggestions stays distinguishable forever.
    """

    USER_SELECTED = "user_selected"
    SYSTEM_SUGGESTED = "system_suggested"
    TEMPLATE_APPLIED = "template_applied"


class FieldConcept(StrEnum):
    """Canonical platform field concepts a source column may be mapped to.

    A concept records *declared meaning only*. No normalization, no allele
    interpretation and no reference-genome processing happens in application
    code; those belong to the scientific compute subsystem.
    """

    CHROMOSOME = "chromosome"
    POSITION = "position"
    REFERENCE_ALLELE = "reference_allele"
    ALTERNATE_ALLELE = "alternate_allele"
    VARIANT_IDENTIFIER = "variant_identifier"
    GENE_SYMBOL = "gene_symbol"
    TRANSCRIPT_IDENTIFIER = "transcript_identifier"
    CONSEQUENCE = "consequence"
    SAMPLE_IDENTIFIER = "sample_identifier"
    GENOTYPE = "genotype"
    ZYGOSITY = "zygosity"
    READ_DEPTH = "read_depth"
    ALLELE_FREQUENCY = "allele_frequency"
    QUALITY = "quality"
    FILTER_STATUS = "filter_status"
    PHENOTYPE_TERM = "phenotype_term"
    #: Carried through verbatim as source metadata, with no platform meaning.
    PASSTHROUGH = "passthrough"
    IGNORED = "ignored"


class ReferenceBuildDeclaration(StrEnum):
    """The genome build a submitter *declares* for an input.

    A declaration is metadata, never a verification. Confirming that coordinates
    are consistent with a build is scientific work performed outside this layer.
    """

    GRCH37 = "grch37"
    GRCH38 = "grch38"
    T2T_CHM13 = "t2t_chm13"
    UNSPECIFIED = "unspecified"


class ValidationCategory(StrEnum):
    """Which concern a validation issue belongs to.

    Categories are kept explicit so that a transfer problem, a security refusal
    and a schema mismatch are never presented as the same class of failure.
    """

    TRANSFER_INTEGRITY = "transfer_integrity"
    SECURITY = "security"
    FILE_FORMAT = "file_format"
    STRUCTURE = "structure"
    TABULAR_SCHEMA = "tabular_schema"
    METADATA = "metadata"
    GENOMIC_SUITABILITY = "genomic_suitability"
    IMPORT_CONFIGURATION = "import_configuration"


class DuplicateRelation(StrEnum):
    """How a candidate input relates to something already in the same scope."""

    NONE = "none"
    SAME_CHECKSUM_IN_SCOPE = "same_checksum_in_scope"
    SAME_NAME_IN_SCOPE = "same_name_in_scope"


class QueryScope(StrEnum):
    """Who a saved filter, preset or ranking configuration is visible to.

    The order is a widening one, but visibility is never *inherited upwards*: a
    personal configuration is never globally visible, and an organization
    configuration is never available to an unrelated organization. The scope
    states where a configuration may be offered; authorization still decides
    whether a given caller may see or use it.
    """

    PERSONAL = "personal"
    PROJECT = "project"
    ORGANIZATION = "organization"
    PLATFORM = "platform"


class QueryDefinitionState(StrEnum):
    """Lifecycle of a saved filter, preset or ranking configuration.

    ``PUBLISHED`` is the point from which a version may be referenced by an
    analysis execution; from then on that *version* is immutable and editing
    produces a new one. ``ARCHIVED`` withdraws a definition from being offered
    without removing anything an execution already referenced.
    """

    DRAFT = "draft"
    PUBLISHED = "published"
    ARCHIVED = "archived"


class QueryExecutionOutcome(StrEnum):
    """How a filter or ranking execution ended.

    Recorded so an empty page can be told apart from a query the platform
    stopped: zero surviving variants and a refused query must never look alike.
    """

    COMPLETED = "completed"
    LIMIT_EXCEEDED = "limit_exceeded"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    FAILED = "failed"
