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
        Permission.PLATFORM_STORAGE_ADMINISTER,
        Permission.PLATFORM_JOB_ADMINISTER,
        Permission.PLATFORM_JOB_READ,
        Permission.PLATFORM_COMPUTE_ADMINISTER,
        Permission.PLATFORM_COMPUTE_READ,
        Permission.PLATFORM_SCHEDULE_ADMINISTER,
        Permission.PLATFORM_RESULT_ADMINISTER,
        Permission.PLATFORM_RESULT_READ,
        # Governance of the filtering and ranking vocabulary: which fields and
        # methods exist, which presets the platform offers, and the query limits
        # everyone runs under.
        Permission.PLATFORM_ANNOTATION_RESOURCE_ADMINISTER,
        Permission.PLATFORM_ANNOTATION_READ,
        Permission.PLATFORM_FILTER_FIELD_ADMINISTER,
        Permission.PLATFORM_RANKING_METHOD_ADMINISTER,
        Permission.PLATFORM_QUERY_PRESET_ADMINISTER,
        Permission.PLATFORM_QUERY_LIMIT_MANAGE,
        Permission.PLATFORM_QUERY_READ,
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
        # An operator watches the control plane; it does not steer it.
        Permission.PLATFORM_JOB_READ,
        Permission.PLATFORM_COMPUTE_READ,
        # Operational visibility of the result surface, without the authority to
        # invalidate one.
        Permission.PLATFORM_RESULT_READ,
        # Visibility of what was queried, without authority over the vocabulary.
        Permission.PLATFORM_QUERY_READ,
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
    Permission.WORKSPACE_DATASET_CREATE,
    Permission.WORKSPACE_DATA_READ,
    Permission.WORKSPACE_DATA_WRITE,
    Permission.WORKSPACE_DATA_IMPORT,
    Permission.WORKSPACE_DATA_DOWNLOAD,
    Permission.WORKSPACE_ANALYSIS_READ,
    Permission.WORKSPACE_ANALYSIS_CREATE,
    Permission.WORKSPACE_ANALYSIS_UPDATE,
    Permission.WORKSPACE_ANALYSIS_EXECUTE,
    Permission.WORKSPACE_ANALYSIS_CANCEL,
    Permission.WORKSPACE_SCHEDULE_MANAGE,
    Permission.WORKSPACE_JOB_READ,
    Permission.WORKSPACE_VARIANT_READ,
    Permission.WORKSPACE_RESULT_READ,
    Permission.WORKSPACE_RESULT_INGEST,
    Permission.WORKSPACE_RESULT_DOWNLOAD,
    # Filtering, ranking and view state are working capabilities of anyone who
    # may read the workspace's results. They are separate grants so a filter
    # permission never implies a ranking permission.
    Permission.WORKSPACE_FILTER_READ,
    Permission.WORKSPACE_FILTER_MANAGE,
    Permission.WORKSPACE_RANKING_READ,
    Permission.WORKSPACE_RANKING_MANAGE,
    Permission.WORKSPACE_QUERY_EXECUTE,
    Permission.WORKSPACE_SAVED_VIEW_MANAGE,
    Permission.ORGANIZATION_QUERY_PRESET_READ,
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
    Permission.WORKSPACE_DATA_DELETE,
    Permission.WORKSPACE_ANALYSIS_DELETE,
    # Curating the organization's own offered presets. Platform presets stay out
    # of reach.
    Permission.ORGANIZATION_QUERY_PRESET_MANAGE,
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
    {
        Permission.PROJECT_READ,
        Permission.PROJECT_MEMBER_READ,
        Permission.PROJECT_DATA_READ,
        Permission.PROJECT_ANALYSIS_READ,
        # Reading scientific content of the project's own results. Reading is
        # not downloading: bytes need their own grant.
        Permission.PROJECT_VARIANT_READ,
        Permission.PROJECT_RESULT_READ,
        # Reading results implies being able to query them and to keep one's own
        # view and configuration state; it never implies curating a preset.
        Permission.PROJECT_FILTER_READ,
        Permission.PROJECT_FILTER_MANAGE,
        Permission.PROJECT_RANKING_READ,
        Permission.PROJECT_RANKING_MANAGE,
        Permission.PROJECT_QUERY_EXECUTE,
        Permission.PROJECT_SAVED_VIEW_MANAGE,
        # Annotation status and provenance are part of reading the project's
        # scientific data; requesting a run is an analyst capability below.
        Permission.PROJECT_ANNOTATION_READ,
    }
)
#: An analyst produces and imports data; deletion stays with project management.
_PROJECT_ANALYST = _PROJECT_VIEWER | {
    Permission.PROJECT_DATA_WRITE,
    Permission.PROJECT_DATASET_CREATE,
    Permission.PROJECT_DATA_IMPORT,
    Permission.PROJECT_DATA_DOWNLOAD,
    Permission.PROJECT_ANALYSIS_CREATE,
    Permission.PROJECT_ANALYSIS_UPDATE,
    Permission.PROJECT_ANALYSIS_EXECUTE,
    Permission.PROJECT_ANALYSIS_CANCEL,
    Permission.PROJECT_SCHEDULE_MANAGE,
    Permission.PROJECT_JOB_READ,
    Permission.PROJECT_RESULT_INGEST,
    Permission.PROJECT_RESULT_DOWNLOAD,
    Permission.PROJECT_ANNOTATION_EXECUTE,
}
#: A reviewer is a scientific/clinical responsibility, not an administrator: it
#: reviews and finalizes, it does not manage membership.
_PROJECT_REVIEWER = _PROJECT_VIEWER | {
    Permission.PROJECT_DATA_DOWNLOAD,
    Permission.PROJECT_RESULT_DOWNLOAD,
    Permission.PROJECT_INTERPRETATION_REVIEW,
    Permission.PROJECT_REPORT_FINALIZE,
}
_PROJECT_MANAGER = _PROJECT_ANALYST | {
    Permission.PROJECT_DATA_DELETE,
    Permission.PROJECT_ANALYSIS_DELETE,
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
    {
        Permission.WORKSPACE_READ,
        Permission.WORKSPACE_PROJECT_CREATE,
        Permission.WORKSPACE_DATASET_CREATE,
        Permission.WORKSPACE_DATA_READ,
        Permission.WORKSPACE_DATA_WRITE,
        Permission.WORKSPACE_DATA_IMPORT,
        Permission.WORKSPACE_DATA_DOWNLOAD,
        Permission.WORKSPACE_DATA_DELETE,
        Permission.WORKSPACE_ANALYSIS_READ,
        Permission.WORKSPACE_ANALYSIS_CREATE,
        Permission.WORKSPACE_ANALYSIS_UPDATE,
        Permission.WORKSPACE_ANALYSIS_EXECUTE,
        Permission.WORKSPACE_ANALYSIS_CANCEL,
        Permission.WORKSPACE_ANALYSIS_DELETE,
        Permission.WORKSPACE_SCHEDULE_MANAGE,
        Permission.WORKSPACE_JOB_READ,
        Permission.WORKSPACE_VARIANT_READ,
        Permission.WORKSPACE_RESULT_READ,
        Permission.WORKSPACE_RESULT_INGEST,
        Permission.WORKSPACE_RESULT_DOWNLOAD,
        Permission.WORKSPACE_FILTER_READ,
        Permission.WORKSPACE_FILTER_MANAGE,
        Permission.WORKSPACE_RANKING_READ,
        Permission.WORKSPACE_RANKING_MANAGE,
        Permission.WORKSPACE_QUERY_EXECUTE,
        Permission.WORKSPACE_SAVED_VIEW_MANAGE,
        Permission.WORKSPACE_ANNOTATION_READ,
        Permission.WORKSPACE_ANNOTATION_EXECUTE,
    }
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
