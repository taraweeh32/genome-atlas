"""Shared dependencies and authorization for the interpretation/review use cases.

Four capabilities, deliberately four separate permissions:

* **read** an interpretation, its versions, its review history and its
  disagreements — reading a decision is not making one;
* **author** a version — opening a decision context and recording a proposal;
* **review** — recording a reviewer action against a version;
* **adjudicate** and **finalize** — resolving a disagreement, and closing a version
  as the final immutable record. Neither is implied by *review*, so a reviewer who
  disagreed cannot rule on their own disagreement by virtue of being a reviewer.

Scope always comes from the stored interpretation row, never from the request body:
that is what stops a known interpretation identifier from becoming a cross-tenant
read or write.
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
from app.domain.errors import AuthorizationError, NotFoundError
from app.domain.review.entities import InterpretationRecord


@dataclass(frozen=True)
class ReviewServices:
    """The dependency bundle every interpretation/review use case shares."""

    unit_of_work: Any
    clock: Any
    authorization: AuthorizationService
    config: ApplicationSettings
    software_version: str = "package-11"


@dataclass(frozen=True, slots=True)
class ScopedPermission:
    workspace: Permission
    project: Permission


INTERPRETATION_READ = ScopedPermission(
    Permission.WORKSPACE_INTERPRETATION_READ, Permission.PROJECT_INTERPRETATION_READ
)
INTERPRETATION_AUTHOR = ScopedPermission(
    Permission.WORKSPACE_INTERPRETATION_AUTHOR, Permission.PROJECT_INTERPRETATION_AUTHOR
)
#: Recording a reviewer action. Project-scoped in both slots: review is a project
#: responsibility, and a workspace-level grant never stands in for it.
INTERPRETATION_REVIEW = ScopedPermission(
    Permission.PROJECT_INTERPRETATION_REVIEW, Permission.PROJECT_INTERPRETATION_REVIEW
)
INTERPRETATION_ADJUDICATE = ScopedPermission(
    Permission.PROJECT_INTERPRETATION_ADJUDICATE,
    Permission.PROJECT_INTERPRETATION_ADJUDICATE,
)
INTERPRETATION_FINALIZE = ScopedPermission(
    Permission.PROJECT_INTERPRETATION_FINALIZE,
    Permission.PROJECT_INTERPRETATION_FINALIZE,
)


@dataclass(frozen=True, slots=True)
class ResolvedScope:
    actor: ActorContext
    workspace_id: str
    project_id: str | None


async def require_scope(
    services: ReviewServices,
    repositories: Any,
    actor: ActorContext,
    *,
    workspace_id: str,
    project_id: str | None,
    action: ScopedPermission,
    recorder: ActivityRecorder,
    occurred_at: datetime,
) -> ResolvedScope:
    """Require ``action`` in the scope the stored row itself declares."""
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


async def load_authorized_interpretation(
    services: ReviewServices,
    repositories: Any,
    actor: ActorContext,
    *,
    interpretation_id: str,
    action: ScopedPermission,
    recorder: ActivityRecorder,
    occurred_at: datetime,
) -> tuple[InterpretationRecord, ResolvedScope]:
    """Read an interpretation and authorize against *its* workspace and project.

    A missing row and an unauthorized row both surface as ``not found``, so the
    endpoint cannot be used to probe for the existence of another tenant's work.
    """
    record = await repositories.interpretations.get(interpretation_id)
    if record is None:
        raise NotFoundError("interpretation", interpretation_id)
    try:
        scope = await require_scope(
            services,
            repositories,
            actor,
            workspace_id=record.workspace_id,
            project_id=record.project_id,
            action=action,
            recorder=recorder,
            occurred_at=occurred_at,
        )
    except (AuthorizationError, NotFoundError) as error:
        raise NotFoundError("interpretation", interpretation_id) from error
    return record, scope


def readable_workspace_scope(
    actor: ActorContext,
    *,
    workspace_id: str | None = None,
    action: ScopedPermission = INTERPRETATION_READ,
) -> tuple[str, ...]:
    """Workspaces the actor may read interpretations in.

    Built from grants the platform holds, never from identifiers the client sent, so
    a listing physically cannot reach another tenant's interpretations.
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
    "INTERPRETATION_ADJUDICATE",
    "INTERPRETATION_AUTHOR",
    "INTERPRETATION_FINALIZE",
    "INTERPRETATION_READ",
    "INTERPRETATION_REVIEW",
    "ResolvedScope",
    "ReviewServices",
    "ScopedPermission",
    "load_authorized_interpretation",
    "readable_workspace_scope",
    "require_scope",
]
