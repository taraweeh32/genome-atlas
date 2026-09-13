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

from app.domain.events import DomainEvent
from app.domain.identity.entities import (
    CredentialToken,
    Credentials,
    Session,
    UserAccount,
)
from app.domain.organization.entities import (
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
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
from app.domain.project.entities import Project, ProjectMembership
from app.domain.value_objects.enums import (
    ActorType,
    AuditChannel,
    AuditOutcome,
    CredentialTokenKind,
    DatasetState,
    InvitationState,
    JobKind,
    MembershipState,
    OrganizationState,
    PlatformRole,
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
    """Transactional enqueue of durable work.

    Enqueueing happens inside the business transaction that requested the work,
    so a job can never reference state that was rolled back, and a committed
    state change can never lose its follow-up work. Claiming, leasing, retrying
    and executing jobs is the job-subsystem package; this port only records the
    intent durably.
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
    ) -> str: ...
    async def get(self, job_id: str) -> dict[str, Any] | None: ...


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
    "AuditRecord",
    "AuditRepository",
    "CredentialTokenRepository",
    "ColumnMappingRepository",
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
