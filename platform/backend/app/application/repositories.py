"""Repository ports.

Protocols only: the application layer states what it needs, infrastructure
supplies it. Nothing here imports SQLAlchemy, so use cases remain testable
against in-memory implementations and cannot smuggle SQL into the domain.

Two conventions hold throughout:

* Reads are **scope-explicit**. A repository never returns "everything"; a caller
  passes the workspace, organization or project scope it has been authorized for.
* Writes are **version-checked** where the entity is mutable. A concurrent update
  raises ``ConcurrencyConflictError`` rather than silently overwriting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from app.domain.analysis.entities import (
    AnalysisConfigurationVersion,
    AnalysisDefinition,
    AnalysisExecutionRecord,
    AnalysisSchedule,
    ComputeNode,
    ConfigurationInput,
    ExecutionInput,
    JobAttemptRecord,
    JobRecord,
    ScheduleTrigger,
    ScientificArtifactRecord,
    ScientificExecutionRecord,
)
from app.domain.annotation.entities import (
    AnnotationProfileRecord,
    AnnotationProfileVersionRecord,
    AnnotationResourceRecord,
    AnnotationResultVersionRecord,
    AnnotationRunRecord,
    AnnotationValidationFinding,
)
from app.domain.data.entities import (
    ColumnMapping,
    Dataset,
    DatasetVersion,
    FileArtifact,
    ImportSession,
    UploadSession,
    ValidationIssue,
    ValidationRun,
)
from app.domain.events import DomainEvent
from app.domain.evidence.entities import (
    EvidenceIngestionBatch,
    EvidenceRecord,
    EvidenceSourceRecord,
    EvidenceValidationFinding,
)
from app.domain.identity.entities import (
    Credentials,
    CredentialToken,
    Session,
    UserAccount,
)
from app.domain.interpretation.entities import (
    AutomatedClassificationRecord,
    BenchmarkCaseRecord,
    BenchmarkRunRecord,
    ClassificationEvaluationRecord,
    CriterionEvaluationRecord,
    RulesetRecord,
)
from app.domain.organization.entities import (
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
)
from app.domain.project.entities import Project, ProjectMembership
from app.domain.query.entities import (
    FilterDefinitionRecord,
    FilterExecutionRecord,
    FilterPresetRecord,
    FilterPresetVersionRecord,
    FilterVersionRecord,
    RankingDefinitionRecord,
    RankingExecutionRecord,
    RankingPresetRecord,
    RankingPresetVersionRecord,
    RankingVersionRecord,
    SavedViewRecord,
)
from app.domain.review.entities import (
    InterpretationRecord,
    InterpretationVersionRecord,
    ReviewAssignmentRecord,
    ReviewDecisionRecord,
)
from app.domain.value_objects.enums import (
    ActorType,
    AnalysisState,
    AnnotationResourceCategory,
    AnnotationRunState,
    AuditChannel,
    AuditOutcome,
    BenchmarkValidationKind,
    ClassificationEvaluationState,
    CredentialTokenKind,
    DatasetState,
    EvidenceCategory,
    EvidenceIngestionState,
    EvidenceRecordState,
    EvidenceSourceCategory,
    ExecutionState,
    InterpretationState,
    InvitationState,
    JobErrorClass,
    JobKind,
    JobState,
    MembershipState,
    NodeClass,
    OrganizationState,
    PlatformRole,
    ResultIngestionState,
    ResultSetState,
    ReviewState,
    ScheduleState,
    ScheduleTriggerOutcome,
)
from app.domain.variant.entities import (
    ClinicalAssertionRecord,
    DatasetVersionVariant,
    GeneReference,
    PopulationFrequencyRecord,
    PopulationRecord,
    SampleObservation,
    SampleRecord,
    TranscriptContext,
    TranscriptReference,
    VariantAnnotationRecord,
    VariantExternalIdentifier,
    VariantRecord,
    VariantRepresentation,
    VariantSourceRepresentation,
)
from app.domain.variant.results import (
    ResultArtifactRecord,
    ResultIngestionRequest,
    ResultSetRecord,
)
from app.domain.workspace.entities import Workspace


@dataclass(frozen=True, slots=True)
class Page:
    """Pagination request. Bounded by application configuration at the edge."""

    number: int = 1
    size: int = 25

    @property
    def offset(self) -> int:
        return (self.number - 1) * self.size


@dataclass(frozen=True, slots=True)
class Paged[T]:
    items: tuple[T, ...]
    total: int
    page: Page


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """One audit fact: who did what, to what, with what outcome."""

    action: str
    outcome: AuditOutcome
    occurred_at: datetime
    actor_type: ActorType = ActorType.USER
    actor_user_id: str | None = None
    actor_label: str | None = None
    channel: AuditChannel = AuditChannel.API
    resource_type: str | None = None
    resource_id: str | None = None
    organization_id: str | None = None
    workspace_id: str | None = None
    project_id: str | None = None
    previous_state: str | None = None
    new_state: str | None = None
    reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    correlation_id: str | None = None
    request_ip_hash: str | None = None
    user_agent_summary: str | None = None


@dataclass(frozen=True, slots=True)
class SecurityRecord:
    """One security-relevant fact. Never contains a credential or a raw address."""

    event_kind: str
    outcome: AuditOutcome
    occurred_at: datetime
    subject_user_id: str | None = None
    subject_identifier_hash: str | None = None
    request_ip_hash: str | None = None
    user_agent_summary: str | None = None
    correlation_id: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class UserRepository(Protocol):
    async def get(self, user_id: str) -> UserAccount | None: ...
    async def get_by_email(self, email_normalized: str) -> UserAccount | None: ...
    async def add(self, account: UserAccount) -> UserAccount: ...
    async def save(self, account: UserAccount) -> UserAccount: ...
    async def set_personal_workspace(self, user_id: str, workspace_id: str) -> None: ...
    async def touch_activity(self, user_id: str, moment: datetime) -> None: ...
    async def list_accounts(
        self, *, page: Page, query: str | None = None
    ) -> Paged[UserAccount]: ...


@runtime_checkable
class CredentialsRepository(Protocol):
    async def get(self, user_id: str) -> Credentials | None: ...
    async def create(self, credentials: Credentials) -> Credentials: ...
    async def replace_password(
        self, user_id: str, *, password_hash: str, algorithm: str, moment: datetime
    ) -> None: ...
    async def register_failure(
        self, user_id: str, *, moment: datetime, lock_until: datetime | None
    ) -> int: ...
    async def register_success(self, user_id: str, *, moment: datetime) -> None: ...


@runtime_checkable
class SessionRepository(Protocol):
    async def create(self, session: Session, *, token_hash: str) -> Session: ...
    async def get_by_token_hash(self, token_hash: str) -> Session | None: ...
    async def touch(self, session_id: str, *, last_seen_at: datetime, expires_at: datetime) -> None: ...
    async def revoke(self, session_id: str, *, reason: str, moment: datetime) -> None: ...
    async def revoke_all_for_user(
        self, user_id: str, *, reason: str, moment: datetime, keep_session_id: str | None = None
    ) -> int: ...
    async def list_active_for_user(self, user_id: str) -> tuple[Session, ...]: ...


@runtime_checkable
class CredentialTokenRepository(Protocol):
    async def create(self, token: CredentialToken, *, token_hash: str) -> CredentialToken: ...
    async def get_by_token_hash(self, token_hash: str) -> CredentialToken | None: ...
    async def consume(self, token_id: str, *, moment: datetime) -> None: ...
    async def invalidate_active(
        self, user_id: str, kind: CredentialTokenKind, *, reason: str, moment: datetime
    ) -> int: ...


@runtime_checkable
class WorkspaceRepository(Protocol):
    async def add(self, workspace: Workspace) -> Workspace: ...
    async def get(self, workspace_id: str) -> Workspace | None: ...
    async def get_personal_for_user(self, user_id: str) -> Workspace | None: ...
    async def get_for_organization(self, organization_id: str) -> Workspace | None: ...
    async def list_for_user(self, user_id: str) -> tuple[Workspace, ...]: ...


@runtime_checkable
class OrganizationRepository(Protocol):
    async def add(self, organization: Organization) -> Organization: ...
    async def get(self, organization_id: str) -> Organization | None: ...
    async def get_by_slug(self, slug: str) -> Organization | None: ...
    async def save(self, organization: Organization) -> Organization: ...
    async def list_by_states(
        self, states: tuple[OrganizationState, ...], *, page: Page
    ) -> Paged[Organization]: ...
    async def list_for_user(self, user_id: str, *, page: Page) -> Paged[Organization]: ...


@runtime_checkable
class OrganizationMembershipRepository(Protocol):
    async def add(self, membership: OrganizationMembership) -> OrganizationMembership: ...
    async def get(
        self, organization_id: str, user_id: str
    ) -> OrganizationMembership | None: ...
    async def save(self, membership: OrganizationMembership) -> OrganizationMembership: ...
    async def list_for_user(self, user_id: str) -> tuple[OrganizationMembership, ...]: ...
    async def list_for_organization(
        self, organization_id: str, *, page: Page, states: tuple[MembershipState, ...] | None = None
    ) -> Paged[OrganizationMembership]: ...
    async def count_active_with_role(self, organization_id: str, role: str) -> int: ...


@runtime_checkable
class OrganizationInvitationRepository(Protocol):
    async def add(
        self, invitation: OrganizationInvitation, *, token_hash: str
    ) -> OrganizationInvitation: ...
    async def get(self, invitation_id: str) -> OrganizationInvitation | None: ...
    async def get_by_token_hash(self, token_hash: str) -> OrganizationInvitation | None: ...
    async def get_open_for_email(
        self, organization_id: str, email_normalized: str
    ) -> OrganizationInvitation | None: ...
    async def save(self, invitation: OrganizationInvitation) -> OrganizationInvitation: ...
    async def list_for_organization(
        self, organization_id: str, *, page: Page, states: tuple[InvitationState, ...] | None = None
    ) -> Paged[OrganizationInvitation]: ...
    async def list_open_for_email(
        self, email_normalized: str
    ) -> tuple[OrganizationInvitation, ...]: ...


@runtime_checkable
class ProjectRepository(Protocol):
    async def add(self, project: Project) -> Project: ...
    async def get(self, project_id: str) -> Project | None: ...
    async def save(self, project: Project) -> Project: ...
    async def list_for_workspaces(
        self, workspace_ids: tuple[str, ...], *, page: Page
    ) -> Paged[Project]: ...


@runtime_checkable
class ProjectMembershipRepository(Protocol):
    async def add(self, membership: ProjectMembership) -> ProjectMembership: ...
    async def get(self, project_id: str, user_id: str) -> ProjectMembership | None: ...
    async def save(self, membership: ProjectMembership) -> ProjectMembership: ...
    async def list_for_user(self, user_id: str) -> tuple[ProjectMembership, ...]: ...
    async def list_for_project(
        self, project_id: str, *, page: Page
    ) -> Paged[ProjectMembership]: ...
    async def count_active_with_role(self, project_id: str, role: str) -> int: ...


@runtime_checkable
class PlatformRoleRepository(Protocol):
    async def list_active_for_user(self, user_id: str) -> frozenset[PlatformRole]: ...
    async def grant(
        self, user_id: str, role: PlatformRole, *, granted_by: str, moment: datetime
    ) -> None: ...
    async def revoke(self, user_id: str, role: PlatformRole, *, moment: datetime) -> None: ...


@runtime_checkable
class AuditRepository(Protocol):
    """Append-only. There is deliberately no update or delete method."""

    async def record(self, record: AuditRecord) -> None: ...


@runtime_checkable
class SecurityEventRepository(Protocol):
    async def record(self, record: SecurityRecord) -> None: ...


@runtime_checkable
class OutboxRepository(Protocol):
    async def publish(self, event: DomainEvent) -> None: ...


@runtime_checkable
class NotificationRepository(Protocol):
    async def create(
        self,
        *,
        recipient_user_id: str,
        notification_kind: str,
        subject: str,
        body: str | None,
        occurred_at: datetime,
        organization_id: str | None = None,
        workspace_id: str | None = None,
        project_id: str | None = None,
        subject_resource_type: str | None = None,
        subject_resource_id: str | None = None,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> str: ...


# --------------------------------------------------------------------------- #
# Datasets, files and ingestion                                               #
# --------------------------------------------------------------------------- #


@runtime_checkable
class DatasetRepository(Protocol):
    async def add(self, dataset: Dataset) -> Dataset: ...
    async def get(self, dataset_id: str) -> Dataset | None: ...
    async def save(self, dataset: Dataset) -> Dataset: ...
    async def list_for_scope(
        self,
        *,
        workspace_ids: tuple[str, ...],
        page: Page,
        project_id: str | None = None,
        states: tuple[DatasetState, ...] = (),
        query: str | None = None,
        include_archived: bool = False,
    ) -> Paged[Dataset]: ...
    async def name_exists(
        self, *, workspace_id: str, project_id: str | None, name: str
    ) -> bool: ...


@runtime_checkable
class DatasetVersionRepository(Protocol):
    async def add(self, version: DatasetVersion) -> DatasetVersion: ...
    async def get(self, version_id: str) -> DatasetVersion | None: ...
    async def save(self, version: DatasetVersion) -> DatasetVersion: ...
    async def list_for_dataset(self, dataset_id: str, *, page: Page) -> Paged[DatasetVersion]: ...
    async def next_version_number(self, dataset_id: str) -> int: ...
    async def list_accepted(self, dataset_id: str) -> tuple[DatasetVersion, ...]: ...


@runtime_checkable
class FileArtifactRepository(Protocol):
    async def add(self, artifact: FileArtifact) -> FileArtifact: ...
    async def get(self, artifact_id: str) -> FileArtifact | None: ...
    async def save(self, artifact: FileArtifact) -> FileArtifact: ...
    async def list_for_version(self, version_id: str) -> tuple[FileArtifact, ...]: ...
    async def find_by_checksum(
        self, *, workspace_id: str, checksum_algorithm: str, checksum_value: str
    ) -> FileArtifact | None: ...
    async def find_by_filename(
        self, *, workspace_id: str, filename: str
    ) -> FileArtifact | None: ...


@runtime_checkable
class UploadSessionRepository(Protocol):
    async def add(self, session: UploadSession) -> UploadSession: ...
    async def get(self, session_id: str) -> UploadSession | None: ...
    async def save(self, session: UploadSession) -> UploadSession: ...
    async def get_for_artifact(self, artifact_id: str) -> UploadSession | None: ...
    async def list_for_version(self, version_id: str) -> tuple[UploadSession, ...]: ...
    async def list_expired(
        self, *, moment: datetime, limit: int = 100
    ) -> tuple[UploadSession, ...]: ...


@runtime_checkable
class ImportSessionRepository(Protocol):
    async def add(self, session: ImportSession) -> ImportSession: ...
    async def get(self, session_id: str) -> ImportSession | None: ...
    async def save(self, session: ImportSession) -> ImportSession: ...
    async def get_by_idempotency_key(self, key: str) -> ImportSession | None: ...
    async def list_for_dataset(self, dataset_id: str, *, page: Page) -> Paged[ImportSession]: ...


@runtime_checkable
class ColumnMappingRepository(Protocol):
    async def replace_all(
        self, import_session_id: str, mappings: tuple[ColumnMapping, ...]
    ) -> tuple[ColumnMapping, ...]: ...
    async def list_for_session(self, import_session_id: str) -> tuple[ColumnMapping, ...]: ...


@runtime_checkable
class ValidationRunRepository(Protocol):
    async def add(self, run: ValidationRun) -> ValidationRun: ...
    async def get(self, run_id: str) -> ValidationRun | None: ...
    async def save(self, run: ValidationRun) -> ValidationRun: ...
    async def list_for_subject(
        self, *, subject_type: str, subject_id: str, page: Page
    ) -> Paged[ValidationRun]: ...
    async def latest_for_subject(
        self, *, subject_type: str, subject_id: str
    ) -> ValidationRun | None: ...


@runtime_checkable
class ValidationIssueRepository(Protocol):
    async def add_many(self, issues: tuple[ValidationIssue, ...]) -> None: ...
    async def list_for_run(self, run_id: str, *, page: Page) -> Paged[ValidationIssue]: ...


@runtime_checkable
class JobRepository(Protocol):
    """Durable work: transactional enqueue, then concurrency-safe execution.

    Enqueueing happens inside the business transaction that requested the work,
    so a job can never reference state that was rolled back, and a committed
    state change can never lose its follow-up work.

    The execution half of the port is deliberately narrow and explicit. Claiming
    is a single atomic statement that also writes the lease; a worker that stops
    heartbeating loses its claim when the lease expires, and recovery re-queues
    that job instead of leaving it "running" forever.
    """

    async def enqueue(
        self,
        *,
        kind: JobKind,
        payload: dict[str, Any],
        correlation_id: str,
        queue: str = "default",
        priority: int = 100,
        workspace_id: str | None = None,
        project_id: str | None = None,
        requested_by: str | None = None,
        idempotency_key: str | None = None,
        available_at: datetime | None = None,
        max_attempts: int = 3,
        analysis_execution_id: str | None = None,
        scheduled_job_id: str | None = None,
        node_class: NodeClass = NodeClass.APPLICATION_WORKER,
        resource_requirements: dict[str, Any] | None = None,
        required_capabilities: tuple[str, ...] = (),
        lease_duration_seconds: int = 60,
        execution_context_ref: str | None = None,
    ) -> str: ...
    async def get(self, job_id: str) -> dict[str, Any] | None: ...
    async def find(self, job_id: str) -> JobRecord | None: ...
    async def claim_next(
        self,
        *,
        worker_id: str,
        queues: tuple[str, ...],
        node_class: NodeClass,
        kinds: tuple[JobKind, ...] = (),
        now: datetime,
        lease_expires_at: datetime,
        node_id: str | None = None,
    ) -> JobRecord | None:
        """Atomically take the highest-priority available job, or return None."""
        ...

    async def heartbeat(
        self,
        *,
        job_id: str,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
        progress_percent: int | None = None,
        progress_message: str | None = None,
    ) -> JobRecord | None:
        """Extend the lease *only* while this worker still holds the claim."""
        ...

    async def mark_running(
        self, *, job_id: str, worker_id: str, now: datetime
    ) -> JobRecord | None: ...
    async def complete(self, *, job_id: str, worker_id: str, now: datetime) -> None: ...
    async def fail(
        self,
        *,
        job_id: str,
        worker_id: str,
        now: datetime,
        error_class: JobErrorClass,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        retry_at: datetime | None = None,
        dead_letter: bool = False,
    ) -> JobRecord | None:
        """Record the failure and either schedule a retry or dead-letter it."""
        ...

    async def request_cancellation(
        self, *, job_id: str, requested_by: str | None, now: datetime
    ) -> JobRecord | None: ...
    async def mark_cancelled(self, *, job_id: str, now: datetime) -> JobRecord | None: ...
    async def recover_stale(
        self, *, before: datetime, now: datetime, limit: int = 50
    ) -> tuple[JobRecord, ...]:
        """Re-queue or dead-letter jobs whose lease expired without a heartbeat."""
        ...

    async def add_attempt(self, attempt: JobAttemptRecord) -> JobAttemptRecord: ...
    async def list_attempts(self, job_id: str) -> tuple[JobAttemptRecord, ...]: ...
    async def list_for_scope(
        self,
        *,
        workspace_ids: tuple[str, ...],
        page: Page,
        project_id: str | None = None,
        states: tuple[JobState, ...] = (),
        kinds: tuple[JobKind, ...] = (),
        queue: str | None = None,
    ) -> Paged[JobRecord]: ...
    async def list_all(
        self,
        *,
        page: Page,
        states: tuple[JobState, ...] = (),
        kinds: tuple[JobKind, ...] = (),
        queue: str | None = None,
    ) -> Paged[JobRecord]:
        """Platform-administrative listing across every tenant."""
        ...

    async def queue_statistics(self) -> tuple[dict[str, Any], ...]: ...


@runtime_checkable
class AnalysisRepository(Protocol):
    async def add(self, analysis: AnalysisDefinition) -> AnalysisDefinition: ...
    async def get(self, analysis_id: str) -> AnalysisDefinition | None: ...
    async def save(self, analysis: AnalysisDefinition) -> AnalysisDefinition: ...
    async def name_exists(self, *, project_id: str, name: str) -> bool: ...
    async def list_for_scope(
        self,
        *,
        workspace_ids: tuple[str, ...],
        page: Page,
        project_id: str | None = None,
        states: tuple[AnalysisState, ...] = (),
        query: str | None = None,
    ) -> Paged[AnalysisDefinition]: ...


@runtime_checkable
class AnalysisConfigurationRepository(Protocol):
    """Configuration versions are immutable; there is no ``save`` for content."""

    async def add(
        self, configuration: AnalysisConfigurationVersion
    ) -> AnalysisConfigurationVersion: ...
    async def get(self, configuration_id: str) -> AnalysisConfigurationVersion | None: ...
    async def record_validation(
        self, configuration: AnalysisConfigurationVersion
    ) -> AnalysisConfigurationVersion: ...
    async def next_version_number(self, analysis_id: str) -> int: ...
    async def list_for_analysis(
        self, analysis_id: str, *, page: Page
    ) -> Paged[AnalysisConfigurationVersion]: ...
    async def add_inputs(self, inputs: tuple[ConfigurationInput, ...]) -> None: ...
    async def list_inputs(self, configuration_id: str) -> tuple[ConfigurationInput, ...]: ...


@runtime_checkable
class AnalysisExecutionRepository(Protocol):
    async def add(self, execution: AnalysisExecutionRecord) -> AnalysisExecutionRecord: ...
    async def get(self, execution_id: str) -> AnalysisExecutionRecord | None: ...
    async def save(self, execution: AnalysisExecutionRecord) -> AnalysisExecutionRecord: ...
    async def find_by_idempotency_key(self, key: str) -> AnalysisExecutionRecord | None: ...
    async def next_attempt_sequence(self, analysis_id: str) -> int: ...
    async def count_active_for_analysis(self, analysis_id: str) -> int: ...
    async def list_for_scope(
        self,
        *,
        workspace_ids: tuple[str, ...],
        page: Page,
        analysis_id: str | None = None,
        project_id: str | None = None,
        states: tuple[ExecutionState, ...] = (),
    ) -> Paged[AnalysisExecutionRecord]: ...
    async def add_inputs(self, inputs: tuple[ExecutionInput, ...]) -> None: ...
    async def list_inputs(self, execution_id: str) -> tuple[ExecutionInput, ...]: ...


@runtime_checkable
class ScheduleRepository(Protocol):
    async def add(self, schedule: AnalysisSchedule) -> AnalysisSchedule: ...
    async def get(self, schedule_id: str) -> AnalysisSchedule | None: ...
    async def save(self, schedule: AnalysisSchedule) -> AnalysisSchedule: ...
    async def name_exists(self, *, owner_scope: str, owner_id: str | None, name: str) -> bool: ...
    async def list_for_scope(
        self,
        *,
        workspace_ids: tuple[str, ...],
        page: Page,
        project_id: str | None = None,
        states: tuple[ScheduleState, ...] = (),
    ) -> Paged[AnalysisSchedule]: ...
    async def list_due(self, *, now: datetime, limit: int = 25) -> tuple[AnalysisSchedule, ...]: ...
    async def record_trigger(self, trigger: ScheduleTrigger) -> ScheduleTrigger | None:
        """Return ``None`` when this slot was already claimed by another run."""
        ...

    async def finalize_trigger(
        self,
        *,
        schedule_id: str,
        scheduled_for: datetime,
        outcome: ScheduleTriggerOutcome,
        analysis_execution_id: str | None = None,
        job_id: str | None = None,
        detail: dict | None = None,
    ) -> None:
        """Complete a claimed slot in place once its real outcome is known."""
        ...

    async def list_triggers(
        self, schedule_id: str, *, page: Page
    ) -> Paged[ScheduleTrigger]: ...


@runtime_checkable
class ComputeNodeRepository(Protocol):
    async def upsert(self, node: ComputeNode) -> ComputeNode: ...
    async def get_by_key(self, node_key: str) -> ComputeNode | None: ...
    async def get(self, node_id: str) -> ComputeNode | None: ...
    async def save(self, node: ComputeNode) -> ComputeNode: ...
    async def list_nodes(
        self, *, node_class: NodeClass | None = None, page: Page | None = None
    ) -> tuple[ComputeNode, ...]: ...
    async def mark_unhealthy_before(self, *, threshold: datetime) -> int:
        """Nodes that stopped heartbeating are not silently kept schedulable."""
        ...


@runtime_checkable
class ScientificExecutionRepository(Protocol):
    """Append-only mirror of the scientific subsystem's runs, for provenance."""

    async def add(self, record: ScientificExecutionRecord) -> ScientificExecutionRecord: ...
    async def get(self, record_id: str) -> ScientificExecutionRecord | None: ...
    async def record_outcome(
        self, record: ScientificExecutionRecord
    ) -> ScientificExecutionRecord: ...
    async def record_artifacts(
        self, artifacts: tuple[ScientificArtifactRecord, ...]
    ) -> tuple[ScientificArtifactRecord, ...]: ...

    async def list_artifacts(
        self, scientific_execution_id: str
    ) -> tuple[ScientificArtifactRecord, ...]: ...

    async def list_for_execution(
        self, analysis_execution_id: str
    ) -> tuple[ScientificExecutionRecord, ...]: ...


