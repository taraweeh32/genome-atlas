"""The effective authorization context.

Resolved by the application layer from the *authenticated* identity plus the
resource scope being addressed — never from anything the client asserts. A
client may name a workspace, an organization or a project; the grants in this
object are the ones the database actually contains for that identity.

Nothing here is optional convenience state: an empty grant map means "no
access", which is the correct answer when resolution found nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.authorization.permissions import Permission
from app.domain.authorization.roles import (
    ORGANIZATION_ROLE_PERMISSIONS,
    ORGANIZATION_ROLE_PROJECT_PERMISSIONS,
    PERSONAL_WORKSPACE_PERMISSIONS,
    PROJECT_ROLE_PERMISSIONS,
    platform_permissions,
)
from app.domain.value_objects.enums import (
    AccountState,
    ActorType,
    MembershipState,
    OrganizationRole,
    OrganizationState,
    PlatformRole,
    ProjectRole,
    ProjectState,
    WorkspaceKind,
)


@dataclass(frozen=True, slots=True)
class OrganizationGrant:
    """One organization membership as it actually exists in the database."""

    organization_id: str
    role: OrganizationRole
    membership_state: MembershipState
    organization_state: OrganizationState
    workspace_id: str | None = None

    @property
    def is_usable(self) -> bool:
        """Membership must be active *and* the organization must be usable.

        A suspended or deactivated organization confers no capability, so its
        members lose access without any membership row being destroyed.
        """
        return self.membership_state is MembershipState.ACTIVE and self.organization_state in (
            OrganizationState.ACTIVE,
            OrganizationState.APPROVED,
        )


@dataclass(frozen=True, slots=True)
class WorkspaceGrant:
    workspace_id: str
    kind: WorkspaceKind
    organization_id: str | None = None
    owner_user_id: str | None = None
    usable: bool = True


@dataclass(frozen=True, slots=True)
class ProjectGrant:
    project_id: str
    workspace_id: str
    role: ProjectRole
    membership_state: MembershipState
    project_state: ProjectState

    @property
    def is_usable(self) -> bool:
        return self.membership_state is MembershipState.ACTIVE


@dataclass(frozen=True, slots=True)
class ActorContext:
    """Authenticated identity plus every grant resolved for this request."""

    actor_id: str
    actor_type: ActorType = ActorType.USER
    account_state: AccountState = AccountState.ACTIVE
    session_id: str | None = None
    platform_roles: frozenset[PlatformRole] = frozenset()
    organizations: dict[str, OrganizationGrant] = field(default_factory=dict)
    workspaces: dict[str, WorkspaceGrant] = field(default_factory=dict)
    projects: dict[str, ProjectGrant] = field(default_factory=dict)
    #: True only when the session actually completed a second factor. Package 3
    #: never sets this from client input; the MFA package will set it from a
    #: real verification. It is *not* a bypass flag.
    mfa_satisfied: bool = False
    #: Timestamp of the most recent successful credential proof on the session,
    #: used by re-authentication requirements for sensitive operations.
    reauthenticated_at_epoch: float | None = None

    # ------------------------------------------------------------------ #
    # Derived capability sets                                            #
    # ------------------------------------------------------------------ #

    @property
    def account_is_usable(self) -> bool:
        return self.account_state is AccountState.ACTIVE

    @property
    def is_platform_administrator(self) -> bool:
        return PlatformRole.PLATFORM_ADMINISTRATOR in self.platform_roles

    def platform_capabilities(self) -> frozenset[Permission]:
        if not self.account_is_usable:
            return frozenset()
        return platform_permissions(self.platform_roles)

    def organization_capabilities(self, organization_id: str) -> frozenset[Permission]:
        if not self.account_is_usable:
            return frozenset()
        granted: frozenset[Permission] = frozenset()
        grant = self.organizations.get(organization_id)
        if grant is not None and grant.is_usable:
            granted |= ORGANIZATION_ROLE_PERMISSIONS.get(grant.role, frozenset())
        # A platform administrator may read any organization for governance, but
        # never inherits organization-internal administration.
        if self.is_platform_administrator:
            granted |= {Permission.ORGANIZATION_READ, Permission.ORGANIZATION_MEMBER_READ}
        return granted

    def workspace_capabilities(self, workspace_id: str) -> frozenset[Permission]:
        if not self.account_is_usable:
            return frozenset()
        grant = self.workspaces.get(workspace_id)
        if grant is None or not grant.usable:
            return frozenset()
        if grant.kind is WorkspaceKind.PERSONAL:
            # A personal workspace is private: only its owner has capability,
            # regardless of any organization the owner belongs to.
            if grant.owner_user_id == self.actor_id:
                return PERSONAL_WORKSPACE_PERMISSIONS
            return frozenset()
        if grant.organization_id is None:
            return frozenset()
        organization = self.organizations.get(grant.organization_id)
        if organization is None or not organization.is_usable:
            return frozenset()
        return frozenset(
            permission
            for permission in ORGANIZATION_ROLE_PERMISSIONS.get(organization.role, frozenset())
            if permission.value.startswith("workspace.")
        )

    def project_capabilities(self, project_id: str) -> frozenset[Permission]:
        if not self.account_is_usable:
            return frozenset()
        grant = self.projects.get(project_id)
        granted: frozenset[Permission] = frozenset()
        if grant is not None and grant.is_usable:
            granted |= PROJECT_ROLE_PERMISSIONS.get(grant.role, frozenset())
            if grant.project_state in (ProjectState.ARCHIVED, ProjectState.CLOSED):
                # An archived project is readable and reopenable; it is not
                # writable, and no scientific work may proceed inside it.
                granted = frozenset(
                    permission
                    for permission in granted
                    if permission
                    in {
                        Permission.PROJECT_READ,
                        Permission.PROJECT_MEMBER_READ,
                        Permission.PROJECT_DATA_READ,
                        Permission.PROJECT_REOPEN,
                    }
                )
        # Organization administration reach over projects in its own workspace.
        workspace = self.workspaces.get(grant.workspace_id) if grant else None
        if workspace is not None and workspace.organization_id:
            organization = self.organizations.get(workspace.organization_id)
            if organization is not None and organization.is_usable:
                granted |= ORGANIZATION_ROLE_PROJECT_PERMISSIONS.get(organization.role, frozenset())
        return granted

    def organization_role(self, organization_id: str) -> OrganizationRole | None:
        grant = self.organizations.get(organization_id)
        return grant.role if grant and grant.is_usable else None

    def project_role(self, project_id: str) -> ProjectRole | None:
        grant = self.projects.get(project_id)
        return grant.role if grant and grant.is_usable else None

    def usable_organization_ids(self) -> frozenset[str]:
        return frozenset(
            identifier for identifier, grant in self.organizations.items() if grant.is_usable
        )


__all__ = [
    "ActorContext",
    "OrganizationGrant",
    "ProjectGrant",
    "WorkspaceGrant",
]
