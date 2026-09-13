"""Shared dependencies and scope resolution for analysis use cases.

Mirrors the dataset package deliberately: an analysis declares its own scope on
its row, the caller's permission is evaluated **in that scope**, and the mapping
lives in exactly one place so it cannot drift between a dozen call sites.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.application.services.authorization import AuthorizationService
from app.application.services.recorder import ActivityRecorder
from app.core.app_config import ApplicationSettings
from app.domain.analysis.entities import AnalysisDefinition
from app.domain.analysis.policies import LeasePolicy, RetryPolicy, TimeoutPolicy
from app.domain.authorization.context import ActorContext
from app.domain.authorization.permissions import Permission


@dataclass(frozen=True)
class AnalysisServices:
    """The dependency bundle analysis/execution/job/schedule use cases share."""

    unit_of_work: Any
    clock: Any
    authorization: AuthorizationService
    config: ApplicationSettings
    #: The scientific integration gateway. Only execution runners receive one;
    #: it is optional so pure orchestration use cases need no scientific wiring.
    scientific: Any | None = None
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    lease: LeasePolicy = field(default_factory=LeasePolicy)
    timeouts: TimeoutPolicy = field(default_factory=TimeoutPolicy)
    #: How long a soft-deleted analysis stays recoverable.
    retention_days: int = 30


@dataclass(frozen=True, slots=True)
class AnalysisAction:
    """A permission pair: the workspace-scoped and project-scoped equivalents."""

    workspace: Permission
    project: Permission


READ = AnalysisAction(Permission.WORKSPACE_ANALYSIS_READ, Permission.PROJECT_ANALYSIS_READ)
CREATE = AnalysisAction(Permission.WORKSPACE_ANALYSIS_CREATE, Permission.PROJECT_ANALYSIS_CREATE)
UPDATE = AnalysisAction(Permission.WORKSPACE_ANALYSIS_UPDATE, Permission.PROJECT_ANALYSIS_UPDATE)
EXECUTE = AnalysisAction(
    Permission.WORKSPACE_ANALYSIS_EXECUTE, Permission.PROJECT_ANALYSIS_EXECUTE
)
CANCEL = AnalysisAction(Permission.WORKSPACE_ANALYSIS_CANCEL, Permission.PROJECT_ANALYSIS_CANCEL)
DELETE = AnalysisAction(Permission.WORKSPACE_ANALYSIS_DELETE, Permission.PROJECT_ANALYSIS_DELETE)
SCHEDULE = AnalysisAction(Permission.WORKSPACE_SCHEDULE_MANAGE, Permission.PROJECT_SCHEDULE_MANAGE)
JOB_READ = AnalysisAction(Permission.WORKSPACE_JOB_READ, Permission.PROJECT_JOB_READ)

#: Capability names the server reports for UI rendering only. Never a check.
_CAPABILITY_PERMISSIONS: dict[str, AnalysisAction] = {
    "read": READ,
    "update": UPDATE,
    "execute": EXECUTE,
    "cancel": CANCEL,
    "delete": DELETE,
    "schedule": SCHEDULE,
}


@dataclass(frozen=True, slots=True)
class ResolvedScope:
    actor: ActorContext
    workspace_id: str
    project_id: str | None


async def resolve_scope(
    services: AnalysisServices,
    repositories: Any,
    actor: ActorContext,
    *,
    workspace_id: str,
    project_id: str | None,
    action: AnalysisAction,
    recorder: ActivityRecorder,
    occurred_at: datetime,
) -> ResolvedScope:
    """Require ``action`` in the scope the resource actually declares."""
    if project_id is not None:
        actor = await services.authorization.ensure_project_scope(repositories, actor, project_id)
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


async def require_analysis_access(
    services: AnalysisServices,
    repositories: Any,
    actor: ActorContext,
    analysis: AnalysisDefinition,
    *,
    action: AnalysisAction,
    recorder: ActivityRecorder,
    occurred_at: datetime,
) -> ResolvedScope:
    return await resolve_scope(
        services,
        repositories,
        actor,
        workspace_id=analysis.workspace_id,
        project_id=analysis.project_id,
        action=action,
        recorder=recorder,
        occurred_at=occurred_at,
    )


def analysis_capabilities(actor: ActorContext, analysis: AnalysisDefinition) -> tuple[str, ...]:
    """What the *server* would allow on this analysis, for UI rendering only."""
    if analysis.project_id:
        held = actor.project_capabilities(analysis.project_id)
        return tuple(
            sorted(
                name
                for name, action in _CAPABILITY_PERMISSIONS.items()
                if action.project in held
            )
        )
    held = actor.workspace_capabilities(analysis.workspace_id)
    return tuple(
        sorted(name for name, action in _CAPABILITY_PERMISSIONS.items() if action.workspace in held)
    )


def readable_workspace_scope(
    actor: ActorContext, *, workspace_id: str | None, action: AnalysisAction = READ
) -> tuple[str, ...]:
    """Workspaces the actor may read this resource kind in.

    Project grants are independent of workspace grants, so a workspace reachable
    only through a project membership is included too.
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
    "CANCEL",
    "CREATE",
    "DELETE",
    "EXECUTE",
    "JOB_READ",
    "READ",
    "SCHEDULE",
    "UPDATE",
    "AnalysisAction",
    "AnalysisServices",
    "ResolvedScope",
    "analysis_capabilities",
    "readable_workspace_scope",
    "require_analysis_access",
    "resolve_scope",
]