# --------------------------------------------------------------------------- #
# Package 6: the scientific data layer
# --------------------------------------------------------------------------- #


@runtime_checkable
class VariantRepository(Protocol):
    """Canonical variants and everything attached to them.

    Canonical variants are *shared reference data*: they carry no tenant, because
    the same genomic change observed in two organizations is the same change.
    Tenant isolation therefore happens on the rows that are tenant-owned —
    observations, dataset-version membership, result sets — never on this table,
    and no listing method here is reachable without a scope filter supplied by
    the caller.
    """

    async def get(self, variant_id: str) -> VariantRecord | None: ...
    async def get_by_canonical_key(self, canonical_key: str) -> VariantRecord | None: ...
    async def add(self, variant: VariantRecord) -> VariantRecord: ...
    async def get_or_add(self, variant: VariantRecord) -> tuple[VariantRecord, bool]:
        """Idempotent insert. Returns ``(record, created)``.

        Concurrent ingestion of the same variant must converge on one row rather
        than raise: two datasets legitimately contain the same variant.
        """
        ...

    async def list_for_dataset_version(
        self,
        dataset_version_id: str,
        *,
        page: Page,
        contig: str | None = None,
        position_from: int | None = None,
        position_to: int | None = None,
        query: str | None = None,
    ) -> Paged[VariantRecord]: ...
    async def count_for_dataset_version(self, dataset_version_id: str) -> int: ...


