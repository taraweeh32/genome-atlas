"""Projects, project membership and tenant isolation.

Organization membership is deliberately *not* project access: these tests pin
that separation, personal-workspace privacy, and the fact that an identifier
alone never opens a resource.
"""

from __future__ import annotations

import pytest

from app.application.repositories import Page
from app.application.use_cases.tenancy.memberships import (
    InviteMember,
    InviteMemberCommand,
    RespondToInvitation,
    RespondToInvitationCommand,
)
from app.application.use_cases.tenancy.projects import (
    AddProjectMember,
    AddProjectMemberCommand,
    ChangeProjectLifecycle,
    ChangeProjectLifecycleCommand,
    CreateProject,
    CreateProjectCommand,
    GetProject,
    GetProjectQuery,
    ListProjects,
    ListProjectsQuery,
    RemoveProjectMember,
    RemoveProjectMemberCommand,
    UpdateProject,
    UpdateProjectCommand,
)
from app.application.use_cases.tenancy.workspaces import (
    GetWorkspace,
    GetWorkspaceQuery,
    ListWorkspaces,
    ListWorkspacesQuery,
)
from app.domain.errors import AuthorizationError, NotFoundError
from app.domain.value_objects.enums import (
    OrganizationRole,
    ProjectRole,
    ProjectState,
    WorkspaceKind,
)
from tests.support.actors import actor_for, create_account
from tests.support.services import build_harness
from tests.tenancy.test_organizations_and_memberships import approved_organization

PAGE = Page(number=1, size=25)


async def personal_project(harness, user_id: str, name: str = "Personal Cohort"):
    workspace = await harness.repositories.workspaces.get_personal_for_user(user_id)
    return await CreateProject(harness.tenancy).execute(
        CreateProjectCommand(
            actor=await actor_for(harness, user_id),
            workspace_id=workspace.id,
            name=name,
            description=None,
            request=harness.request,
        )
    )


async def add_member(harness, organization_id: str, owner_id: str, email: str) -> str:
    user_id = await create_account(harness, email)
    invitation = await InviteMember(harness.tenancy).execute(
        InviteMemberCommand(
            actor=await actor_for(harness, owner_id),
            organization_id=organization_id,
            email=email,
            role=OrganizationRole.MEMBER,
            request=harness.request,
        )
    )
    await RespondToInvitation(harness.tenancy).execute(
        RespondToInvitationCommand(
            actor=await actor_for(harness, user_id),
            token=invitation.development_only_token,
            accept=True,
            request=harness.request,
        )
    )
    return user_id


async def test_workspace_listing_returns_only_reachable_workspaces() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.org")
    view = await approved_organization(harness, owner_id)
    outsider_id = await create_account(harness, "outsider@example.org")

    owner_workspaces = await ListWorkspaces(harness.tenancy).execute(
        ListWorkspacesQuery(actor=await actor_for(harness, owner_id), request=harness.request)
    )
    outsider_workspaces = await ListWorkspaces(harness.tenancy).execute(
        ListWorkspacesQuery(actor=await actor_for(harness, outsider_id), request=harness.request)
    )

    assert {item.workspace.kind for item in owner_workspaces} == {
        WorkspaceKind.PERSONAL,
        WorkspaceKind.ORGANIZATION,
    }
    assert {item.workspace.kind for item in outsider_workspaces} == {WorkspaceKind.PERSONAL}
    # The organization workspace is not readable by identifier either.
    with pytest.raises((NotFoundError, AuthorizationError)):
        await GetWorkspace(harness.tenancy).execute(
            GetWorkspaceQuery(
                actor=await actor_for(harness, outsider_id),
                workspace_id=view.workspace_id,
                request=harness.request,
            )
        )


async def test_a_personal_project_is_private_to_its_owner() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.org")
    other_id = await create_account(harness, "other@example.org")
    project = await personal_project(harness, owner_id)

    with pytest.raises((NotFoundError, AuthorizationError)):
        await GetProject(harness.tenancy).execute(
            GetProjectQuery(
                actor=await actor_for(harness, other_id),
                project_id=project.project.id,
                request=harness.request,
            )
        )
    listed = await ListProjects(harness.tenancy).execute(
        ListProjectsQuery(
            actor=await actor_for(harness, other_id), page=PAGE, request=harness.request
        )
    )
    assert listed.items == ()


async def test_a_project_cannot_be_created_in_someone_elses_workspace() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.org")
    other_id = await create_account(harness, "other@example.org")
    victim_workspace = await harness.repositories.workspaces.get_personal_for_user(owner_id)

    with pytest.raises((AuthorizationError, NotFoundError)):
        await CreateProject(harness.tenancy).execute(
            CreateProjectCommand(
                actor=await actor_for(harness, other_id),
                workspace_id=victim_workspace.id,
                name="Injected",
                description=None,
                request=harness.request,
            )
        )


