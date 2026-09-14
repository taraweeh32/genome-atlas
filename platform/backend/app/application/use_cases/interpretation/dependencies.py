"""Shared dependencies and governance for the interpretation-engine use cases.

Two different kinds of authority live in this package and they are deliberately
not the same permission:

* **Ruleset governance** is platform-level. A ruleset version is a versioned
  scientific identity — a guideline, its criteria and its combination rules — not
  tenant content. Registering one, or activating, deprecating, retiring or
  invalidating one, requires ``platform.ruleset.administer`` and nothing else
  grants it. An organization administrator never reaches it.
* **Running an evaluation and reading its result** is tenant capability, scoped to
  the workspace or project the evaluated variant surface belongs to.

The scope of an evaluation always comes from the stored row, never from the
request body, which is what stops a known evaluation identifier from becoming a
cross-tenant read.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.application.services.authorization import AuthorizationService
from app.application.services.recorder import ActivityRecorder
from app.core.app_config import ApplicationSettings
from app.domain.authorization.context import ActorContext
from app.domain.authorization.permissions import Permission


@dataclass(frozen=True)
class InterpretationServices:
    """The dependency bundle every interpretation use case shares."""

    unit_of_work: Any
    clock: Any
    authorization: AuthorizationService
    config: ApplicationSettings
    #: The only door to the ACMG/AMP rules engine. Optional: the registry and
    #: result reads need no scientific wiring at all.
    scientific: Any | None = None
    software_version: str = "package-10"


@dataclass(frozen=True, slots=True)
class ScopedPermission:
    workspace: Permission
    project: Permission


CLASSIFICATION_READ = ScopedPermission(
    Permission.WORKSPACE_CLASSIFICATION_READ, Permission.PROJECT_CLASSIFICATION_READ
)
CLASSIFICATION_EXECUTE = ScopedPermission(
    Permission.WORKSPACE_CLASSIFICATION_EXECUTE,
    Permission.PROJECT_CLASSIFICATION_EXECUTE,
)

PLATFORM_ADMINISTER = Permission.PLATFORM_RULESET_ADMINISTER
PLATFORM_READ = Permission.PLATFORM_CLASSIFICATION_READ


@dataclass(frozen=True, slots=True)
class ResolvedScope:
    actor: ActorContext
    workspace_id: str
    project_id: str | None


async def require_platform_administration(
    services: InterpretationServices,
    actor: ActorContext,
    *,
    recorder: ActivityRecorder,
    occurred_at: datetime,
) -> None:
    """Ruleset governance is platform-level. No tenant role substitutes for it."""
    await services.authorization.require(
        actor, PLATFORM_ADMINISTER, recorder=recorder, occurred_at=occurred_at
    )


async def require_platform_read(
    services: InterpretationServices,
    actor: ActorContext,
    *,
    recorder: ActivityRecorder,
    occurred_at: datetime,
) -> None:
    await services.authorization.require(
        actor, PLATFORM_READ, recorder=recorder, occurred_at=occurred_at
    )


async def resolve_scope(
    services: InterpretationServices,
    repositories: Any,
    actor: ActorContext,
    *,
    workspace_id: str,
    project_id: str | None,
    action: ScopedPermission,
    recorder: ActivityRecorder,
    occurred_at: datetime,
) -> ResolvedScope:
    """Require ``action`` in the scope the target row itself declares."""
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


def readable_workspace_scope(
    actor: ActorContext,
    *,
    workspace_id: str | None = None,
    action: ScopedPermission = CLASSIFICATION_READ,
) -> tuple[str, ...]:
    """Workspaces the actor may read classifications in.

    Built from grants the platform holds, never from identifiers the client sent,
    so a listing physically cannot reach another tenant's evaluations.
    """
    direct = tuple(
        candidate
        for candidate in actor.workspaces
        if action.workspace in actor.workspace_capabilities(candidate)
        and (workspace_id is None or candidate == workspace_id)
    )
    through_projects = tuple(
        grant.workspace_id
        for project_id, grant in actor.projects.items()
        if action.project in actor.project_capabilities(project_id)
        and (workspace_id is None or grant.workspace_id == workspace_id)
    )
    return tuple(dict.fromkeys(direct + through_projects))


__all__ = [
    "CLASSIFICATION_EXECUTE",
    "CLASSIFICATION_READ",
    "PLATFORM_ADMINISTER",
    "PLATFORM_READ",
    "InterpretationServices",
    "ResolvedScope",
    "ScopedPermission",
    "readable_workspace_scope",
    "require_platform_administration",
    "require_platform_read",
    "resolve_scope",
]
