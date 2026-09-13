"""In-memory implementations of the repository ports.

These exist because the repository *ports* are protocols with no SQL in them:
use cases can therefore be exercised for real — authorization, lifecycle,
tenant isolation, concurrency — without PostgreSQL. They are test doubles for
persistence only. They are never a substitute for the integration tests that run
the SQLAlchemy repositories against a live database (marked ``integration``).

Optimistic concurrency is modelled faithfully: a save whose version does not
match the stored version raises ``ConcurrencyConflictError``, exactly as the SQL
repositories do.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from app.application.repositories import (
    AuditRecord,
    Page,
    Paged,
    SecurityRecord,
)
from app.domain.errors import ConcurrencyConflictError
from app.domain.events import DomainEvent
from app.domain.identity.entities import CredentialToken, Credentials, Session, UserAccount
from app.domain.organization.entities import (
    Organization,
    OrganizationInvitation,
    OrganizationMembership,
)
from app.domain.project.entities import Project, ProjectMembership
from app.domain.value_objects.enums import (
    CredentialTokenKind,
    CredentialTokenState,
    InvitationState,
    MembershipState,
    OrganizationState,
    PlatformRole,
    SessionState,
)
from app.domain.workspace.entities import Workspace
from tests.support.analysis_memory import (
    MemoryAnalyses,
    MemoryAnalysisConfigurations,
    MemoryAnalysisExecutions,
    MemoryComputeNodes,
    MemoryJobQueue,
    MemorySchedules,
    MemoryScientificExecutions,
)
from tests.support.data_memory import (
    MemoryColumnMappings,
    MemoryDatasets,
    MemoryDatasetVersions,
    MemoryFileArtifacts,
    MemoryImportSessions,
    MemoryUploadSessions,
    MemoryValidationIssues,
    MemoryValidationRuns,
)


def _paged(items: list, page: Page) -> Paged:
    window = items[page.offset : page.offset + page.size]
    return Paged(items=tuple(window), total=len(items), page=page)


def _bump(entity, expected_version: int):  # noqa: ANN001, ANN202
    if entity.version != expected_version:
        raise ConcurrencyConflictError(
            f"{type(entity).__name__.lower()} {entity.id} was modified concurrently"
        )
    return replace(entity, version=entity.version + 1)


# --------------------------------------------------------------------- #
# Identity                                                              #
# --------------------------------------------------------------------- #


@dataclass
class MemoryUsers:
    rows: dict[str, UserAccount] = field(default_factory=dict)

    async def get(self, user_id: str) -> UserAccount | None:
        return self.rows.get(user_id)

    async def get_by_email(self, email_normalized: str) -> UserAccount | None:
        for account in self.rows.values():
            if account.email_normalized == email_normalized:
                return account
        return None

    async def add(self, account: UserAccount) -> UserAccount:
        self.rows[account.id] = account
        return account

    async def save(self, account: UserAccount) -> UserAccount:
        stored = self.rows[account.id]
        if stored.version != account.version:
            raise ConcurrencyConflictError("user", account.id)
        updated = replace(account, version=account.version + 1)
        self.rows[account.id] = updated
        return updated

    async def set_personal_workspace(self, user_id: str, workspace_id: str) -> None:
        account = self.rows[user_id]
        self.rows[user_id] = replace(account, personal_workspace_id=workspace_id)

    async def touch_activity(self, user_id: str, moment: datetime) -> None:
        account = self.rows.get(user_id)
        if account is not None:
            self.rows[user_id] = replace(account, last_activity_at=moment)

    async def list_accounts(self, *, page: Page, query: str | None = None) -> Paged[UserAccount]:
        items = sorted(self.rows.values(), key=lambda a: a.email_normalized)
        if query:
            needle = query.strip().lower()
            items = [
                a
                for a in items
                if needle in a.email_normalized or needle in a.display_name.lower()
            ]
        return _paged(items, page)


@dataclass
class MemoryCredentials:
    rows: dict[str, Credentials] = field(default_factory=dict)

    async def get(self, user_id: str) -> Credentials | None:
        return self.rows.get(user_id)

    async def create(self, credentials: Credentials) -> Credentials:
        self.rows[credentials.user_id] = credentials
        return credentials

    async def replace_password(
        self, user_id: str, *, password_hash: str, algorithm: str, moment: datetime
    ) -> None:
        current = self.rows[user_id]
        self.rows[user_id] = replace(
            current,
            password_hash=password_hash,
            password_algorithm=algorithm,
            password_updated_at=moment,
            failed_attempt_count=0,
            locked_until=None,
        )

    async def register_failure(
        self, user_id: str, *, moment: datetime, lock_until: datetime | None
    ) -> int:
        current = self.rows[user_id]
        count = current.failed_attempt_count + 1
        self.rows[user_id] = replace(
            current, failed_attempt_count=count, locked_until=lock_until
        )
        return count

    async def register_success(self, user_id: str, *, moment: datetime) -> None:
        current = self.rows[user_id]
        self.rows[user_id] = replace(
            current,
            failed_attempt_count=0,
            locked_until=None,
            last_successful_authentication_at=moment,
        )


@dataclass
class MemorySessions:
    rows: dict[str, Session] = field(default_factory=dict)
    token_hashes: dict[str, str] = field(default_factory=dict)

    async def create(self, session: Session, *, token_hash: str) -> Session:
        self.rows[session.id] = session
        self.token_hashes[token_hash] = session.id
        return session

    async def get_by_token_hash(self, token_hash: str) -> Session | None:
        session_id = self.token_hashes.get(token_hash)
        return self.rows.get(session_id) if session_id else None

    async def touch(
        self, session_id: str, *, last_seen_at: datetime, expires_at: datetime
    ) -> None:
        session = self.rows[session_id]
        self.rows[session_id] = replace(
            session, last_seen_at=last_seen_at, expires_at=expires_at
        )

    async def revoke(self, session_id: str, *, reason: str, moment: datetime) -> None:
        session = self.rows.get(session_id)
        if session is None:
            return
        self.rows[session_id] = replace(
            session, state=SessionState.REVOKED, revoked_at=moment, revocation_reason=reason
        )

    async def revoke_all_for_user(
        self,
        user_id: str,
        *,
        reason: str,
        moment: datetime,
        keep_session_id: str | None = None,
    ) -> int:
        revoked = 0
        for session in list(self.rows.values()):
            if session.user_id != user_id or session.id == keep_session_id:
                continue
            if session.state is not SessionState.ACTIVE:
                continue
            await self.revoke(session.id, reason=reason, moment=moment)
            revoked += 1
        return revoked

    async def list_active_for_user(self, user_id: str) -> tuple[Session, ...]:
        active = [
            s
            for s in self.rows.values()
            if s.user_id == user_id and s.state is SessionState.ACTIVE
        ]
        return tuple(sorted(active, key=lambda s: s.issued_at))


@dataclass
class MemoryCredentialTokens:
    rows: dict[str, CredentialToken] = field(default_factory=dict)
    token_hashes: dict[str, str] = field(default_factory=dict)

    async def create(self, token: CredentialToken, *, token_hash: str) -> CredentialToken:
        self.rows[token.id] = token
        self.token_hashes[token_hash] = token.id
        return token

    async def get_by_token_hash(self, token_hash: str) -> CredentialToken | None:
        token_id = self.token_hashes.get(token_hash)
        return self.rows.get(token_id) if token_id else None

    async def consume(self, token_id: str, *, moment: datetime) -> None:
        token = self.rows[token_id]
        self.rows[token_id] = replace(
            token, state=CredentialTokenState.CONSUMED, consumed_at=moment
        )

    async def invalidate_active(
        self, user_id: str, kind: CredentialTokenKind, *, reason: str, moment: datetime
    ) -> int:
        count = 0
        for token in list(self.rows.values()):
            if token.user_id != user_id or token.kind is not kind:
                continue
            if token.state is not CredentialTokenState.ACTIVE:
                continue
            self.rows[token.id] = replace(token, state=CredentialTokenState.INVALIDATED)
            count += 1
        return count


@dataclass
class MemoryPlatformRoles:
    rows: dict[str, set[PlatformRole]] = field(default_factory=dict)

    async def list_active_for_user(self, user_id: str) -> frozenset[PlatformRole]:
        return frozenset(self.rows.get(user_id, set()))

    async def grant(
        self, user_id: str, role: PlatformRole, *, granted_by: str, moment: datetime
    ) -> None:
        self.rows.setdefault(user_id, set()).add(role)

    async def revoke(self, user_id: str, role: PlatformRole, *, moment: datetime) -> None:
        self.rows.get(user_id, set()).discard(role)


# --------------------------------------------------------------------- #
# Tenancy                                                               #
# --------------------------------------------------------------------- #


@dataclass
class MemoryWorkspaces:
    rows: dict[str, Workspace] = field(default_factory=dict)
    #: Set by ``MemoryRepositories``; organization reach is a membership question.
    memberships: "MemoryOrganizationMemberships | None" = None

    async def add(self, workspace: Workspace) -> Workspace:
        self.rows[workspace.id] = workspace
        return workspace

    async def get(self, workspace_id: str) -> Workspace | None:
        return self.rows.get(workspace_id)

    async def get_personal_for_user(self, user_id: str) -> Workspace | None:
        for workspace in self.rows.values():
            if workspace.is_personal and workspace.owner_user_id == user_id:
                return workspace
        return None

    async def get_for_organization(self, organization_id: str) -> Workspace | None:
        for workspace in self.rows.values():
            if workspace.organization_id == organization_id:
                return workspace
        return None

    async def list_for_user(self, user_id: str) -> tuple[Workspace, ...]:
        """Mirrors the SQL repository: the personal workspace plus the workspace
        of every organization the user is an *active* member of."""
        organization_ids = {
            membership.organization_id
            for membership in (
                self.memberships.rows.values() if self.memberships is not None else ()
            )
            if membership.user_id == user_id and membership.state is MembershipState.ACTIVE
        }
        return tuple(
            workspace
            for workspace in self.rows.values()
            if (workspace.is_personal and workspace.owner_user_id == user_id)
            or (workspace.organization_id in organization_ids)
        )


@dataclass
class MemoryOrganizations:
    rows: dict[str, Organization] = field(default_factory=dict)
    memberships: "MemoryOrganizationMemberships | None" = None

    async def add(self, organization: Organization) -> Organization:
        self.rows[organization.id] = organization
        return organization

    async def get(self, organization_id: str) -> Organization | None:
        return self.rows.get(organization_id)

    async def get_by_slug(self, slug: str) -> Organization | None:
        for organization in self.rows.values():
            if organization.slug == slug:
                return organization
        return None

    async def save(self, organization: Organization) -> Organization:
        stored = self.rows[organization.id]
        updated = _bump(organization, stored.version)
        self.rows[organization.id] = updated
        return updated

    async def list_by_states(
        self, states: tuple[OrganizationState, ...], *, page: Page
    ) -> Paged[Organization]:
        items = [o for o in self.rows.values() if o.state in states]
        return _paged(sorted(items, key=lambda o: o.slug), page)

    async def list_for_user(self, user_id: str, *, page: Page) -> Paged[Organization]:
        assert self.memberships is not None
        ids = {
            m.organization_id
            for m in await self.memberships.list_for_user(user_id)
            if m.state is MembershipState.ACTIVE
        }
        items = [o for o in self.rows.values() if o.id in ids]
        return _paged(sorted(items, key=lambda o: o.slug), page)


@dataclass
class MemoryOrganizationMemberships:
    rows: dict[tuple[str, str], OrganizationMembership] = field(default_factory=dict)

    async def add(self, membership: OrganizationMembership) -> OrganizationMembership:
        self.rows[(membership.organization_id, membership.user_id)] = membership
        return membership

    async def get(self, organization_id: str, user_id: str) -> OrganizationMembership | None:
        return self.rows.get((organization_id, user_id))

    async def save(self, membership: OrganizationMembership) -> OrganizationMembership:
        key = (membership.organization_id, membership.user_id)
        updated = _bump(membership, self.rows[key].version)
        self.rows[key] = updated
        return updated

    async def list_for_user(self, user_id: str) -> tuple[OrganizationMembership, ...]:
        return tuple(m for m in self.rows.values() if m.user_id == user_id)

    async def list_for_organization(
        self,
        organization_id: str,
        *,
        page: Page,
        states: tuple[MembershipState, ...] | None = None,
    ) -> Paged[OrganizationMembership]:
        items = [m for m in self.rows.values() if m.organization_id == organization_id]
        if states:
            items = [m for m in items if m.state in states]
        return _paged(sorted(items, key=lambda m: m.user_id), page)

    async def count_active_with_role(self, organization_id: str, role: str) -> int:
        return sum(
            1
            for m in self.rows.values()
            if m.organization_id == organization_id
            and m.role.value == role
            and m.state is MembershipState.ACTIVE
        )


@dataclass
class MemoryInvitations:
    rows: dict[str, OrganizationInvitation] = field(default_factory=dict)
    token_hashes: dict[str, str] = field(default_factory=dict)

    async def add(
        self, invitation: OrganizationInvitation, *, token_hash: str
    ) -> OrganizationInvitation:
        self.rows[invitation.id] = invitation
        self.token_hashes[token_hash] = invitation.id
        return invitation

    async def get(self, invitation_id: str) -> OrganizationInvitation | None:
        return self.rows.get(invitation_id)

    async def get_by_token_hash(self, token_hash: str) -> OrganizationInvitation | None:
        invitation_id = self.token_hashes.get(token_hash)
        return self.rows.get(invitation_id) if invitation_id else None

    async def get_open_for_email(
        self, organization_id: str, email_normalized: str
    ) -> OrganizationInvitation | None:
        for invitation in self.rows.values():
            if (
                invitation.organization_id == organization_id
                and invitation.invited_email_normalized == email_normalized
                and invitation.state is InvitationState.PENDING
            ):
                return invitation
        return None

    async def save(self, invitation: OrganizationInvitation) -> OrganizationInvitation:
        updated = _bump(invitation, self.rows[invitation.id].version)
        self.rows[invitation.id] = updated
        return updated

    async def list_for_organization(
        self,
        organization_id: str,
        *,
        page: Page,
        states: tuple[InvitationState, ...] | None = None,
    ) -> Paged[OrganizationInvitation]:
        items = [i for i in self.rows.values() if i.organization_id == organization_id]
        if states:
            items = [i for i in items if i.state in states]
        return _paged(sorted(items, key=lambda i: i.invited_email_normalized), page)

    async def list_open_for_email(
        self, email_normalized: str
    ) -> tuple[OrganizationInvitation, ...]:
        return tuple(
            i
            for i in self.rows.values()
            if i.invited_email_normalized == email_normalized
            and i.state is InvitationState.PENDING
        )


@dataclass
class MemoryProjects:
    rows: dict[str, Project] = field(default_factory=dict)

    async def add(self, project: Project) -> Project:
        self.rows[project.id] = project
        return project

    async def get(self, project_id: str) -> Project | None:
        return self.rows.get(project_id)

    async def save(self, project: Project) -> Project:
        updated = _bump(project, self.rows[project.id].version)
        self.rows[project.id] = updated
        return updated

    async def list_for_workspaces(
        self, workspace_ids: tuple[str, ...], *, page: Page
    ) -> Paged[Project]:
        items = [p for p in self.rows.values() if p.workspace_id in workspace_ids]
        return _paged(sorted(items, key=lambda p: p.name), page)


@dataclass
class MemoryProjectMemberships:
    rows: dict[tuple[str, str], ProjectMembership] = field(default_factory=dict)

    async def add(self, membership: ProjectMembership) -> ProjectMembership:
        self.rows[(membership.project_id, membership.user_id)] = membership
        return membership

    async def get(self, project_id: str, user_id: str) -> ProjectMembership | None:
        return self.rows.get((project_id, user_id))

    async def save(self, membership: ProjectMembership) -> ProjectMembership:
        key = (membership.project_id, membership.user_id)
        updated = _bump(membership, self.rows[key].version)
        self.rows[key] = updated
        return updated

    async def list_for_user(self, user_id: str) -> tuple[ProjectMembership, ...]:
        return tuple(m for m in self.rows.values() if m.user_id == user_id)

    async def list_for_project(
        self, project_id: str, *, page: Page
    ) -> Paged[ProjectMembership]:
        items = [m for m in self.rows.values() if m.project_id == project_id]
        return _paged(sorted(items, key=lambda m: m.user_id), page)

    async def count_active_with_role(self, project_id: str, role: str) -> int:
        return sum(
            1
            for m in self.rows.values()
            if m.project_id == project_id
            and m.role.value == role
            and m.state is MembershipState.ACTIVE
        )


# --------------------------------------------------------------------- #
# Governance                                                            #
# --------------------------------------------------------------------- #


@dataclass
class MemoryAudit:
    records: list[AuditRecord] = field(default_factory=list)

    async def record(self, record: AuditRecord) -> None:
        self.records.append(record)


@dataclass
class MemorySecurityEvents:
    records: list[SecurityRecord] = field(default_factory=list)

    async def record(self, record: SecurityRecord) -> None:
        self.records.append(record)


@dataclass
class MemoryOutbox:
    events: list[DomainEvent] = field(default_factory=list)

    async def publish(self, event: DomainEvent) -> None:
        self.events.append(event)


@dataclass
class MemoryNotifications:
    records: list[dict[str, Any]] = field(default_factory=list)

    async def create(self, **kwargs: Any) -> str:
        self.records.append(kwargs)
        return f"ntf_{len(self.records)}"


@dataclass
class MemoryRepositories:
    """The whole repository set, standing in for one transaction."""

    users: MemoryUsers = field(default_factory=MemoryUsers)
    credentials: MemoryCredentials = field(default_factory=MemoryCredentials)
    sessions: MemorySessions = field(default_factory=MemorySessions)
    credential_tokens: MemoryCredentialTokens = field(default_factory=MemoryCredentialTokens)
    workspaces: MemoryWorkspaces = field(default_factory=MemoryWorkspaces)
    organizations: MemoryOrganizations = field(default_factory=MemoryOrganizations)
    organization_memberships: MemoryOrganizationMemberships = field(
        default_factory=MemoryOrganizationMemberships
    )
    organization_invitations: MemoryInvitations = field(default_factory=MemoryInvitations)
    projects: MemoryProjects = field(default_factory=MemoryProjects)
    project_memberships: MemoryProjectMemberships = field(
        default_factory=MemoryProjectMemberships
    )
    platform_roles: MemoryPlatformRoles = field(default_factory=MemoryPlatformRoles)
    audit: MemoryAudit = field(default_factory=MemoryAudit)
    security_events: MemorySecurityEvents = field(default_factory=MemorySecurityEvents)
    outbox: MemoryOutbox = field(default_factory=MemoryOutbox)
    notifications: MemoryNotifications = field(default_factory=MemoryNotifications)
    # Dataset-side repositories live in their own module to keep this one
    # readable; they belong to the same transaction.
    datasets: MemoryDatasets = field(default_factory=MemoryDatasets)
    dataset_versions: MemoryDatasetVersions = field(default_factory=MemoryDatasetVersions)
    file_artifacts: MemoryFileArtifacts = field(default_factory=MemoryFileArtifacts)
    upload_sessions: MemoryUploadSessions = field(default_factory=MemoryUploadSessions)
    import_sessions: MemoryImportSessions = field(default_factory=MemoryImportSessions)
    column_mappings: MemoryColumnMappings = field(default_factory=MemoryColumnMappings)
    validation_runs: MemoryValidationRuns = field(default_factory=MemoryValidationRuns)
    validation_issues: MemoryValidationIssues = field(default_factory=MemoryValidationIssues)
    # Package 5 orchestration repositories, same transaction.
    analyses: MemoryAnalyses = field(default_factory=MemoryAnalyses)
    analysis_configurations: MemoryAnalysisConfigurations = field(
        default_factory=MemoryAnalysisConfigurations
    )
    analysis_executions: MemoryAnalysisExecutions = field(
        default_factory=MemoryAnalysisExecutions
    )
    schedules: MemorySchedules = field(default_factory=MemorySchedules)
    compute_nodes: MemoryComputeNodes = field(default_factory=MemoryComputeNodes)
    scientific_executions: MemoryScientificExecutions = field(
        default_factory=MemoryScientificExecutions
    )
    jobs: MemoryJobQueue = field(default_factory=MemoryJobQueue)

    def __post_init__(self) -> None:
        self.organizations.memberships = self.organization_memberships
        self.workspaces.memberships = self.organization_memberships


class MemoryUnitOfWorkFactory:
    """Hands the same repository set to every transaction, as one database would."""

    def __init__(self, repositories: MemoryRepositories | None = None) -> None:
        self.repositories = repositories or MemoryRepositories()
        self.transactions = 0

    @asynccontextmanager
    async def begin(self):  # noqa: ANN201
        self.transactions += 1
        yield self.repositories


class AllowAllRateLimiter:
    """Rate limiting is exercised in its own tests; here it must not interfere."""

    async def check(self, *args: Any, **kwargs: Any):  # noqa: ANN201
        from app.infrastructure.redis.rate_limiter import RateLimitDecision

        return RateLimitDecision(allowed=True, remaining=99, retry_after_seconds=0)

    async def reset(self, *args: Any, **kwargs: Any) -> None:
        return None


__all__ = [
    "AllowAllRateLimiter",
    "MemoryRepositories",
    "MemoryUnitOfWorkFactory",
]
