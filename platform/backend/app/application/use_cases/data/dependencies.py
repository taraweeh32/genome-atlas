"""Shared dependencies and scope resolution for dataset use cases.

Every dataset-facing operation answers the same question first: *which* scope
does this resource actually live in, and does the caller hold the required
permission **there**? A dataset declares its own scope on its row, so the answer
never comes from the request. ``resolve_scope`` is the single place that mapping
is made, which is what keeps the authorization rule from being re-implemented
(and diverging) in a dozen use cases.
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
from app.domain.data.entities import Dataset


@dataclass(frozen=True)
class DataServices:
    """The dependency bundle dataset/upload/import/validation use cases share."""

    unit_of_work: Any
    clock: Any
    authorization: AuthorizationService
    storage: Any
    scanner: Any
    inspector: Any
    checksums: Any
    config: ApplicationSettings
    storage_provider: str = "s3"
    storage_bucket: str = ""
    upload_url_ttl_seconds: int = 900
    download_url_ttl_seconds: int = 300


@dataclass(frozen=True, slots=True)
class DataAction:
    """A permission pair: the workspace-scoped and project-scoped equivalents.

    A dataset directly in a workspace is governed by the workspace permission; a
    dataset inside a project is governed by the project permission. Organization
    membership alone never reaches into a project's data.
    """

    workspace: Permission
    project: Permission


READ = DataAction(Permission.WORKSPACE_DATA_READ, Permission.PROJECT_DATA_READ)
WRITE = DataAction(Permission.WORKSPACE_DATA_WRITE, Permission.PROJECT_DATA_WRITE)
CREATE = DataAction(Permission.WORKSPACE_DATASET_CREATE, Permission.PROJECT_DATASET_CREATE)
IMPORT = DataAction(Permission.WORKSPACE_DATA_IMPORT, Permission.PROJECT_DATA_IMPORT)
DOWNLOAD = DataAction(Permission.WORKSPACE_DATA_DOWNLOAD, Permission.PROJECT_DATA_DOWNLOAD)
DELETE = DataAction(Permission.WORKSPACE_DATA_DELETE, Permission.PROJECT_DATA_DELETE)


@dataclass(frozen=True, slots=True)
class ResolvedScope:
    actor: ActorContext
    workspace_id: str
    project_id: str | None

    @property
    def permission_for(self) -> str:
        return "project" if self.project_id else "workspace"


async def resolve_scope(
    services: DataServices,
    repositories: Any,
    actor: ActorContext,
    *,
    workspace_id: str,
    project_id: str | None,
    action: DataAction,
    recorder: ActivityRecorder,
    occurred_at: datetime,
) -> ResolvedScope:
    """Require ``action`` in the scope the resource actually declares."""
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


async def require_dataset_access(
    services: DataServices,
    repositories: Any,
    actor: ActorContext,
    dataset: Dataset,
    *,
    action: DataAction,
    recorder: ActivityRecorder,
    occurred_at: datetime,
) -> ResolvedScope:
    return await resolve_scope(
        services,
        repositories,
        actor,
        workspace_id=dataset.workspace_id,
        project_id=dataset.project_id,
        action=action,
        recorder=recorder,
        occurred_at=occurred_at,
    )


def dataset_capabilities(actor: ActorContext, dataset: Dataset) -> tuple[str, ...]:
    """Capabilities the *server* grants on this dataset, for UI rendering only.

    The frontend uses these to decide what to show. It is never the check: every
    operation re-evaluates the permission on the server.
    """
    if dataset.project_id:
        held = actor.project_capabilities(dataset.project_id)
        relevant = {
            "read": Permission.PROJECT_DATA_READ,
            "write": Permission.PROJECT_DATA_WRITE,
            "import": Permission.PROJECT_DATA_IMPORT,
            "download": Permission.PROJECT_DATA_DOWNLOAD,
            "delete": Permission.PROJECT_DATA_DELETE,
        }
    else:
        held = actor.workspace_capabilities(dataset.workspace_id)
        relevant = {
            "read": Permission.WORKSPACE_DATA_READ,
            "write": Permission.WORKSPACE_DATA_WRITE,
            "import": Permission.WORKSPACE_DATA_IMPORT,
            "download": Permission.WORKSPACE_DATA_DOWNLOAD,
            "delete": Permission.WORKSPACE_DATA_DELETE,
        }
    return tuple(sorted(name for name, permission in relevant.items() if permission in held))


__all__ = [
    "CREATE",
    "DELETE",
    "DOWNLOAD",
    "IMPORT",
    "READ",
    "WRITE",
    "DataAction",
    "DataServices",
    "ResolvedScope",
    "dataset_capabilities",
    "require_dataset_access",
    "resolve_scope",
]
