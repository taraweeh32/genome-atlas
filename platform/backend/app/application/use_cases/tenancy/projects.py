"""Projects and project memberships.

Rules the backend owns here:

* A project belongs to exactly one workspace, and creating one requires a
  create permission **in that workspace** — organization membership alone is
  never enough.
* Project access is a relationship of its own. An organization member sees no
  project until a project membership (or their organization's administrative
  reach) grants it.
* The creator is recorded permanently and separately from the owner, and every
  project keeps at least one active owner.
* Archiving is a reversible lifecycle transition, not a deletion; retention and
  deletion are a separate concern that later packages implement.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.tenancy.dependencies import TenancyServices
from app.domain.authorization.context import ActorContext
from app.domain.authorization.permissions import Permission
from app.domain.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.domain.events import EventType
from app.domain.lifecycle import require_transition
from app.domain.project.entities import Project, ProjectMembership, clean_project_name
from app.domain.value_objects.enums import (
    AuditOutcome,
    MembershipState,
    ProjectRole,
    ProjectState,
)
from app.infrastructure.persistence.repositories.base import new_id


@dataclass(frozen=True, slots=True)
class ProjectView:
    project: Project
    role: ProjectRole | None
    capabilities: tuple[str, ...]


def _view(actor: ActorContext, project: Project) -> ProjectView:
    return ProjectView(
        project=project,
        role=actor.project_role(project.id),
        capabilities=tuple(sorted(p.value for p in actor.project_capabilities(project.id))),
    )


@dataclass(frozen=True, slots=True)
class CreateProjectCommand:
    actor: ActorContext
    workspace_id: str
    name: str
    description: str | None
    request: RequestContext


class CreateProject:
    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, command: CreateProjectCommand) -> ProjectView:
        name = clean_project_name(command.name)
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            await self._services.authorization.require(
                command.actor,
                Permission.WORKSPACE_PROJECT_CREATE,
                recorder=recorder,
                occurred_at=now,
                workspace_id=command.workspace_id,
            )
            workspace = await repositories.workspaces.get(command.workspace_id)
            if workspace is None:
                raise NotFoundError("workspace", command.workspace_id)
            if not workspace.is_usable:
                raise ConflictError("this workspace is not currently usable")

            actor_id = command.actor.actor_id
            if actor_id is None:  # pragma: no cover - the permission check precedes this
                raise AuthorizationError("authentication is required")

            project = await repositories.projects.add(
                Project(
                    id=new_id("prj"),
                    workspace_id=workspace.id,
                    name=name,
                    description=command.description or None,
                    state=ProjectState.ACTIVE,
                    # Creator is historical fact; owner is accountable party.
                    created_by=actor_id,
                    owner_user_id=actor_id,
                )
            )
            membership = await repositories.project_memberships.add(
                ProjectMembership(
                    id=new_id("pmb"),
                    project_id=project.id,
                    user_id=actor_id,
                    role=ProjectRole.OWNER,
                    state=MembershipState.ACTIVE,
                    granted_by=actor_id,
                    joined_at=now,
                )
            )
            await recorder.audit(
                action="project.created",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=actor_id,
                resource_type="project",
                resource_id=project.id,
                organization_id=workspace.organization_id,
                workspace_id=workspace.id,
                project_id=project.id,
                new_state=project.state.value,
            )
            await recorder.audit(
                action="project.member_added",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=actor_id,
                resource_type="project_membership",
                resource_id=membership.id,
                workspace_id=workspace.id,
                project_id=project.id,
                detail={"role": ProjectRole.OWNER.value},
            )
            await recorder.event(
                event_type=EventType.PROJECT_CREATED,
                aggregate_type="project",
                aggregate_id=project.id,
                occurred_at=now,
                workspace_id=workspace.id,
                idempotency_suffix=project.id,
            )
        # The freshly created membership is not yet in the resolved context, so
        # report the owner role explicitly rather than showing no capabilities.
        return ProjectView(
            project=project,
            role=ProjectRole.OWNER,
            capabilities=tuple(
                sorted(p.value for p in command.actor.project_capabilities(project.id))
            ),
        )


@dataclass(frozen=True, slots=True)
class ListProjectsQuery:
    actor: ActorContext
    page: Page
    request: RequestContext
    workspace_id: str | None = None


class ListProjects:
    """Lists only projects inside workspaces the actor may read."""

    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, query: ListProjectsQuery) -> Paged[ProjectView]:
        actor = query.actor
        readable = tuple(
            workspace_id
            for workspace_id in actor.workspaces
            if Permission.WORKSPACE_READ in actor.workspace_capabilities(workspace_id)
            and (query.workspace_id is None or workspace_id == query.workspace_id)
        )
        if not readable:
            return Paged(items=(), total=0, page=query.page)
        async with self._services.unit_of_work.begin() as repositories:
            page = await repositories.projects.list_for_workspaces(readable, page=query.page)
        views = tuple(
            _view(actor, project)
            for project in page.items
            if Permission.PROJECT_READ in actor.project_capabilities(project.id)
        )
        return Paged(items=views, total=page.total, page=page.page)


@dataclass(frozen=True, slots=True)
class GetProjectQuery:
    actor: ActorContext
    project_id: str
    request: RequestContext


class GetProject:
    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, query: GetProjectQuery) -> ProjectView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            actor = await self._services.authorization.ensure_project_scope(
                repositories, query.actor, query.project_id
            )
            await self._services.authorization.require(
                actor,
                Permission.PROJECT_READ,
                recorder=recorder,
                occurred_at=now,
                project_id=query.project_id,
            )
            project = await repositories.projects.get(query.project_id)
            if project is None:
                raise NotFoundError("project", query.project_id)
        return _view(actor, project)


@dataclass(frozen=True, slots=True)
class UpdateProjectCommand:
    actor: ActorContext
    project_id: str
    name: str | None
    description: str | None
    request: RequestContext


class UpdateProject:
    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, command: UpdateProjectCommand) -> ProjectView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            actor = await self._services.authorization.ensure_project_scope(
                repositories, command.actor, command.project_id
            )
            await self._services.authorization.require(
                actor,
                Permission.PROJECT_UPDATE,
                recorder=recorder,
                occurred_at=now,
                project_id=command.project_id,
            )
            project = await repositories.projects.get(command.project_id)
            if project is None:
                raise NotFoundError("project", command.project_id)
            name = clean_project_name(command.name) if command.name is not None else project.name
            project = await repositories.projects.save(
                replace(
                    project,
                    name=name,
                    description=command.description
                    if command.description is not None
                    else project.description,
                )
            )
            await recorder.audit(
                action="project.updated",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=actor.actor_id,
                resource_type="project",
                resource_id=project.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
            )
        return _view(actor, project)


@dataclass(frozen=True, slots=True)
class ChangeProjectLifecycleCommand:
    actor: ActorContext
    project_id: str
    target_state: ProjectState
    reason: str | None
    request: RequestContext


class ChangeProjectLifecycle:
    """Archive or reopen a project. Archiving deletes nothing."""

    _PERMISSIONS = {
        ProjectState.ARCHIVED: Permission.PROJECT_ARCHIVE,
        ProjectState.ACTIVE: Permission.PROJECT_REOPEN,
    }
    _EVENTS = {
        ProjectState.ARCHIVED: EventType.PROJECT_ARCHIVED,
        ProjectState.ACTIVE: EventType.PROJECT_REOPENED,
    }

    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, command: ChangeProjectLifecycleCommand) -> ProjectView:
        permission = self._PERMISSIONS.get(command.target_state)
        if permission is None:
            raise ValidationError(
                "unsupported project lifecycle target",
                details={"field": "state", "allowed": sorted(s.value for s in self._PERMISSIONS)},
            )
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            actor = await self._services.authorization.ensure_project_scope(
                repositories, command.actor, command.project_id
            )
            await self._services.authorization.require(
                actor,
                permission,
                recorder=recorder,
                occurred_at=now,
                project_id=command.project_id,
            )
            project = await repositories.projects.get(command.project_id)
            if project is None:
                raise NotFoundError("project", command.project_id)
            previous = project.state
            target = require_transition("project", previous, command.target_state)
            project = await repositories.projects.save(
                replace(
                    project,
                    state=target,
                    archived_at=now if target is ProjectState.ARCHIVED else project.archived_at,
                    archived_by=(
                        actor.actor_id if target is ProjectState.ARCHIVED else project.archived_by
                    ),
                    reopened_at=now if target is ProjectState.ACTIVE else project.reopened_at,
                )
            )
            await recorder.audit(
                action=f"project.{target.value}",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=actor.actor_id,
                resource_type="project",
                resource_id=project.id,
                workspace_id=project.workspace_id,
                project_id=project.id,
                previous_state=previous.value,
                new_state=target.value,
                reason=command.reason,
                detail={"resources_preserved": True},
            )
            await recorder.event(
                event_type=self._EVENTS[target],
                aggregate_type="project",
                aggregate_id=project.id,
                occurred_at=now,
                workspace_id=project.workspace_id,
            )
        return _view(actor, project)


# --------------------------------------------------------------------------- #
# Project membership                                                          #
# --------------------------------------------------------------------------- #


async def _assert_not_last_project_owner(
    repositories,
    membership: ProjectMembership,
    *,
    operation: str,
) -> None:
    if membership.role is not ProjectRole.OWNER or not membership.is_active:
        return
    remaining = await repositories.project_memberships.count_active_with_role(
        membership.project_id, ProjectRole.OWNER.value
    )
    if remaining <= 1:
        raise ConflictError(
            "a project must always keep at least one active owner",
            details={"operation": operation, "role": ProjectRole.OWNER.value},
        )


@dataclass(frozen=True, slots=True)
class ListProjectMembersQuery:
    actor: ActorContext
    project_id: str
    page: Page
    request: RequestContext


class ListProjectMembers:
    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, query: ListProjectMembersQuery) -> Paged[ProjectMembership]:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            actor = await self._services.authorization.ensure_project_scope(
                repositories, query.actor, query.project_id
            )
            await self._services.authorization.require(
                actor,
                Permission.PROJECT_MEMBER_READ,
                recorder=recorder,
                occurred_at=now,
                project_id=query.project_id,
            )
            return await repositories.project_memberships.list_for_project(
                query.project_id, page=query.page
            )


@dataclass(frozen=True, slots=True)
class AddProjectMemberCommand:
    actor: ActorContext
    project_id: str
    user_id: str
    role: ProjectRole
    request: RequestContext


class AddProjectMember:
    """Grants project access. The candidate must be reachable in the workspace."""

    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, command: AddProjectMemberCommand) -> ProjectMembership:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            actor = await self._services.authorization.ensure_project_scope(
                repositories, command.actor, command.project_id
            )
            await self._services.authorization.require(
                actor,
                Permission.PROJECT_MEMBER_MANAGE,
                recorder=recorder,
                occurred_at=now,
                project_id=command.project_id,
            )
            project = await repositories.projects.get(command.project_id)
            if project is None:
                raise NotFoundError("project", command.project_id)
            workspace = await repositories.workspaces.get(project.workspace_id)
            if workspace is None:
                raise NotFoundError("workspace", project.workspace_id)
            candidate = await repositories.users.get(command.user_id)
            if candidate is None or not candidate.can_authenticate:
                raise NotFoundError("user", command.user_id)

            if workspace.organization_id is not None:
                # Only an active member of the owning organization may be added:
                # a project must not become a back door into the tenant.
                membership = await repositories.organization_memberships.get(
                    workspace.organization_id, command.user_id
                )
                if membership is None or not membership.is_active:
                    raise ConflictError(
                        "that person is not an active member of the owning organization"
                    )
            elif workspace.owner_user_id != command.user_id:
                # A personal workspace is private to its owner.
                raise ConflictError("a personal workspace project cannot be shared")

            existing = await repositories.project_memberships.get(
                command.project_id, command.user_id
            )
            if existing is not None and existing.is_active:
                raise ConflictError("that person is already a member of this project")
            if existing is None:
                result = await repositories.project_memberships.add(
                    ProjectMembership(
                        id=new_id("pmb"),
                        project_id=command.project_id,
                        user_id=command.user_id,
                        role=command.role,
                        state=MembershipState.ACTIVE,
                        granted_by=actor.actor_id,
                        joined_at=now,
                    )
                )
            else:
                state = require_transition("membership", existing.state, MembershipState.ACTIVE)
                result = await repositories.project_memberships.save(
                    replace(
                        existing,
                        state=state,
                        role=command.role,
                        granted_by=actor.actor_id,
                        joined_at=now,
                        left_at=None,
                    )
                )
            await recorder.audit(
                action="project.member_added",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=actor.actor_id,
                resource_type="project_membership",
                resource_id=result.id,
                organization_id=workspace.organization_id,
                workspace_id=workspace.id,
                project_id=command.project_id,
                detail={"role": command.role.value, "user_id": command.user_id},
            )
            await recorder.event(
                event_type=EventType.PROJECT_MEMBER_ADDED,
                aggregate_type="project",
                aggregate_id=command.project_id,
                occurred_at=now,
                workspace_id=workspace.id,
                payload={"user_id": command.user_id, "role": command.role.value},
            )
            return result


@dataclass(frozen=True, slots=True)
class ChangeProjectMemberRoleCommand:
    actor: ActorContext
    project_id: str
    user_id: str
    role: ProjectRole
    request: RequestContext


class ChangeProjectMemberRole:
    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, command: ChangeProjectMemberRoleCommand) -> ProjectMembership:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            actor = await self._services.authorization.ensure_project_scope(
                repositories, command.actor, command.project_id
            )
            await self._services.authorization.require(
                actor,
                Permission.PROJECT_MEMBER_ROLE_CHANGE,
                recorder=recorder,
                occurred_at=now,
                project_id=command.project_id,
            )
            membership = await repositories.project_memberships.get(
                command.project_id, command.user_id
            )
            if membership is None:
                raise NotFoundError("project_membership", command.user_id)
            if membership.role is command.role:
                return membership
            await _assert_not_last_project_owner(
                repositories, membership, operation="role_change"
            )
            previous_role = membership.role
            membership = await repositories.project_memberships.save(
                replace(membership, role=command.role)
            )
            await recorder.audit(
                action="project.member_role_changed",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=actor.actor_id,
                resource_type="project_membership",
                resource_id=membership.id,
                project_id=command.project_id,
                detail={
                    "previous_role": previous_role.value,
                    "role": command.role.value,
                    "user_id": command.user_id,
                },
            )
            await recorder.event(
                event_type=EventType.PROJECT_ROLE_CHANGED,
                aggregate_type="project",
                aggregate_id=command.project_id,
                occurred_at=now,
                payload={"user_id": command.user_id, "role": command.role.value},
            )
            return membership


@dataclass(frozen=True, slots=True)
class RemoveProjectMemberCommand:
    actor: ActorContext
    project_id: str
    user_id: str
    request: RequestContext


class RemoveProjectMember:
    """Ends project access. Nothing the member created is deleted."""

    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, command: RemoveProjectMemberCommand) -> None:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            actor = await self._services.authorization.ensure_project_scope(
                repositories, command.actor, command.project_id
            )
            await self._services.authorization.require(
                actor,
                Permission.PROJECT_MEMBER_MANAGE,
                recorder=recorder,
                occurred_at=now,
                project_id=command.project_id,
            )
            membership = await repositories.project_memberships.get(
                command.project_id, command.user_id
            )
            if membership is None or not membership.is_active:
                raise NotFoundError("project_membership", command.user_id)
            await _assert_not_last_project_owner(repositories, membership, operation="remove")
            state = require_transition("membership", membership.state, MembershipState.REMOVED)
            await repositories.project_memberships.save(
                replace(membership, state=state, left_at=now)
            )
            await recorder.audit(
                action="project.member_removed",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=actor.actor_id,
                resource_type="project_membership",
                resource_id=membership.id,
                project_id=command.project_id,
                previous_state=membership.state.value,
                new_state=state.value,
                detail={"user_id": command.user_id, "resources_preserved": True},
            )
            await recorder.event(
                event_type=EventType.PROJECT_MEMBER_REMOVED,
                aggregate_type="project",
                aggregate_id=command.project_id,
                occurred_at=now,
                payload={"user_id": command.user_id},
            )


__all__ = [
    "AddProjectMember",
    "AddProjectMemberCommand",
    "ChangeProjectLifecycle",
    "ChangeProjectLifecycleCommand",
    "ChangeProjectMemberRole",
    "ChangeProjectMemberRoleCommand",
    "CreateProject",
    "CreateProjectCommand",
    "GetProject",
    "GetProjectQuery",
    "ListProjectMembers",
    "ListProjectMembersQuery",
    "ListProjects",
    "ListProjectsQuery",
    "ProjectView",
    "RemoveProjectMember",
    "RemoveProjectMemberCommand",
    "UpdateProject",
    "UpdateProjectCommand",
]
