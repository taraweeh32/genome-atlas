"""Workspace queries.

A workspace is never created by a client request in Package 3: a personal
workspace is provisioned with the account, and an organization workspace is
provisioned when the organization is approved. This module therefore only reads,
and it reads only what the actor's grants actually cover.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.tenancy.dependencies import TenancyServices
from app.domain.authorization.context import ActorContext
from app.domain.authorization.permissions import Permission
from app.domain.errors import AuthorizationError, NotFoundError
from app.domain.workspace.entities import Workspace


@dataclass(frozen=True, slots=True)
class ListWorkspacesQuery:
    actor: ActorContext
    request: RequestContext


@dataclass(frozen=True, slots=True)
class WorkspaceView:
    workspace: Workspace
    #: Permissions the actor holds in this workspace, so the UI can enable or
    #: hide controls without guessing. The backend still re-checks every call.
    capabilities: tuple[str, ...]


class ListWorkspaces:
    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, query: ListWorkspacesQuery) -> tuple[WorkspaceView, ...]:
        actor = query.actor
        async with self._services.unit_of_work.begin() as repositories:
            workspaces = await repositories.workspaces.list_for_user(actor.actor_id)
        views: list[WorkspaceView] = []
        for workspace in workspaces:
            capabilities = actor.workspace_capabilities(workspace.id)
            if Permission.WORKSPACE_READ not in capabilities:
                # A row the actor may not read is not returned, and its
                # existence is not hinted at either.
                continue
            views.append(
                WorkspaceView(
                    workspace=workspace,
                    capabilities=tuple(sorted(p.value for p in capabilities)),
                )
            )
        return tuple(views)


@dataclass(frozen=True, slots=True)
class GetWorkspaceQuery:
    actor: ActorContext
    workspace_id: str
    request: RequestContext


class GetWorkspace:
    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, query: GetWorkspaceQuery) -> WorkspaceView:
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            try:
                await self._services.authorization.require(
                    query.actor,
                    Permission.WORKSPACE_READ,
                    recorder=recorder,
                    occurred_at=self._services.clock.now(),
                    workspace_id=query.workspace_id,
                )
            except AuthorizationError as denial:
                # The refusal is still recorded as a security event above; the
                # caller is told nothing about whether the workspace exists.
                raise NotFoundError("the workspace was not found") from denial
            workspace = await repositories.workspaces.get(query.workspace_id)
        if workspace is None:
            raise NotFoundError("workspace", query.workspace_id)
        return WorkspaceView(
            workspace=workspace,
            capabilities=tuple(
                sorted(p.value for p in query.actor.workspace_capabilities(workspace.id))
            ),
        )


__all__ = [
    "GetWorkspace",
    "GetWorkspaceQuery",
    "ListWorkspaces",
    "ListWorkspacesQuery",
    "WorkspaceView",
]
