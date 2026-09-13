"""Workspace endpoints.

The listing is authoritative: it returns exactly the workspaces the caller may
access — their personal workspace plus the organization workspaces their
memberships reach. The client never assembles this list itself.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.authentication import CallerDep, RequestContextDep
from app.api.dependencies import ContainerDep
from app.api.v1.mapping import workspace_response
from app.api.v1.schemas.common import ERROR_RESPONSES
from app.api.v1.schemas.tenancy import WorkspaceCollection, WorkspaceResponse
from app.application.use_cases.tenancy.workspaces import (
    GetWorkspace,
    GetWorkspaceQuery,
    ListWorkspaces,
    ListWorkspacesQuery,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get(
    "",
    response_model=WorkspaceCollection,
    summary="Workspaces the caller may access",
    responses=ERROR_RESPONSES,
)
async def list_workspaces(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> WorkspaceCollection:
    views = await ListWorkspaces(container.tenancy_services()).execute(
        ListWorkspacesQuery(actor=caller.actor, request=context)
    )
    return WorkspaceCollection(items=[workspace_response(view) for view in views])


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceResponse,
    summary="One workspace",
    description="Returns 404 when the caller may not access the workspace, so an "
    "identifier alone reveals nothing about its existence.",
    responses=ERROR_RESPONSES,
)
async def get_workspace(
    workspace_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> WorkspaceResponse:
    view = await GetWorkspace(container.tenancy_services()).execute(
        GetWorkspaceQuery(actor=caller.actor, workspace_id=workspace_id, request=context)
    )
    return workspace_response(view)


__all__ = ["router"]
