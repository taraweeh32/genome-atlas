"""Project and project-membership endpoints.

Project access is a relationship of its own: belonging to an organization does not
by itself grant access to its projects. Personal-workspace projects stay private
to their owner.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.authentication import CallerDep, RequestContextDep
from app.api.dependencies import ContainerDep
from app.api.v1.mapping import (
    PageDep,
    page_meta,
    parse_enum,
    project_member_response,
    project_response,
)
from app.api.v1.schemas.common import ERROR_RESPONSES
from app.api.v1.schemas.tenancy import (
    ProjectCollection,
    ProjectCreatePayload,
    ProjectLifecyclePayload,
    ProjectMemberCollection,
    ProjectMemberPayload,
    ProjectMemberResponse,
    ProjectMemberRolePayload,
    ProjectResponse,
    ProjectUpdatePayload,
)
from app.application.use_cases.tenancy.projects import (
    AddProjectMember,
    AddProjectMemberCommand,
    ChangeProjectLifecycle,
    ChangeProjectLifecycleCommand,
    ChangeProjectMemberRole,
    ChangeProjectMemberRoleCommand,
    CreateProject,
    CreateProjectCommand,
    GetProject,
    GetProjectQuery,
    ListProjectMembers,
    ListProjectMembersQuery,
    ListProjects,
    ListProjectsQuery,
    RemoveProjectMember,
    RemoveProjectMemberCommand,
    UpdateProject,
    UpdateProjectCommand,
)
from app.domain.value_objects.enums import ProjectRole, ProjectState

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project",
    responses=ERROR_RESPONSES,
)
async def create_project(
    payload: ProjectCreatePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ProjectResponse:
    view = await CreateProject(container.tenancy_services()).execute(
        CreateProjectCommand(
            actor=caller.actor,
            workspace_id=payload.workspace_id,
            name=payload.name,
            description=payload.description,
            request=context,
        )
    )
    return project_response(view)


@router.get(
    "",
    response_model=ProjectCollection,
    summary="Projects the caller may access",
    responses=ERROR_RESPONSES,
)
async def list_projects(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
    workspace_id: Annotated[str | None, Query()] = None,
) -> ProjectCollection:
    result = await ListProjects(container.tenancy_services()).execute(
        ListProjectsQuery(
            actor=caller.actor, page=page, request=context, workspace_id=workspace_id
        )
    )
    return ProjectCollection(
        items=[project_response(view) for view in result.items], page=page_meta(result)
    )


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="One project",
    responses=ERROR_RESPONSES,
)
async def get_project(
    project_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ProjectResponse:
    view = await GetProject(container.tenancy_services()).execute(
        GetProjectQuery(actor=caller.actor, project_id=project_id, request=context)
    )
    return project_response(view)


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Update a project profile",
    responses=ERROR_RESPONSES,
)
async def update_project(
    project_id: str,
    payload: ProjectUpdatePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ProjectResponse:
    view = await UpdateProject(container.tenancy_services()).execute(
        UpdateProjectCommand(
            actor=caller.actor,
            project_id=project_id,
            name=payload.name,
            description=payload.description,
            request=context,
        )
    )
    return project_response(view)


@router.post(
    "/{project_id}/state",
    response_model=ProjectResponse,
    summary="Archive or reopen a project",
    description="A lifecycle transition, not a deletion: archiving preserves every "
    "dataset, analysis and historical record. Invalid transitions are rejected.",
    responses=ERROR_RESPONSES,
)
async def change_project_state(
    project_id: str,
    payload: ProjectLifecyclePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ProjectResponse:
    view = await ChangeProjectLifecycle(container.tenancy_services()).execute(
        ChangeProjectLifecycleCommand(
            actor=caller.actor,
            project_id=project_id,
            target_state=parse_enum(ProjectState, payload.state, field="state"),
            reason=payload.reason,
            request=context,
        )
    )
    return project_response(view)


@router.get(
    "/{project_id}/members",
    response_model=ProjectMemberCollection,
    summary="Project members",
    responses=ERROR_RESPONSES,
)
async def list_project_members(
    project_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
    page: PageDep,
) -> ProjectMemberCollection:
    result = await ListProjectMembers(container.tenancy_services()).execute(
        ListProjectMembersQuery(
            actor=caller.actor, project_id=project_id, page=page, request=context
        )
    )
    return ProjectMemberCollection(
        items=[project_member_response(item) for item in result.items], page=page_meta(result)
    )


@router.post(
    "/{project_id}/members",
    response_model=ProjectMemberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Grant a user access to a project",
    responses=ERROR_RESPONSES,
)
async def add_project_member(
    project_id: str,
    payload: ProjectMemberPayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ProjectMemberResponse:
    membership = await AddProjectMember(container.tenancy_services()).execute(
        AddProjectMemberCommand(
            actor=caller.actor,
            project_id=project_id,
            user_id=payload.user_id,
            role=parse_enum(ProjectRole, payload.role, field="role"),
            request=context,
        )
    )
    return project_member_response(membership)


@router.patch(
    "/{project_id}/members/{user_id}",
    response_model=ProjectMemberResponse,
    summary="Change a project member's role",
    responses=ERROR_RESPONSES,
)
async def change_project_member_role(
    project_id: str,
    user_id: str,
    payload: ProjectMemberRolePayload,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> ProjectMemberResponse:
    membership = await ChangeProjectMemberRole(container.tenancy_services()).execute(
        ChangeProjectMemberRoleCommand(
            actor=caller.actor,
            project_id=project_id,
            user_id=user_id,
            role=parse_enum(ProjectRole, payload.role, field="role"),
            request=context,
        )
    )
    return project_member_response(membership)


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a user's project access",
    responses=ERROR_RESPONSES,
)
async def remove_project_member(
    project_id: str,
    user_id: str,
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> None:
    await RemoveProjectMember(container.tenancy_services()).execute(
        RemoveProjectMemberCommand(
            actor=caller.actor, project_id=project_id, user_id=user_id, request=context
        )
    )


__all__ = ["router"]