async def test_organization_membership_alone_grants_no_project_access() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.org")
    view = await approved_organization(harness, owner_id)
    member_id = await add_member(harness, view.organization.id, owner_id, "member@example.org")

    project = await CreateProject(harness.tenancy).execute(
        CreateProjectCommand(
            actor=await actor_for(harness, owner_id),
            workspace_id=view.workspace_id,
            name="Rare Disease Cohort",
            description=None,
            request=harness.request,
        )
    )

    # Being in the organization is not being on the project.
    with pytest.raises((NotFoundError, AuthorizationError)):
        await GetProject(harness.tenancy).execute(
            GetProjectQuery(
                actor=await actor_for(harness, member_id),
                project_id=project.project.id,
                request=harness.request,
            )
        )

    await AddProjectMember(harness.tenancy).execute(
        AddProjectMemberCommand(
            actor=await actor_for(harness, owner_id),
            project_id=project.project.id,
            user_id=member_id,
            role=ProjectRole.ANALYST,
            request=harness.request,
        )
    )
    reachable = await GetProject(harness.tenancy).execute(
        GetProjectQuery(
            actor=await actor_for(harness, member_id),
            project_id=project.project.id,
            request=harness.request,
        )
    )
    assert reachable.role is ProjectRole.ANALYST


async def test_removing_a_project_member_withdraws_access_again() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.org")
    view = await approved_organization(harness, owner_id)
    member_id = await add_member(harness, view.organization.id, owner_id, "member@example.org")
    project = await CreateProject(harness.tenancy).execute(
        CreateProjectCommand(
            actor=await actor_for(harness, owner_id),
            workspace_id=view.workspace_id,
            name="Cardiology Cohort",
            description=None,
            request=harness.request,
        )
    )
    await AddProjectMember(harness.tenancy).execute(
        AddProjectMemberCommand(
            actor=await actor_for(harness, owner_id),
            project_id=project.project.id,
            user_id=member_id,
            role=ProjectRole.ANALYST,
            request=harness.request,
        )
    )

    await RemoveProjectMember(harness.tenancy).execute(
        RemoveProjectMemberCommand(
            actor=await actor_for(harness, owner_id),
            project_id=project.project.id,
            user_id=member_id,
            request=harness.request,
        )
    )

    with pytest.raises((NotFoundError, AuthorizationError)):
        await GetProject(harness.tenancy).execute(
            GetProjectQuery(
                actor=await actor_for(harness, member_id),
                project_id=project.project.id,
                request=harness.request,
            )
        )
    # The project itself is untouched by the membership change.
    assert await harness.repositories.projects.get(project.project.id) is not None


async def test_a_viewer_cannot_modify_the_project() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.org")
    view = await approved_organization(harness, owner_id)
    viewer_id = await add_member(harness, view.organization.id, owner_id, "viewer@example.org")
    project = await CreateProject(harness.tenancy).execute(
        CreateProjectCommand(
            actor=await actor_for(harness, owner_id),
            workspace_id=view.workspace_id,
            name="Read Only Cohort",
            description=None,
            request=harness.request,
        )
    )
    await AddProjectMember(harness.tenancy).execute(
        AddProjectMemberCommand(
            actor=await actor_for(harness, owner_id),
            project_id=project.project.id,
            user_id=viewer_id,
            role=ProjectRole.VIEWER,
            request=harness.request,
        )
    )
    viewer_actor = await actor_for(harness, viewer_id)

    with pytest.raises(AuthorizationError):
        await UpdateProject(harness.tenancy).execute(
            UpdateProjectCommand(
                actor=viewer_actor,
                project_id=project.project.id,
                name="Renamed by a viewer",
                description=None,
                request=harness.request,
            )
        )
    with pytest.raises(AuthorizationError):
        await ChangeProjectLifecycle(harness.tenancy).execute(
            ChangeProjectLifecycleCommand(
                actor=viewer_actor,
                project_id=project.project.id,
                target_state=ProjectState.ARCHIVED,
                reason=None,
                request=harness.request,
            )
        )


async def test_creator_and_owner_are_recorded_separately() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.org")
    view = await approved_organization(harness, owner_id)
    creator_id = await add_member(harness, view.organization.id, owner_id, "creator@example.org")
    await AddProjectMember(harness.tenancy).execute(
        AddProjectMemberCommand(
            actor=await actor_for(harness, owner_id),
            project_id=(
                await CreateProject(harness.tenancy).execute(
                    CreateProjectCommand(
                        actor=await actor_for(harness, owner_id),
                        workspace_id=view.workspace_id,
                        name="Owner Project",
                        description=None,
                        request=harness.request,
                    )
                )
            ).project.id,
            user_id=creator_id,
            role=ProjectRole.MANAGER,
            request=harness.request,
        )
    )

    project = await CreateProject(harness.tenancy).execute(
        CreateProjectCommand(
            actor=await actor_for(harness, creator_id),
            workspace_id=view.workspace_id,
            name="Created By A Member",
            description=None,
            request=harness.request,
        )
    )

    # The creator is recorded as the creator; ownership is a separate field and is
    # never inferred from whoever happened to create the project.
    assert project.project.created_by == creator_id
    assert project.project.owner_user_id is not None


async def test_archiving_and_reopening_a_project_follows_the_state_machine() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.org")
    project = await personal_project(harness, owner_id)
    actor = await actor_for(harness, owner_id)

    archived = await ChangeProjectLifecycle(harness.tenancy).execute(
        ChangeProjectLifecycleCommand(
            actor=actor,
            project_id=project.project.id,
            target_state=ProjectState.ARCHIVED,
            reason="cohort completed",
            request=harness.request,
        )
    )
    assert archived.project.state is ProjectState.ARCHIVED

    reopened = await ChangeProjectLifecycle(harness.tenancy).execute(
        ChangeProjectLifecycleCommand(
            actor=await actor_for(harness, owner_id),
            project_id=project.project.id,
            target_state=ProjectState.ACTIVE,
            reason=None,
            request=harness.request,
        )
    )
    assert reopened.project.state is ProjectState.ACTIVE
