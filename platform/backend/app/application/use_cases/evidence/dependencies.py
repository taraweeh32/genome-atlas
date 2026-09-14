"""Shared dependencies and governance for the evidence use cases.

Evidence **sources** are platform-governed: a source version is a versioned
scientific identity, not tenant content, so registering, activating or retiring
one requires the platform evidence-administration permission and nothing else
grants it — an organization administrator never reaches it.

Evidence **records** are tenant content when they carry a workspace, and shared
reference content when they do not. Their scope always comes from the stored row,
never from the request, which is what stops a known identifier from becoming a
cross-tenant read or write.
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
class EvidenceServices:
    """The dependency bundle every evidence use case shares."""

    unit_of_work: Any
    clock: Any
    authorization: AuthorizationService
    config: ApplicationSettings
    #: The only door to the scientific compute subsystem, used when evidence is
    #: retrieved through it. Optional: registry and curation need no scientific
    #: wiring at all.
    scientific: Any | None = None
    #: Verifies that a declared artifact checksum matches the stored bytes.
    checksums: Any | None = None
    software_version: str = "package-9"


@dataclass(frozen=True, slots=True)
class ScopedPermission:
    workspace: Permission
    project: Permission


EVIDENCE_READ = ScopedPermission(
    Permission.WORKSPACE_EVIDENCE_READ, Permission.PROJECT_EVIDENCE_READ
)
EVIDENCE_CURATE = ScopedPermission(
    Permission.WORKSPACE_EVIDENCE_CURATE, Permission.PROJECT_EVIDENCE_CURATE
)

PLATFORM_ADMINISTER = Permission.PLATFORM_EVIDENCE_RESOURCE_ADMINISTER
PLATFORM_READ = Permission.PLATFORM_EVIDENCE_READ


@dataclass(frozen=True, slots=True)
class ResolvedScope:
    actor: ActorContext
    workspace_id: str | None
    project_id: str | None


async def require_platform_administration(
    services: EvidenceServices,
    actor: ActorContext,
    *,
    recorder: ActivityRecorder,
    occurred_at: datetime,
) -> None:
    """Source governance is platform-level. No tenant role substitutes for it."""
    await services.authorization.require(
        actor, PLATFORM_ADMINISTER, recorder=recorder, occurred_at=occurred_at
    )


async def require_platform_read(
    services: EvidenceServices,
    actor: ActorContext,
    *,
    recorder: ActivityRecorder,
    occurred_at: datetime,
) -> None:
    await services.authorization.require(
        actor, PLATFORM_READ, recorder=recorder, occurred_at=occurred_at
    )


async def resolve_scope(
    services: EvidenceServices,
    repositories: Any,
    actor: ActorContext,
    *,
    workspace_id: str | None,
    project_id: str | None,
    action: ScopedPermission,
    recorder: ActivityRecorder,
    occurred_at: datetime,
) -> ResolvedScope:
    """Require ``action`` in the scope the target itself declares.

    A record with neither workspace nor project is platform reference evidence;
    writing it is platform governance, not a tenant capability.
    """
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
    elif workspace_id is not None:
        await services.authorization.require(
            actor,
            action.workspace,
            recorder=recorder,
            occurred_at=occurred_at,
            workspace_id=workspace_id,
        )
    else:
        await services.authorization.require(
            actor, PLATFORM_ADMINISTER, recorder=recorder, occurred_at=occurred_at
        )
    return ResolvedScope(actor=actor, workspace_id=workspace_id, project_id=project_id)


def readable_workspace_scope(
    actor: ActorContext,
    *,
    workspace_id: str | None = None,
    action: ScopedPermission = EVIDENCE_READ,
) -> tuple[str, ...]:
    """Workspaces the actor may read evidence in.

    Built from grants the platform holds, never from identifiers the client sent,
    so a listing physically cannot reach another tenant's evidence.
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
    "EVIDENCE_CURATE",
    "EVIDENCE_READ",
    "PLATFORM_ADMINISTER",
    "PLATFORM_READ",
    "EvidenceServices",
    "ResolvedScope",
    "ScopedPermission",
    "readable_workspace_scope",
    "require_platform_administration",
    "require_platform_read",
    "resolve_scope",
]