@runtime_checkable
class VariantRepresentationRepository(Protocol):
    """Append-only normalization history, including failures."""

    async def add_many(
        self, representations: tuple[VariantRepresentation, ...]
    ) -> tuple[VariantRepresentation, ...]: ...
    async def list_for_variant(
        self, variant_id: str
    ) -> tuple[VariantRepresentation, ...]: ...
    async def list_for_source_representation(
        self, source_representation_id: str
    ) -> tuple[VariantRepresentation, ...]: ...


@runtime_checkable
class VariantSourceRepresentationRepository(Protocol):
    """The submitted representation, preserved verbatim and never rewritten."""

    async def add_many(
        self, representations: tuple[VariantSourceRepresentation, ...]
    ) -> tuple[VariantSourceRepresentation, ...]: ...
    async def get(self, representation_id: str) -> VariantSourceRepresentation | None: ...
    async def link_variant(
        self, *, representation_id: str, variant_id: str
    ) -> VariantSourceRepresentation | None: ...
    async def list_for_variant(
        self, variant_id: str, *, dataset_version_id: str | None = None
    ) -> tuple[VariantSourceRepresentation, ...]: ...
    async def find_by_source_key(
        self, *, dataset_version_id: str, source_record_key: str
    ) -> VariantSourceRepresentation | None: ...


