"""Shared dependencies, scope resolution and governance for query use cases.

Every filter, preset, ranking configuration and saved view declares its own scope
on its row. That declaration — never anything in the request — decides which
permission is evaluated and in which scope:

* **platform** — readable by any usable account (these are the platform's offered
  presets), writable only with the platform administration permission;
* **organization** — governed by the organization permissions, so an organization
  administrator curates their own presets and no one else's;
* **project** — governed by the project permissions, independent of organization
  membership;
* **personal** — the owner, and only the owner.

``authorized_scopes`` is the single place a caller's memberships are turned into
the scope filter every listing uses. Because the filter is built from grants the
platform holds rather than identifiers the client sends, a listing physically
cannot reach another tenant's configurations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.application.repositories import QueryScopeFilter
from app.application.services.authorization import AuthorizationService
from app.application.services.recorder import ActivityRecorder
from app.core.app_config import ApplicationSettings
from app.domain.authorization.context import ActorContext
from app.domain.authorization.permissions import Permission
from app.domain.errors import AuthorizationError, ValidationError
from app.domain.query.fields import DEFAULT_FIELD_REGISTRY, FilterFieldRegistry
from app.domain.query.ranking import RANKING_METHOD_REGISTRY, RankingMethodRegistry
from app.domain.query.validation import FilterLimits
from app.domain.value_objects.enums import QueryScope


@dataclass(frozen=True)
class QueryServices:
    """The dependency bundle the filtering, ranking and view use cases share."""

    unit_of_work: Any
    clock: Any
    authorization: AuthorizationService
    config: ApplicationSettings
    #: Executes compiled predicates against the Parquet surfaces. Optional so that
    #: definition management needs no analytical wiring.
    query_engine: Any | None = None
    fields: FilterFieldRegistry = DEFAULT_FIELD_REGISTRY
    methods: RankingMethodRegistry = RANKING_METHOD_REGISTRY
    #: Resource-governance limits. Configuration-driven, never invented at a call
    #: site, so raising a limit is an operational decision and not a code change.
    limits: FilterLimits = field(default_factory=FilterLimits)
    #: Above this many rows a query is refused for synchronous execution and must
    #: be run as a durable job instead.
    max_page_size: int = 200
    #: Identifies the software that produced an execution record.
    software_version: str = "package-7"


@dataclass(frozen=True, slots=True)
class ScopedPermission:
    """The workspace- and project-scoped equivalents of one capability."""

    workspace: Permission
    project: Permission


FILTER_READ = ScopedPermission(
    Permission.WORKSPACE_FILTER_READ, Permission.PROJECT_FILTER_READ
)
FILTER_MANAGE = ScopedPermission(
    Permission.WORKSPACE_FILTER_MANAGE, Permission.PROJECT_FILTER_MANAGE
)
RANKING_READ = ScopedPermission(
    Permission.WORKSPACE_RANKING_READ, Permission.PROJECT_RANKING_READ
)
RANKING_MANAGE = ScopedPermission(
    Permission.WORKSPACE_RANKING_MANAGE, Permission.PROJECT_RANKING_MANAGE
)
QUERY_EXECUTE = ScopedPermission(
    Permission.WORKSPACE_QUERY_EXECUTE, Permission.PROJECT_QUERY_EXECUTE
)
VIEW_MANAGE = ScopedPermission(
    Permission.WORKSPACE_SAVED_VIEW_MANAGE, Permission.PROJECT_SAVED_VIEW_MANAGE
)


@dataclass(frozen=True, slots=True)
class ConfigurationKind:
    """How one configuration kind is governed, in one place.

    Filters and rankings are governed identically in *shape* and separately in
    *fact*: holding ``filter.manage`` grants nothing over a ranking. Naming the
    permissions here is what makes that separation checkable.
    """

    name: str
    read: ScopedPermission
    manage: ScopedPermission
    organization_read: Permission
    organization_manage: Permission
    platform_manage: Permission


SAVED_FILTER = ConfigurationKind(
    name="filter_definition",
    read=FILTER_READ,
    manage=FILTER_MANAGE,
    organization_read=Permission.ORGANIZATION_QUERY_PRESET_READ,
    organization_manage=Permission.ORGANIZATION_QUERY_PRESET_MANAGE,
    platform_manage=Permission.PLATFORM_QUERY_PRESET_ADMINISTER,
)
FILTER_PRESET = ConfigurationKind(
    name="filter_preset",
    read=FILTER_READ,
    manage=FILTER_MANAGE,
    organization_read=Permission.ORGANIZATION_QUERY_PRESET_READ,
    organization_manage=Permission.ORGANIZATION_QUERY_PRESET_MANAGE,
    platform_manage=Permission.PLATFORM_QUERY_PRESET_ADMINISTER,
)
SAVED_RANKING = ConfigurationKind(
    name="ranking_definition",
    read=RANKING_READ,
    manage=RANKING_MANAGE,
    organization_read=Permission.ORGANIZATION_QUERY_PRESET_READ,
    organization_manage=Permission.ORGANIZATION_QUERY_PRESET_MANAGE,
    platform_manage=Permission.PLATFORM_QUERY_PRESET_ADMINISTER,
)
RANKING_PRESET = ConfigurationKind(
    name="ranking_preset",
    read=RANKING_READ,
    manage=RANKING_MANAGE,
    organization_read=Permission.ORGANIZATION_QUERY_PRESET_READ,
    organization_manage=Permission.ORGANIZATION_QUERY_PRESET_MANAGE,
    platform_manage=Permission.PLATFORM_QUERY_PRESET_ADMINISTER,
)
SAVED_VIEW = ConfigurationKind(
    name="saved_view",
    read=VIEW_MANAGE,
    manage=VIEW_MANAGE,
    organization_read=Permission.ORGANIZATION_QUERY_PRESET_READ,
    organization_manage=Permission.ORGANIZATION_QUERY_PRESET_MANAGE,
    platform_manage=Permission.PLATFORM_QUERY_PRESET_ADMINISTER,
)


@dataclass(frozen=True, slots=True)
class ResolvedScope:
    actor: ActorContext
    workspace_id: str | None
    project_id: str | None


async def resolve_workspace_scope(
    services: QueryServices,
    repositories: Any,
    actor: ActorContext,
    *,
    workspace_id: str,
    project_id: str | None,
    action: ScopedPermission,
    recorder: ActivityRecorder,
    occurred_at: datetime,
) -> ResolvedScope:
    """Require ``action`` in the scope the addressed resource declares."""
    if project_id is not None:
        actor = await services.authorization.ensure_project_scope(
            repositories, actor, project_id
        )
        await services.authorization.require(
            actor,
            action.project,
            recorder=recorder,
            occurred_at=occurred_at,
            project_id=project_id,
        )
    else:
        await services.authorization.require(
            actor,
            action.workspace,
            recorder=recorder,
            occurred_at=occurred_at,
            workspace_id=workspace_id,
        )
    return ResolvedScope(actor=actor, workspace_id=workspace_id, project_id=project_id)


async def require_configuration_access(
    services: QueryServices,
    repositories: Any,
    actor: ActorContext,
    record: Any,
    *,
    kind: ConfigurationKind,
    manage: bool,
    recorder: ActivityRecorder,
    occurred_at: datetime,
) -> ResolvedScope:
    """Authorize a read or a write against the scope the record declares.

    A denial is recorded in the security trail by the authorization service, and
    the message never distinguishes "not yours" from "does not exist", so knowing
    an identifier reveals nothing.
    """
    scope = record.scope
    if scope is QueryScope.PLATFORM:
        if manage:
            await services.authorization.require(
                actor,
                kind.platform_manage,
                recorder=recorder,
                occurred_at=occurred_at,
            )
        elif not (actor and actor.account_is_usable):
            raise AuthorizationError("the requested operation is not permitted")
        return ResolvedScope(actor=actor, workspace_id=None, project_id=None)

    if scope is QueryScope.PERSONAL:
        # A personal configuration is never visible outside its owner, not even to
        # a workspace administrator: it is the user's own working state.
        if record.owner_user_id != actor.actor_id:
            raise AuthorizationError("the requested operation is not permitted")
        return ResolvedScope(
            actor=actor, workspace_id=record.workspace_id, project_id=None
        )

    if scope is QueryScope.ORGANIZATION:
        permission = kind.organization_manage if manage else kind.organization_read
        await services.authorization.require(
            actor,
            permission,
            recorder=recorder,
            occurred_at=occurred_at,
            organization_id=record.organization_id,
        )
        return ResolvedScope(actor=actor, workspace_id=None, project_id=None)

    action = kind.manage if manage else kind.read
    return await resolve_workspace_scope(
        services,
        repositories,
        actor,
        workspace_id=record.workspace_id or "",
        project_id=record.project_id,
        action=action,
        recorder=recorder,
        occurred_at=occurred_at,
    )


async def require_creation_scope(
    services: QueryServices,
    repositories: Any,
    actor: ActorContext,
    *,
    kind: ConfigurationKind,
    scope: QueryScope,
    workspace_id: str | None,
    project_id: str | None,
    organization_id: str | None,
    recorder: ActivityRecorder,
    occurred_at: datetime,
) -> ActorContext:
    """Authorize creating a configuration in the requested scope.

    The scope is the client's choice, which is exactly why it is checked here: a
    caller may not publish a platform preset by asking for one.
    """
    if scope is QueryScope.PLATFORM:
        await services.authorization.require(
            actor, kind.platform_manage, recorder=recorder, occurred_at=occurred_at
        )
        return actor
    if scope is QueryScope.ORGANIZATION:
        await services.authorization.require(
            actor,
            kind.organization_manage,
            recorder=recorder,
            occurred_at=occurred_at,
            organization_id=organization_id,
        )
        return actor
    if scope is QueryScope.PERSONAL:
        if not workspace_id:
            raise ValidationError("a personal configuration requires a workspace")
        resolved = await resolve_workspace_scope(
            services,
            repositories,
            actor,
            workspace_id=workspace_id,
            project_id=None,
            action=kind.read,
            recorder=recorder,
            occurred_at=occurred_at,
        )
        return resolved.actor
    resolved = await resolve_workspace_scope(
        services,
        repositories,
        actor,
        workspace_id=workspace_id or "",
        project_id=project_id,
        action=kind.manage,
        recorder=recorder,
        occurred_at=occurred_at,
    )
    return resolved.actor


def authorized_scopes(
    actor: ActorContext, *, kind: ConfigurationKind, include_platform: bool = True
) -> QueryScopeFilter:
    """The scopes this actor may list configurations from.

    Built from the grants the platform resolved for the actor, so an identifier the
    client did not earn simply never appears in the WHERE clause.
    """
    projects = tuple(
        project_id
        for project_id in actor.projects
        if kind.read.project in actor.project_capabilities(project_id)
    )
    workspaces = tuple(
        workspace_id
        for workspace_id in actor.workspaces
        if kind.read.workspace in actor.workspace_capabilities(workspace_id)
    )
    organizations = tuple(
        organization_id
        for organization_id in actor.organizations
        if kind.organization_read in actor.organization_capabilities(organization_id)
    )
    return QueryScopeFilter(
        user_id=actor.actor_id,
        workspace_ids=workspaces,
        project_ids=projects,
        organization_ids=organizations,
        include_platform=include_platform and actor.account_is_usable,
    )


def configuration_capabilities(
    actor: ActorContext, record: Any, *, kind: ConfigurationKind
) -> tuple[str, ...]:
    """What the server would allow on this record, for UI rendering only.

    The frontend uses these to decide what to offer. It is never the check: every
    operation re-evaluates the permission server-side.
    """
    granted: list[str] = ["read"]
    scope = record.scope
    if scope is QueryScope.PLATFORM:
        if kind.platform_manage in actor.platform_capabilities():
            granted.append("manage")
    elif scope is QueryScope.PERSONAL:
        if record.owner_user_id == actor.actor_id:
            granted.append("manage")
    elif scope is QueryScope.ORGANIZATION:
        if kind.organization_manage in actor.organization_capabilities(
            record.organization_id or ""
        ):
            granted.append("manage")
    elif record.project_id:
        if kind.manage.project in actor.project_capabilities(record.project_id):
            granted.append("manage")
    elif kind.manage.workspace in actor.workspace_capabilities(record.workspace_id or ""):
        granted.append("manage")
    return tuple(granted)


__all__ = [
    "FILTER_MANAGE",
    "FILTER_PRESET",
    "FILTER_READ",
    "QUERY_EXECUTE",
    "RANKING_MANAGE",
    "RANKING_PRESET",
    "RANKING_READ",
    "SAVED_FILTER",
    "SAVED_RANKING",
    "SAVED_VIEW",
    "VIEW_MANAGE",
    "ConfigurationKind",
    "QueryServices",
    "ResolvedScope",
    "ScopedPermission",
    "authorized_scopes",
    "configuration_capabilities",
    "require_configuration_access",
    "require_creation_scope",
    "resolve_workspace_scope",
]
