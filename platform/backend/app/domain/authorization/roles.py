"""Role → permission grants.

Three independent role dimensions, deliberately not merged:

* platform role (platform scope only),
* organization role (one organization),
* project role (one project).

A user type is not a role, and a role is not a permission. The same human may
be a platform operator, the owner of one organization, an analyst in one project
and a reviewer in another; each grant is evaluated against its own scope.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.domain.authorization.permissions import Permission
from app.domain.value_objects.enums import OrganizationRole, PlatformRole, ProjectRole

_PLATFORM_ADMINISTRATOR = frozenset(
    {
        Permission.PLATFORM_ORGANIZATION_REVIEW,
        Permission.PLATFORM_ORGANIZATION_APPROVE,
        Permission.PLATFORM_ORGANIZATION_LIFECYCLE,
        Permission.PLATFORM_ORGANIZATION_READ_ANY,
        Permission.PLATFORM_USER_READ,
        Permission.PLATFORM_USER_LIFECYCLE,
        Permission.PLATFORM_ROLE_MANAGE,
        Permission.PLATFORM_AUDIT_READ,
        Permission.PLATFORM_SECURITY_POLICY_MANAGE,
    }
)

#: A platform operator observes; it cannot decide an organization's fate and it
#: cannot change platform security policy.
_PLATFORM_OPERATOR = frozenset(
    {
        Permission.PLATFORM_ORGANIZATION_REVIEW,
        Permission.PLATFORM_ORGANIZATION_READ_ANY,
        Permission.PLATFORM_USER_READ,
        Permission.PLATFORM_AUDIT_READ,
    }
)

PLATFORM_ROLE_PERMISSIONS: Mapping[PlatformRole, frozenset[Permission]] = {
    PlatformRole.PLATFORM_ADMINISTRATOR: _PLATFORM_ADMINISTRATOR,
    PlatformRole.PLATFORM_OPERATOR: _PLATFORM_OPERATOR,
    # An ordinary account holds no platform capability at all.
    PlatformRole.USER: frozenset(),
}

_ORGANIZATION_GUEST = frozenset({Permission.ORGANIZATION_READ})
_ORGANIZATION_MEMBER = _ORGANIZATION_GUEST | {
    Permission.ORGANIZATION_MEMBER_READ,
    Permission.WORKSPACE_READ,
    Permission.WORKSPACE_PROJECT_CREATE,
}
_ORGANIZATION_ADMIN = _ORGANIZATION_MEMBER | {
    Permission.ORGANIZATION_UPDATE,
    Permission.ORGANIZATION_SETTINGS_MANAGE,
    Permission.ORGANIZATION_MEMBER_INVITE,
    Permission.ORGANIZATION_MEMBER_REMOVE,
    Permission.ORGANIZATION_MEMBER_ROLE_CHANGE,
    Permission.ORGANIZATION_INVITATION_READ,
    Permission.ORGANIZATION_INVITATION_REVOKE,
    Permission.ORGANIZATION_AUDIT_READ,
}

ORGANIZATION_ROLE_PERMISSIONS: Mapping[OrganizationRole, frozenset[Permission]] = {
    OrganizationRole.OWNER: _ORGANIZATION_ADMIN,
    OrganizationRole.ADMIN: _ORGANIZATION_ADMIN,
    OrganizationRole.MEMBER: _ORGANIZATION_MEMBER,
    OrganizationRole.BILLING: _ORGANIZATION_GUEST,
    OrganizationRole.GUEST: _ORGANIZATION_GUEST,
}

#: Administrative reach an organization role has over projects *inside its own
#: organization*. Deliberately narrow: an organization administrator may keep
#: the project inventory in order, but membership of the organization never
#: grants project data access, analysis execution or scientific review.
ORGANIZATION_ROLE_PROJECT_PERMISSIONS: Mapping[OrganizationRole, frozenset[Permission]] = {
    OrganizationRole.OWNER: frozenset(
        {
            Permission.PROJECT_READ,
            Permission.PROJECT_UPDATE,
            Permission.PROJECT_ARCHIVE,
            Permission.PROJECT_REOPEN,
            Permission.PROJECT_MEMBER_READ,
            Permission.PROJECT_MEMBER_MANAGE,
            Permission.PROJECT_MEMBER_ROLE_CHANGE,
            Permission.PROJECT_OWNERSHIP_TRANSFER,
        }
    ),
    OrganizationRole.ADMIN: frozenset(
        {
            Permission.PROJECT_READ,
            Permission.PROJECT_UPDATE,
            Permission.PROJECT_ARCHIVE,
            Permission.PROJECT_REOPEN,
            Permission.PROJECT_MEMBER_READ,
            Permission.PROJECT_MEMBER_MANAGE,
            Permission.PROJECT_MEMBER_ROLE_CHANGE,
        }
    ),
    OrganizationRole.MEMBER: frozenset(),
    OrganizationRole.BILLING: frozenset(),
    OrganizationRole.GUEST: frozenset(),
}

_PROJECT_VIEWER = frozenset(
    {Permission.PROJECT_READ, Permission.PROJECT_MEMBER_READ, Permission.PROJECT_DATA_READ}
)
_PROJECT_ANALYST = _PROJECT_VIEWER | {
    Permission.PROJECT_DATA_WRITE,
    Permission.PROJECT_ANALYSIS_EXECUTE,
}
#: A reviewer is a scientific/clinical responsibility, not an administrator: it
#: reviews and finalizes, it does not manage membership.
_PROJECT_REVIEWER = _PROJECT_VIEWER | {
    Permission.PROJECT_INTERPRETATION_REVIEW,
    Permission.PROJECT_REPORT_FINALIZE,
}
_PROJECT_MANAGER = _PROJECT_ANALYST | {
    Permission.PROJECT_UPDATE,
    Permission.PROJECT_ARCHIVE,
    Permission.PROJECT_REOPEN,
    Permission.PROJECT_MEMBER_MANAGE,
    Permission.PROJECT_MEMBER_ROLE_CHANGE,
}

PROJECT_ROLE_PERMISSIONS: Mapping[ProjectRole, frozenset[Permission]] = {
    ProjectRole.OWNER: _PROJECT_MANAGER | {Permission.PROJECT_OWNERSHIP_TRANSFER},
    ProjectRole.MANAGER: _PROJECT_MANAGER,
    ProjectRole.ANALYST: _PROJECT_ANALYST,
    ProjectRole.REVIEWER: _PROJECT_REVIEWER,
    ProjectRole.VIEWER: _PROJECT_VIEWER,
}

#: Permissions the owner of a personal workspace holds over that workspace.
PERSONAL_WORKSPACE_PERMISSIONS: frozenset[Permission] = frozenset(
    {Permission.WORKSPACE_READ, Permission.WORKSPACE_PROJECT_CREATE}
)


def platform_permissions(roles: frozenset[PlatformRole]) -> frozenset[Permission]:
    granted: frozenset[Permission] = frozenset()
    for role in roles:
        granted |= PLATFORM_ROLE_PERMISSIONS.get(role, frozenset())
    return granted


__all__ = [
    "ORGANIZATION_ROLE_PERMISSIONS",
    "ORGANIZATION_ROLE_PROJECT_PERMISSIONS",
    "PERSONAL_WORKSPACE_PERMISSIONS",
    "PLATFORM_ROLE_PERMISSIONS",
    "PROJECT_ROLE_PERMISSIONS",
    "platform_permissions",
]
