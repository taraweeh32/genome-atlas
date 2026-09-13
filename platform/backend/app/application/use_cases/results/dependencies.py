"""Shared dependencies and scope resolution for the scientific data layer.

The same shape as the dataset and analysis packages, for the same reason: the
resource row declares its own scope, the caller's permission is evaluated **in
that scope**, and the permission mapping exists in exactly one place.

One thing is specific to this package. Canonical variants are shared across
tenants by construction — the same variant is the same variant everywhere — so a
variant is never authorized by "who owns it". It is authorized through the
dataset version, result set or project *through which the caller reached it*.
``require_variant_access`` is the only door, and it always needs such a context.
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
from app.domain.variant.results import ResultSetRecord


@dataclass(frozen=True)
class ResultServices:
    """The dependency bundle the result and variant use cases share."""

    unit_of_work: Any
    clock: Any
    authorization: AuthorizationService
    config: ApplicationSettings
    #: Reads materialized Parquet surfaces. Optional so that use cases which only
    #: touch metadata need no analytical wiring at all.
    analytics: Any | None = None
    #: Verifies that stored artifact bytes match what the producer declared.
    checksums: Any | None = None
    object_storage: Any | None = None
    #: How long a presigned artifact download stays valid.
    download_url_seconds: int = 300


@dataclass(frozen=True, slots=True)
class ScopedPermission:
    """A permission pair: the workspace-scoped and project-scoped equivalents."""

    workspace: Permission
    project: Permission


RESULT_READ = ScopedPermission(
    Permission.WORKSPACE_RESULT_READ, Permission.PROJECT_RESULT_READ
)
RESULT_INGEST = ScopedPermission(
    Permission.WORKSPACE_RESULT_INGEST, Permission.PROJECT_RESULT_INGEST
)
RESULT_DOWNLOAD = ScopedPermission(
    Permission.WORKSPACE_RESULT_DOWNLOAD, Permission.PROJECT_RESULT_DOWNLOAD
)
VARIANT_READ = ScopedPermission(
    Permission.WORKSPACE_VARIANT_READ, Permission.PROJECT_VARIANT_READ
)

#: Capability names reported to the UI for rendering only. Never a check: the UI
#: hides a button, the server refuses the operation.
_CAPABILITY_PERMISSIONS: dict[str, ScopedPermission] = {
    "read": RESULT_READ,
    "download": RESULT_DOWNLOAD,
    "variant_read": VARIANT_READ,
}


@dataclass(frozen=True, slots=True)
class ResolvedScope:
    actor: ActorContext
    workspace_id: str
    project_id: str | None


async def resolve_scope(
    services: ResultServices,
    repositories: Any,
    actor: ActorContext,
    *,
    workspace_id: str,
    project_id: str | None,
    action: ScopedPermission,
    recorder: ActivityRecorder,
    occurred_at: datetime,
) -> ResolvedScope:
    """Require ``action`` in the scope the resource itself declares."""
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


async def require_result_access(
    services: ResultServices,
    repositories: Any,
    actor: ActorContext,
    result_set: ResultSetRecord,
    *,
    action: ScopedPermission,
    recorder: ActivityRecorder,
    occurred_at: datetime,
) -> ResolvedScope:
    return await resolve_scope(
        services,
        repositories,
        actor,
        workspace_id=result_set.workspace_id,
        project_id=result_set.project_id,
        action=action,
        recorder=recorder,
        occurred_at=occurred_at,
    )


async def require_variant_access(
    services: ResultServices,
    repositories: Any,
    actor: ActorContext,
    *,
    dataset_version_id: str,
    recorder: ActivityRecorder,
    occurred_at: datetime,
) -> ResolvedScope:
    """Authorize a variant read through the dataset version that contains it.

    The dataset version row carries the tenant scope; the request does not. A
    caller who knows a variant id but cannot read any dataset version containing
    it gets nothing, which is what stops canonical-variant sharing from becoming
    a cross-tenant read.
    """
    from app.domain.errors import NotFoundError

    version = await repositories.dataset_versions.get(dataset_version_id)
    if version is None:
        raise NotFoundError("dataset_version", dataset_version_id)
    dataset = await repositories.datasets.get(version.dataset_id)
    if dataset is None:
        raise NotFoundError("dataset_version", dataset_version_id)
    return await resolve_scope(
        services,
        repositories,
        actor,
        workspace_id=dataset.workspace_id,
        project_id=dataset.project_id,
        action=VARIANT_READ,
        recorder=recorder,
        occurred_at=occurred_at,
    )


def result_capabilities(actor: ActorContext, result_set: ResultSetRecord) -> tuple[str, ...]:
    """What the *server* would allow on this result set, for UI rendering only."""
    if result_set.project_id:
        held = actor.project_capabilities(result_set.project_id)
        return tuple(
            sorted(
                name
                for name, action in _CAPABILITY_PERMISSIONS.items()
                if action.project in held
            )
        )
    held = actor.workspace_capabilities(result_set.workspace_id)
    return tuple(
        sorted(
            name
            for name, action in _CAPABILITY_PERMISSIONS.items()
            if action.workspace in held
        )
    )


def readable_workspace_scope(
    actor: ActorContext,
    *,
    workspace_id: str | None,
    action: ScopedPermission = RESULT_READ,
) -> tuple[str, ...]:
    """Workspaces the actor may read this resource kind in.

    Project grants are independent of workspace grants, so a workspace reachable
    only through a single project membership is included — and only that.
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
    "RESULT_DOWNLOAD",
    "RESULT_INGEST",
    "RESULT_READ",
    "VARIANT_READ",
    "ResolvedScope",
    "ResultServices",
    "ScopedPermission",
    "readable_workspace_scope",
    "require_result_access",
    "require_variant_access",
    "resolve_scope",
    "result_capabilities",
]