@runtime_checkable
class DatasetVersionVariantRepository(Protocol):
    async def add_many(
        self, memberships: tuple[DatasetVersionVariant, ...]
    ) -> tuple[DatasetVersionVariant, ...]: ...
    async def workspace_ids_for_variant(self, variant_id: str) -> tuple[str, ...]:
        """Which tenants may see this variant at all. Used for authorization."""
        ...

    async def list_dataset_versions(self, variant_id: str) -> tuple[str, ...]: ...


@runtime_checkable
class VariantContextRepository(Protocol):
    """Transcript contexts, observations, annotations, frequencies, assertions.

    One port, because these are all *per-variant scientific facts with their own
    provenance* and are always read together on a variant detail surface. They
    are separate tables, never one JSONB column, and none of them is derivable
    from another.
    """

    #: Resolves the cohort a frequency observation refers to. The cohort identity
    #: comes from the population resource; the platform only records it.
    async def get_or_add_population(
        self, population: PopulationRecord
    ) -> tuple[PopulationRecord, bool]: ...
    async def add_transcript_contexts(
        self, contexts: tuple[TranscriptContext, ...]
    ) -> tuple[TranscriptContext, ...]: ...
    async def list_transcript_contexts(
        self, variant_id: str, *, page: Page
    ) -> Paged[TranscriptContext]: ...
    async def add_observations(
        self, observations: tuple[SampleObservation, ...]
    ) -> tuple[SampleObservation, ...]: ...
    async def list_observations(
        self,
        variant_id: str,
        *,
        page: Page,
        dataset_version_id: str | None = None,
    ) -> Paged[SampleObservation]: ...
    async def add_annotations(
        self, annotations: tuple[VariantAnnotationRecord, ...]
    ) -> tuple[VariantAnnotationRecord, ...]: ...
    async def list_annotations(
        self, variant_id: str, *, page: Page, source_key: str | None = None
    ) -> Paged[VariantAnnotationRecord]: ...
    async def add_frequencies(
        self, frequencies: tuple[PopulationFrequencyRecord, ...]
    ) -> tuple[PopulationFrequencyRecord, ...]: ...
    async def list_frequencies(
        self, variant_id: str, *, page: Page
    ) -> Paged[PopulationFrequencyRecord]: ...
    async def add_clinical_assertions(
        self, assertions: tuple[ClinicalAssertionRecord, ...]
    ) -> tuple[ClinicalAssertionRecord, ...]: ...
    async def list_clinical_assertions(
        self, variant_id: str, *, page: Page
    ) -> Paged[ClinicalAssertionRecord]: ...


