"""The permission vocabulary.

A permission is an *operation-specific capability*, never a user type and never
a role name. Roles grant permissions (see ``roles.py``); code checks
permissions, so adding a role never requires touching a call site.

Permissions are grouped by the scope they are evaluated in:

* ``PLATFORM_*`` — platform scope; only a platform role can grant these.
* ``ORGANIZATION_*`` — evaluated against one organization the actor is a member
  of. Never satisfied by membership of a different organization.
* ``WORKSPACE_*`` — evaluated against one workspace (personal or organization).
* ``PROJECT_*`` — evaluated against one project the actor is a member of.
"""

from __future__ import annotations

import enum


class Scope(str, enum.Enum):
    PLATFORM = "platform"
    ORGANIZATION = "organization"
    WORKSPACE = "workspace"
    PROJECT = "project"


class Permission(str, enum.Enum):
    """Stable permission identifiers. The value is what audit records store."""

    # --- platform scope -------------------------------------------------- #
    PLATFORM_ORGANIZATION_REVIEW = "platform.organization.review"
    PLATFORM_ORGANIZATION_APPROVE = "platform.organization.approve"
    PLATFORM_ORGANIZATION_LIFECYCLE = "platform.organization.lifecycle"
    PLATFORM_ORGANIZATION_READ_ANY = "platform.organization.read_any"
    PLATFORM_USER_READ = "platform.user.read"
    PLATFORM_USER_LIFECYCLE = "platform.user.lifecycle"
    PLATFORM_ROLE_MANAGE = "platform.role.manage"
    PLATFORM_AUDIT_READ = "platform.audit.read"
    PLATFORM_SECURITY_POLICY_MANAGE = "platform.security_policy.manage"

    # --- organization scope ---------------------------------------------- #
    ORGANIZATION_READ = "organization.read"
    ORGANIZATION_UPDATE = "organization.update"
    ORGANIZATION_SETTINGS_MANAGE = "organization.settings.manage"
    ORGANIZATION_MEMBER_READ = "organization.member.read"
    ORGANIZATION_MEMBER_INVITE = "organization.member.invite"
    ORGANIZATION_MEMBER_REMOVE = "organization.member.remove"
    ORGANIZATION_MEMBER_ROLE_CHANGE = "organization.member.role_change"
    ORGANIZATION_INVITATION_READ = "organization.invitation.read"
    ORGANIZATION_INVITATION_REVOKE = "organization.invitation.revoke"
    ORGANIZATION_AUDIT_READ = "organization.audit.read"

    # --- workspace scope ------------------------------------------------- #
    WORKSPACE_READ = "workspace.read"
    WORKSPACE_PROJECT_CREATE = "workspace.project.create"

    # --- project scope --------------------------------------------------- #
    PROJECT_READ = "project.read"
    PROJECT_UPDATE = "project.update"
    PROJECT_ARCHIVE = "project.archive"
    PROJECT_REOPEN = "project.reopen"
    PROJECT_MEMBER_READ = "project.member.read"
    PROJECT_MEMBER_MANAGE = "project.member.manage"
    PROJECT_MEMBER_ROLE_CHANGE = "project.member.role_change"
    PROJECT_OWNERSHIP_TRANSFER = "project.ownership.transfer"
    #: Capability foundations later packages build on. Declared here so that no
    #: later module invents a parallel permission vocabulary, and so that
    #: scientific review stays a distinct responsibility from administration.
    PROJECT_DATA_READ = "project.data.read"
    PROJECT_DATA_WRITE = "project.data.write"
    PROJECT_ANALYSIS_EXECUTE = "project.analysis.execute"
    PROJECT_INTERPRETATION_REVIEW = "project.interpretation.review"
    PROJECT_REPORT_FINALIZE = "project.report.finalize"

    @property
    def scope(self) -> Scope:
        prefix = self.value.split(".", 1)[0]
        return Scope(prefix)


#: Operations that must never be reachable through an organization-scoped role,
#: however privileged that role is inside its own organization.
PLATFORM_ONLY_PERMISSIONS: frozenset[Permission] = frozenset(
    permission for permission in Permission if permission.scope is Scope.PLATFORM
)

#: Scientific responsibility. Kept explicit so administration never silently
#: implies clinical/scientific review authority.
SCIENTIFIC_REVIEW_PERMISSIONS: frozenset[Permission] = frozenset(
    {Permission.PROJECT_INTERPRETATION_REVIEW, Permission.PROJECT_REPORT_FINALIZE}
)


__all__ = [
    "PLATFORM_ONLY_PERMISSIONS",
    "SCIENTIFIC_REVIEW_PERMISSIONS",
    "Permission",
    "Scope",
]
