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
from app.domain.identity.entities import (
    Credentials,
    CredentialToken,
    Session,
    UserAccount,
)
from app.domain.organization.entities import (
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
)
from app.domain.project.entities import Project, ProjectMembership
from app.domain.value_objects.enums import (
    ActorType,
    AnalysisState,
    AuditChannel,
    AuditOutcome,
    CredentialTokenKind,
    DatasetState,
    ExecutionState,
    InvitationState,
    JobErrorClass,
    JobKind,
    JobState,
    MembershipState,
    NodeClass,
    OrganizationState,
    PlatformRole,
    ScheduleState,
    ScheduleTriggerOutcome,
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
    "ColumnMappingRepository",
    "ComputeNodeRepository",
    "CredentialTokenRepository",
    "CredentialsRepository",
    "DatasetRepository",
    "DatasetVersionRepository",
    "FileArtifactRepository",
    "ImportSessionRepository",
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
    "WorkspaceRepository",
]