@runtime_checkable
class SampleRepository(Protocol):
    """Tenant-scoped subjects. A sample key is unique within a workspace only."""

    async def get(self, sample_id: str) -> SampleRecord | None: ...
    async def get_or_add(self, sample: SampleRecord) -> tuple[SampleRecord, bool]: ...
    async def find_by_key(
        self, *, workspace_id: str, sample_key: str
    ) -> SampleRecord | None: ...
    async def list_for_workspace(
        self, workspace_id: str, *, page: Page
    ) -> Paged[SampleRecord]: ...


@runtime_checkable
class GeneTranscriptRepository(Protocol):
    """Reference gene/transcript rows, resolved by identifier, never invented."""

    async def get_or_add_gene(self, gene: GeneReference) -> tuple[GeneReference, bool]: ...
    async def get_or_add_transcript(
        self, transcript: TranscriptReference
    ) -> tuple[TranscriptReference, bool]: ...
    async def find_gene(
        self, *, source_key: str, gene_identifier: str
    ) -> GeneReference | None: ...
    async def find_transcript(
        self, *, source_key: str, transcript_identifier: str
    ) -> TranscriptReference | None: ...


@runtime_checkable
class VariantIdentifierRepository(Protocol):
    """External identifiers. An identifier is a label, never an identity."""

    async def add_many(
        self, identifiers: tuple[VariantExternalIdentifier, ...]
    ) -> tuple[VariantExternalIdentifier, ...]: ...
    async def list_for_variant(
        self, variant_id: str
    ) -> tuple[VariantExternalIdentifier, ...]: ...


@runtime_checkable
class ResultSetRepository(Protocol):
    """Immutable result surfaces produced by an execution.

    ``save`` exists for *state and lineage* transitions only — becoming
    available, being superseded, being invalidated. Scientific content is never
    updated: a corrected run creates a new result set that supersedes the old.
    """

    async def add(self, result_set: ResultSetRecord) -> ResultSetRecord: ...
    async def get(self, result_set_id: str) -> ResultSetRecord | None: ...
    async def save(self, result_set: ResultSetRecord) -> ResultSetRecord: ...
    async def find_by_result_key(
        self, *, analysis_execution_id: str, result_key: str
    ) -> ResultSetRecord | None: ...
    async def list_for_scope(
        self,
        *,
        workspace_ids: tuple[str, ...],
        page: Page,
        project_id: str | None = None,
        analysis_execution_id: str | None = None,
        states: tuple[ResultSetState, ...] = (),
    ) -> Paged[ResultSetRecord]: ...
    async def list_all(
        self, *, page: Page, states: tuple[ResultSetState, ...] = ()
    ) -> Paged[ResultSetRecord]:
        """Platform-wide listing for the control plane. Never a tenant path."""
        ...


@runtime_checkable
class ResultArtifactRepository(Protocol):
    async def add_many(
        self, artifacts: tuple[ResultArtifactRecord, ...]
    ) -> tuple[ResultArtifactRecord, ...]: ...
    async def get(self, artifact_id: str) -> ResultArtifactRecord | None: ...
    async def save(self, artifact: ResultArtifactRecord) -> ResultArtifactRecord: ...
    async def list_for_result_set(
        self, result_set_id: str
    ) -> tuple[ResultArtifactRecord, ...]: ...


@runtime_checkable
class ResultIngestionRepository(Protocol):
    async def add(self, request: ResultIngestionRequest) -> ResultIngestionRequest: ...
    async def get(self, request_id: str) -> ResultIngestionRequest | None: ...
    async def save(self, request: ResultIngestionRequest) -> ResultIngestionRequest: ...
    async def get_by_idempotency_key(self, key: str) -> ResultIngestionRequest | None: ...
    async def list_for_scope(
        self,
        *,
        workspace_ids: tuple[str, ...],
        page: Page,
        project_id: str | None = None,
        states: tuple[ResultIngestionState, ...] = (),
    ) -> Paged[ResultIngestionRequest]: ...


# --------------------------------------------------------------------------- #
# Filtering, ranking and saved views                                          #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class QueryScopeFilter:
    """The scopes a caller has been authorized to see configurations from.

    Passed explicitly on every read, so no listing can accidentally reach outside
    a tenant. An empty filter selects platform-scoped configurations only, which
    is exactly what an authenticated caller with no memberships should see.
    """

    user_id: str | None = None
    workspace_ids: tuple[str, ...] = ()
    project_ids: tuple[str, ...] = ()
    organization_ids: tuple[str, ...] = ()
    include_platform: bool = True


@runtime_checkable
class FilterDefinitionRepository(Protocol):
    """Saved filters and their immutable version history.

    ``save`` only ever writes definition *metadata* — name, description,
    lifecycle, ownership. Content changes go through ``add_version``, which is
    append-only, so an execution that referenced version 3 keeps resolving to
    version 3 forever.
    """

    async def add(self, definition: FilterDefinitionRecord) -> FilterDefinitionRecord: ...
    async def get(self, definition_id: str) -> FilterDefinitionRecord | None: ...
    async def save(self, definition: FilterDefinitionRecord) -> FilterDefinitionRecord: ...
    async def add_version(self, version: FilterVersionRecord) -> FilterVersionRecord: ...
    async def get_version(self, version_id: str) -> FilterVersionRecord | None: ...
    async def find_version(
        self, *, definition_id: str, version_number: int
    ) -> FilterVersionRecord | None: ...
    async def latest_version(self, definition_id: str) -> FilterVersionRecord | None: ...
    async def list_versions(
        self, definition_id: str
    ) -> tuple[FilterVersionRecord, ...]: ...
    async def mark_version_referenced(self, version_id: str) -> None: ...
    async def list_for_scope(
        self, *, scopes: QueryScopeFilter, page: Page
    ) -> Paged[FilterDefinitionRecord]: ...


@runtime_checkable
class FilterPresetRepository(Protocol):
    async def add(self, preset: FilterPresetRecord) -> FilterPresetRecord: ...
    async def get(self, preset_id: str) -> FilterPresetRecord | None: ...
    async def save(self, preset: FilterPresetRecord) -> FilterPresetRecord: ...
    async def add_version(
        self, version: FilterPresetVersionRecord
    ) -> FilterPresetVersionRecord: ...
    async def get_version(self, version_id: str) -> FilterPresetVersionRecord | None: ...
    async def find_version(
        self, *, definition_id: str, version_number: int
    ) -> FilterPresetVersionRecord | None: ...
    async def latest_version(
        self, definition_id: str
    ) -> FilterPresetVersionRecord | None: ...
    async def list_versions(
        self, definition_id: str
    ) -> tuple[FilterPresetVersionRecord, ...]: ...
    async def mark_version_referenced(self, version_id: str) -> None: ...
    async def list_for_scope(
        self, *, scopes: QueryScopeFilter, page: Page
    ) -> Paged[FilterPresetRecord]: ...


@runtime_checkable
class RankingDefinitionRepository(Protocol):
    """Saved ranking configurations. Structurally parallel to saved filters and
    deliberately a separate port: a ranking is never reachable through a filter."""

    async def add(self, definition: RankingDefinitionRecord) -> RankingDefinitionRecord: ...
    async def get(self, definition_id: str) -> RankingDefinitionRecord | None: ...
    async def save(self, definition: RankingDefinitionRecord) -> RankingDefinitionRecord: ...
    async def add_version(self, version: RankingVersionRecord) -> RankingVersionRecord: ...
    async def get_version(self, version_id: str) -> RankingVersionRecord | None: ...
    async def find_version(
        self, *, definition_id: str, version_number: int
    ) -> RankingVersionRecord | None: ...
    async def latest_version(self, definition_id: str) -> RankingVersionRecord | None: ...
    async def list_versions(
        self, definition_id: str
    ) -> tuple[RankingVersionRecord, ...]: ...
    async def mark_version_referenced(self, version_id: str) -> None: ...
    async def list_for_scope(
        self, *, scopes: QueryScopeFilter, page: Page
    ) -> Paged[RankingDefinitionRecord]: ...


@runtime_checkable
class RankingPresetRepository(Protocol):
    async def add(self, preset: RankingPresetRecord) -> RankingPresetRecord: ...
    async def get(self, preset_id: str) -> RankingPresetRecord | None: ...
    async def save(self, preset: RankingPresetRecord) -> RankingPresetRecord: ...
    async def add_version(
        self, version: RankingPresetVersionRecord
    ) -> RankingPresetVersionRecord: ...
    async def get_version(self, version_id: str) -> RankingPresetVersionRecord | None: ...
    async def find_version(
        self, *, definition_id: str, version_number: int
    ) -> RankingPresetVersionRecord | None: ...
    async def latest_version(
        self, definition_id: str
    ) -> RankingPresetVersionRecord | None: ...
    async def list_versions(
        self, definition_id: str
    ) -> tuple[RankingPresetVersionRecord, ...]: ...
    async def mark_version_referenced(self, version_id: str) -> None: ...
    async def list_for_scope(
        self, *, scopes: QueryScopeFilter, page: Page
    ) -> Paged[RankingPresetRecord]: ...


@runtime_checkable
class QueryExecutionRepository(Protocol):
    """Append-only execution records. There is no ``save``: an execution is a
    historical fact, and a fact that can be edited is not provenance."""

    async def add_filter_execution(
        self, execution: FilterExecutionRecord
    ) -> FilterExecutionRecord: ...
    async def add_ranking_execution(
        self, execution: RankingExecutionRecord
    ) -> RankingExecutionRecord: ...
    async def get_filter_execution(
        self, execution_id: str
    ) -> FilterExecutionRecord | None: ...
    async def get_ranking_execution_for_filter(
        self, filter_execution_id: str
    ) -> RankingExecutionRecord | None: ...
    async def list_filter_executions(
        self,
        *,
        workspace_ids: tuple[str, ...],
        page: Page,
        result_set_id: str | None = None,
    ) -> Paged[FilterExecutionRecord]: ...


@runtime_checkable
class SavedViewRepository(Protocol):
    async def add(self, view: SavedViewRecord) -> SavedViewRecord: ...
    async def get(self, view_id: str) -> SavedViewRecord | None: ...
    async def save(self, view: SavedViewRecord) -> SavedViewRecord: ...
    async def list_for_scope(
        self, *, scopes: QueryScopeFilter, page: Page
    ) -> Paged[SavedViewRecord]: ...


class EvidenceSourceRepository(Protocol):
    """Registered evidence source versions.

    Backed by the existing scientific resource registry: an evidence source
    version is a ``scientific_resources`` row of kind ``evidence_resource``. No
    parallel registry exists, and no external database is privileged.
    """

    async def add(self, source: EvidenceSourceRecord) -> EvidenceSourceRecord: ...
    async def get(self, source_id: str) -> EvidenceSourceRecord | None: ...
    async def get_by_version(
        self, *, source_key: str, version: str
    ) -> EvidenceSourceRecord | None: ...
    async def save(self, source: EvidenceSourceRecord) -> EvidenceSourceRecord: ...
    async def list_sources(
        self,
        *,
        page: Page,
        category: EvidenceSourceCategory | None = None,
        source_key: str | None = None,
        usable_only: bool = False,
    ) -> Paged[EvidenceSourceRecord]: ...


class EvidenceRecordRepository(Protocol):
    """Evidence records, stored as rows of the one evidence table.

    ``save_lifecycle`` is deliberately the only mutation: state and supersession
    pointers change, delivered content never does.
    """

    async def add(self, record: EvidenceRecord) -> EvidenceRecord: ...
    async def add_many(self, records: tuple[EvidenceRecord, ...]) -> None: ...
    async def get(self, evidence_id: str) -> EvidenceRecord | None: ...
    async def get_by_digest(
        self, *, variant_id: str, source_key: str, payload_digest: str
    ) -> EvidenceRecord | None: ...
    async def current_for_lineage(
        self, *, variant_id: str, source_key: str, evidence_key: str
    ) -> EvidenceRecord | None: ...
    async def save_lifecycle(self, record: EvidenceRecord) -> EvidenceRecord: ...
    async def list_records(
        self,
        *,
        page: Page,
        workspace_ids: frozenset[str] | None = None,
        variant_id: str | None = None,
        project_id: str | None = None,
        source_key: str | None = None,
        category: EvidenceCategory | None = None,
        state: EvidenceRecordState | None = None,
        include_superseded: bool = False,
    ) -> Paged[EvidenceRecord]: ...
    async def list_for_variant(
        self,
        *,
        variant_id: str,
        workspace_ids: frozenset[str] | None = None,
        include_superseded: bool = False,
        limit: int = 500,
    ) -> tuple[EvidenceRecord, ...]: ...


class EvidenceIngestionRepository(Protocol):
    """Evidence ingestion batches and their validation findings."""

    async def add(self, batch: EvidenceIngestionBatch) -> EvidenceIngestionBatch: ...
    async def get(self, batch_id: str) -> EvidenceIngestionBatch | None: ...
    async def get_by_payload_digest(
        self, *, source_key: str, payload_digest: str
    ) -> EvidenceIngestionBatch | None: ...
    async def save(self, batch: EvidenceIngestionBatch) -> EvidenceIngestionBatch: ...
    async def list_batches(
        self,
        *,
        page: Page,
        workspace_ids: frozenset[str] | None = None,
        source_key: str | None = None,
        state: EvidenceIngestionState | None = None,
    ) -> Paged[EvidenceIngestionBatch]: ...
    async def add_findings(
        self, findings: tuple[EvidenceValidationFinding, ...]
    ) -> None: ...
    async def list_findings(
        self, *, ingestion_batch_id: str, page: Page
    ) -> Paged[EvidenceValidationFinding]: ...


class AnnotationResourceRepository(Protocol):
    """Registered annotation resource versions.

    Backed by the existing scientific resource registry: an annotation resource
    version is a ``scientific_resources`` row of kind ``annotation_resource``
    plus the fields it declares. No parallel registry exists.
    """

    async def add(self, resource: AnnotationResourceRecord) -> AnnotationResourceRecord: ...
    async def get(self, resource_id: str) -> AnnotationResourceRecord | None: ...
    async def get_by_version(
        self, *, resource_key: str, version: str
    ) -> AnnotationResourceRecord | None: ...
    async def save(self, resource: AnnotationResourceRecord) -> AnnotationResourceRecord: ...
    async def list_resources(
        self,
        *,
        page: Page,
        category: AnnotationResourceCategory | None = None,
        resource_key: str | None = None,
        usable_only: bool = False,
    ) -> Paged[AnnotationResourceRecord]: ...
    #: Every resource version whose fields may appear in the field dictionary.
    async def list_field_sources(self) -> tuple[AnnotationResourceRecord, ...]: ...


class AnnotationProfileRepository(Protocol):
    async def add(self, profile: AnnotationProfileRecord) -> AnnotationProfileRecord: ...
    async def get(self, profile_id: str) -> AnnotationProfileRecord | None: ...
    async def get_by_name(self, name: str) -> AnnotationProfileRecord | None: ...
    async def save(self, profile: AnnotationProfileRecord) -> AnnotationProfileRecord: ...
    async def list_profiles(
        self, *, page: Page, offered_only: bool = False
    ) -> Paged[AnnotationProfileRecord]: ...
    #: Append-only: an existing version is never rewritten.
    async def add_version(
        self, version: AnnotationProfileVersionRecord
    ) -> AnnotationProfileVersionRecord: ...
    async def get_version(
        self, version_id: str
    ) -> AnnotationProfileVersionRecord | None: ...
    async def get_version_number(
        self, *, profile_id: str, version_number: int
    ) -> AnnotationProfileVersionRecord | None: ...
    async def mark_version_referenced(self, version_id: str) -> None: ...
    async def list_versions(
        self, *, profile_id: str, page: Page
    ) -> Paged[AnnotationProfileVersionRecord]: ...


class AnnotationRunRepository(Protocol):
    async def add(self, run: AnnotationRunRecord) -> AnnotationRunRecord: ...
    async def get(self, run_id: str) -> AnnotationRunRecord | None: ...
    async def save(self, run: AnnotationRunRecord) -> AnnotationRunRecord: ...
    async def get_by_idempotency_key(
        self, *, workspace_id: str, idempotency_key: str
    ) -> AnnotationRunRecord | None: ...
    async def list_runs(
        self,
        *,
        page: Page,
        workspace_ids: frozenset[str] | None = None,
        project_id: str | None = None,
        result_set_id: str | None = None,
        state: AnnotationRunState | None = None,
    ) -> Paged[AnnotationRunRecord]: ...


class AnnotationResultRepository(Protocol):
    async def add(
        self, result: AnnotationResultVersionRecord
    ) -> AnnotationResultVersionRecord: ...
    async def get(self, result_id: str) -> AnnotationResultVersionRecord | None: ...
    async def save(
        self, result: AnnotationResultVersionRecord
    ) -> AnnotationResultVersionRecord: ...
    async def get_by_payload_digest(
        self, *, annotation_run_id: str, payload_digest: str
    ) -> AnnotationResultVersionRecord | None: ...
    #: Highest version so far for one annotated surface and resource key, which is
    #: what makes an updated resource produce a new version rather than an
    #: overwrite.
    async def latest_version_number(
        self,
        *,
        resource_key: str,
        result_set_id: str | None = None,
        dataset_version_id: str | None = None,
    ) -> int: ...
    async def latest_for_surface(
        self,
        *,
        resource_key: str,
        result_set_id: str | None = None,
        dataset_version_id: str | None = None,
    ) -> AnnotationResultVersionRecord | None: ...
    async def list_results(
        self,
        *,
        page: Page,
        workspace_ids: frozenset[str] | None = None,
        result_set_id: str | None = None,
        annotation_run_id: str | None = None,
    ) -> Paged[AnnotationResultVersionRecord]: ...
    async def add_findings(
        self, findings: tuple[AnnotationValidationFinding, ...]
    ) -> None: ...
    async def list_findings(
        self, *, annotation_run_id: str, page: Page
    ) -> Paged[AnnotationValidationFinding]: ...


class RulesetRepository(Protocol):
    """Registered interpretation ruleset versions and their declared content.

    ``save_lifecycle`` is the only mutation. A registered version's criteria and
    combination rules are written once: a corrected guideline, a modified criterion
    strength or a new gene/disease specification is a new version, never an edit,
    which is what keeps a historical classification explainable.
    """

    async def add(self, ruleset: RulesetRecord) -> RulesetRecord: ...
    async def get(self, ruleset_id: str) -> RulesetRecord | None: ...
    async def get_by_version(
        self, *, ruleset_key: str, version: str
    ) -> RulesetRecord | None: ...
    async def save_lifecycle(self, ruleset: RulesetRecord) -> RulesetRecord: ...
    async def list_rulesets(
        self,
        *,
        page: Page,
        ruleset_key: str | None = None,
        gene_symbol: str | None = None,
        usable_only: bool = False,
    ) -> Paged[RulesetRecord]: ...


class ClassificationEvaluationRepository(Protocol):
    """Requested automated evaluations and the suggestions they produced.

    ``add_classification`` never overwrites: a newer suggestion supersedes the
    previous one, and the earlier row stays readable exactly as the engine
    produced it.
    """

    async def add(
        self, evaluation: ClassificationEvaluationRecord
    ) -> ClassificationEvaluationRecord: ...
    async def get(self, evaluation_id: str) -> ClassificationEvaluationRecord | None: ...
    async def get_by_idempotency_key(
        self, *, workspace_id: str, idempotency_key: str
    ) -> ClassificationEvaluationRecord | None: ...
    async def save(
        self, evaluation: ClassificationEvaluationRecord
    ) -> ClassificationEvaluationRecord: ...
    async def list_evaluations(
        self,
        *,
        page: Page,
        workspace_ids: frozenset[str] | None = None,
        variant_id: str | None = None,
        ruleset_id: str | None = None,
        project_id: str | None = None,
        state: ClassificationEvaluationState | None = None,
    ) -> Paged[ClassificationEvaluationRecord]: ...
    async def add_classification(
        self, classification: AutomatedClassificationRecord
    ) -> AutomatedClassificationRecord: ...
    async def get_classification(
        self, classification_id: str
    ) -> AutomatedClassificationRecord | None: ...
    async def mark_superseded(
        self, *, classification_id: str, superseded_by_id: str
    ) -> None: ...
    async def current_classification(
        self, *, variant_id: str, ruleset_id: str, condition_identifier: str | None = None
    ) -> AutomatedClassificationRecord | None: ...
    async def classification_history(
        self,
        *,
        variant_id: str,
        workspace_ids: frozenset[str] | None = None,
        ruleset_id: str | None = None,
        limit: int = 100,
    ) -> tuple[AutomatedClassificationRecord, ...]: ...
    async def add_criterion_evaluations(
        self, evaluations: tuple[CriterionEvaluationRecord, ...]
    ) -> None: ...
    async def list_criterion_evaluations(
        self, *, classification_evaluation_id: str
    ) -> tuple[CriterionEvaluationRecord, ...]: ...


class RulesetBenchmarkRepository(Protocol):
    """Controlled benchmark cases and the runs executed against them."""

    async def add_case(self, case: BenchmarkCaseRecord) -> BenchmarkCaseRecord: ...
    async def get_case(self, case_id: str) -> BenchmarkCaseRecord | None: ...
    async def get_case_by_key(
        self, *, ruleset_id: str, case_key: str
    ) -> BenchmarkCaseRecord | None: ...
    async def list_cases(
        self,
        *,
        ruleset_id: str,
        validation_kind: BenchmarkValidationKind | None = None,
        active_only: bool = True,
    ) -> tuple[BenchmarkCaseRecord, ...]: ...
    async def add_run(self, run: BenchmarkRunRecord) -> BenchmarkRunRecord: ...
    async def get_run(self, run_id: str) -> BenchmarkRunRecord | None: ...
    async def list_runs(
        self, *, ruleset_id: str, page: Page
    ) -> Paged[BenchmarkRunRecord]: ...


class InterpretationRepository(Protocol):
    """Interpretations and their immutable versions.

    ``add_version`` only ever appends. There is no ``update_version``: a correction
    is a new version that names the one it supersedes, so a report citing an earlier
    version keeps meaning what it meant.
    """

    async def add(self, record: InterpretationRecord) -> InterpretationRecord: ...
    async def get(self, interpretation_id: str) -> InterpretationRecord | None: ...
    async def find_for_context(
        self,
        *,
        project_id: str,
        variant_id: str,
        condition_identifier: str | None = None,
        sample_id: str | None = None,
    ) -> InterpretationRecord | None: ...
    async def save(self, record: InterpretationRecord) -> InterpretationRecord: ...
    async def list_interpretations(
        self,
        *,
        page: Page,
        workspace_ids: frozenset[str] | None = None,
        project_id: str | None = None,
        variant_id: str | None = None,
        state: InterpretationState | None = None,
        review_state: ReviewState | None = None,
        reviewer_user_id: str | None = None,
    ) -> Paged[InterpretationRecord]: ...
    async def add_version(
        self, version: InterpretationVersionRecord
    ) -> InterpretationVersionRecord: ...
    async def get_version(
        self, version_id: str
    ) -> InterpretationVersionRecord | None: ...
    async def finalize_version(
        self, version: InterpretationVersionRecord
    ) -> InterpretationVersionRecord: ...
    async def list_versions(
        self, *, interpretation_id: str, limit: int = 100
    ) -> tuple[InterpretationVersionRecord, ...]: ...


class ReviewRepository(Protocol):
    """Reviewer assignments and the append-only record of their decisions."""

    async def add_assignment(
        self, assignment: ReviewAssignmentRecord
    ) -> ReviewAssignmentRecord: ...
    async def get_assignment(
        self, assignment_id: str
    ) -> ReviewAssignmentRecord | None: ...
    async def find_assignment(
        self, *, interpretation_id: str, reviewer_user_id: str, review_round: int
    ) -> ReviewAssignmentRecord | None: ...
    async def save_assignment(
        self, assignment: ReviewAssignmentRecord
    ) -> ReviewAssignmentRecord: ...
    async def list_assignments(
        self, *, interpretation_id: str, review_round: int | None = None
    ) -> tuple[ReviewAssignmentRecord, ...]: ...
    async def add_decision(
        self, decision: ReviewDecisionRecord
    ) -> ReviewDecisionRecord: ...
    async def get_decision(self, decision_id: str) -> ReviewDecisionRecord | None: ...
    async def list_decisions(
        self,
        *,
        interpretation_id: str,
        review_round: int | None = None,
        interpretation_version_id: str | None = None,
    ) -> tuple[ReviewDecisionRecord, ...]: ...


@runtime_checkable
class TransactionalRepositories(Protocol):
    """Every repository bound to one transaction.

    Use cases receive this, so a single business operation writes state, audit,
    security events and domain events atomically — an audit record can never
    survive a rolled-back change, and a change can never escape unaudited.
    """

    users: UserRepository
    credentials: CredentialsRepository
    sessions: SessionRepository
    credential_tokens: CredentialTokenRepository
    workspaces: WorkspaceRepository
    organizations: OrganizationRepository
    organization_memberships: OrganizationMembershipRepository
    organization_invitations: OrganizationInvitationRepository
    projects: ProjectRepository
    project_memberships: ProjectMembershipRepository
    platform_roles: PlatformRoleRepository
    datasets: DatasetRepository
    dataset_versions: DatasetVersionRepository
    file_artifacts: FileArtifactRepository
    upload_sessions: UploadSessionRepository
    import_sessions: ImportSessionRepository
    column_mappings: ColumnMappingRepository
    validation_runs: ValidationRunRepository
    validation_issues: ValidationIssueRepository
    analyses: AnalysisRepository
    analysis_configurations: AnalysisConfigurationRepository
    analysis_executions: AnalysisExecutionRepository
    schedules: ScheduleRepository
    compute_nodes: ComputeNodeRepository
    scientific_executions: ScientificExecutionRepository
    variants: VariantRepository
    variant_representations: VariantRepresentationRepository
    variant_source_representations: VariantSourceRepresentationRepository
    variant_identifiers: VariantIdentifierRepository
    variant_contexts: VariantContextRepository
    dataset_version_variants: DatasetVersionVariantRepository
    samples: SampleRepository
    genes_transcripts: GeneTranscriptRepository
    result_sets: ResultSetRepository
    result_artifacts: ResultArtifactRepository
    result_ingestions: ResultIngestionRepository
    filter_definitions: FilterDefinitionRepository
    filter_presets: FilterPresetRepository
    ranking_definitions: RankingDefinitionRepository
    ranking_presets: RankingPresetRepository
    query_executions: QueryExecutionRepository
    saved_views: SavedViewRepository
    annotation_resources: AnnotationResourceRepository
    annotation_profiles: AnnotationProfileRepository
    annotation_runs: AnnotationRunRepository
    annotation_results: AnnotationResultRepository
    evidence_sources: EvidenceSourceRepository
    evidence_records: EvidenceRecordRepository
    evidence_ingestions: EvidenceIngestionRepository
    interpretations: InterpretationRepository
    reviews: ReviewRepository
    rulesets: RulesetRepository
    classification_evaluations: ClassificationEvaluationRepository
    ruleset_benchmarks: RulesetBenchmarkRepository
    jobs: JobRepository
    audit: AuditRepository
    security_events: SecurityEventRepository
    outbox: OutboxRepository
    notifications: NotificationRepository


@runtime_checkable
class UnitOfWorkFactory(Protocol):
    """Opens a transaction and yields the repository set bound to it."""

    def begin(self) -> Any: ...


__all__ = [
    "AnalysisConfigurationRepository",
    "AnalysisExecutionRepository",
    "AnalysisRepository",
    "AuditRecord",
    "AuditRepository",
    "ClassificationEvaluationRepository",
    "ColumnMappingRepository",
    "ComputeNodeRepository",
    "CredentialTokenRepository",
    "CredentialsRepository",
    "DatasetRepository",
    "DatasetVersionRepository",
    "DatasetVersionVariantRepository",
    "EvidenceIngestionRepository",
    "EvidenceRecordRepository",
    "EvidenceSourceRepository",
    "FileArtifactRepository",
    "GeneTranscriptRepository",
    "ImportSessionRepository",
    "InterpretationRepository",
    "JobRepository",
    "NotificationRepository",
    "OrganizationInvitationRepository",
    "OrganizationMembershipRepository",
    "OrganizationRepository",
    "OutboxRepository",
    "Page",
    "Paged",
    "PlatformRoleRepository",
    "ProjectMembershipRepository",
    "ProjectRepository",
    "ResultArtifactRepository",
    "ResultIngestionRepository",
    "ResultSetRepository",
    "ReviewRepository",
    "RulesetBenchmarkRepository",
    "RulesetRepository",
    "SampleRepository",
    "ScheduleRepository",
    "ScientificExecutionRepository",
    "SecurityEventRepository",
    "SecurityRecord",
    "SessionRepository",
    "TransactionalRepositories",
    "UnitOfWorkFactory",
    "UploadSessionRepository",
    "UserRepository",
    "ValidationIssueRepository",
    "ValidationRunRepository",
    "VariantContextRepository",
    "VariantIdentifierRepository",
    "VariantRepository",
    "VariantRepresentationRepository",
    "VariantSourceRepresentationRepository",
    "WorkspaceRepository",
]
