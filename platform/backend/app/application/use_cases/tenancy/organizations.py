"""Organization request, approval and lifecycle use cases.

Rules the backend owns here:

* Creating an organization is a **request**, not a creation, whenever platform
  approval is required. Only a platform role may decide it; an organization
  administrator can never approve an organization, not even their own.
* Approval is the moment the organization workspace and the requester's owner
  membership come into existence — in one transaction with the decision.
* A rejected request is retained forever (the lifecycle table has no exit).
* Suspension and deactivation change *reachability*, never data: no resource is
  deleted or transferred, which is why only the organization row changes state.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.application.repositories import Page, Paged
from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.application.use_cases.tenancy.dependencies import TenancyServices
from app.domain.authorization.context import ActorContext
from app.domain.authorization.permissions import Permission
from app.domain.errors import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.domain.events import EventType
from app.domain.lifecycle import require_transition
from app.domain.organization.entities import Organization, OrganizationMembership, normalize_slug
from app.domain.value_objects.enums import (
    AuditOutcome,
    MembershipState,
    OrganizationRole,
    OrganizationState,
    WorkspaceKind,
)
from app.domain.workspace.entities import Workspace
from app.infrastructure.persistence.repositories.base import new_id


@dataclass(frozen=True, slots=True)
class OrganizationView:
    organization: Organization
    workspace_id: str | None
    role: OrganizationRole | None
    capabilities: tuple[str, ...]


def _view(actor: ActorContext, organization: Organization, workspace_id: str | None) -> OrganizationView:
    return OrganizationView(
        organization=organization,
        workspace_id=workspace_id,
        role=actor.organization_role(organization.id),
        capabilities=tuple(
            sorted(p.value for p in actor.organization_capabilities(organization.id))
        ),
    )


@dataclass(frozen=True, slots=True)
class RequestOrganizationCommand:
    actor: ActorContext
    name: str
    slug: str
    description: str | None
    request: RequestContext


class RequestOrganization:
    """Any usable account may request an organization; nobody self-approves one."""

    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, command: RequestOrganizationCommand) -> OrganizationView:
        actor = command.actor
        if actor.actor_id is None or not actor.account_is_usable:
            # Requesting is an authenticated action, but needs no permission
            # beyond a usable account: an organization does not exist yet, so
            # there is no scope to hold a permission in.
            raise AuthenticationError("authentication is required")

        name = (command.name or "").strip()
        if not name:
            raise ValidationError("an organization name is required", details={"field": "name"})
        slug = normalize_slug(command.slug or command.name)
        now = self._services.clock.now()
        requires_approval = self._services.policy.organizations_require_platform_approval

        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            if await repositories.organizations.get_by_slug(slug) is not None:
                raise ConflictError(
                    "an organization with that identifier already exists",
                    details={"field": "slug"},
                )

            organization = Organization(
                id=new_id("org"),
                slug=slug,
                name=name,
                description=(command.description or None),
                state=OrganizationState.REQUESTED,
                requested_by=actor.actor_id,
                requested_at=now,
            )
            organization = await repositories.organizations.add(organization)
            workspace_id: str | None = None

            await recorder.audit(
                action="organization.requested",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=actor.actor_id,
                resource_type="organization",
                resource_id=organization.id,
                organization_id=organization.id,
                new_state=organization.state.value,
            )
            await recorder.event(
                event_type=EventType.ORGANIZATION_REQUESTED,
                aggregate_type="organization",
                aggregate_id=organization.id,
                occurred_at=now,
                idempotency_suffix=organization.id,
            )

            if not requires_approval:
                # Approval is disabled by deployment configuration, so the same
                # provisioning path runs immediately — never a different one.
                organization, workspace_id = await _provision_approved_organization(
                    repositories,
                    recorder,
                    organization=organization,
                    decided_by=actor.actor_id,
                    reason="platform_approval_not_required",
                    moment=now,
                )
        return _view(actor, organization, workspace_id)


async def _provision_approved_organization(
    repositories,
    recorder: ActivityRecorder,
    *,
    organization: Organization,
    decided_by: str | None,
    reason: str | None,
    moment,
) -> tuple[Organization, str]:
    """Approve, provision the workspace and seat the requester as owner.

    One transaction, so an approved organization can never exist without its
    workspace, and a workspace can never exist without an accountable owner.
    """
    approved_state = require_transition("organization", organization.state, OrganizationState.APPROVED)
    organization = await repositories.organizations.save(
        replace(
            organization,
            state=approved_state,
            approval_decided_by=decided_by,
            approval_decided_at=moment,
            approval_decision_reason=reason,
        )
    )
    await recorder.audit(
        action="organization.approved",
        outcome=AuditOutcome.SUCCESS,
        occurred_at=moment,
        actor_user_id=decided_by,
        resource_type="organization",
        resource_id=organization.id,
        organization_id=organization.id,
        previous_state=OrganizationState.REQUESTED.value,
        new_state=organization.state.value,
        reason=reason,
    )
    await recorder.event(
        event_type=EventType.ORGANIZATION_APPROVED,
        aggregate_type="organization",
        aggregate_id=organization.id,
        occurred_at=moment,
        idempotency_suffix="approved",
    )

    owner_user_id = organization.requested_by
    workspace = Workspace(
        id=new_id("wsp"),
        kind=WorkspaceKind.ORGANIZATION,
        name=organization.name,
        organization_id=organization.id,
        # The requester is the accountable owner; ``created_by`` records who
        # brought it into existence. They are the same person here and may
        # legitimately differ later.
        owner_user_id=owner_user_id,
        created_by=owner_user_id,
    )
    await repositories.workspaces.add(workspace)
    await recorder.audit(
        action="workspace.created",
        outcome=AuditOutcome.SUCCESS,
        occurred_at=moment,
        actor_user_id=decided_by,
        resource_type="workspace",
        resource_id=workspace.id,
        organization_id=organization.id,
        workspace_id=workspace.id,
        detail={"kind": WorkspaceKind.ORGANIZATION.value},
    )
    await recorder.event(
        event_type=EventType.WORKSPACE_CREATED,
        aggregate_type="workspace",
        aggregate_id=workspace.id,
        occurred_at=moment,
        workspace_id=workspace.id,
        idempotency_suffix=workspace.id,
    )

    if owner_user_id is not None:
        await repositories.organization_memberships.add(
            OrganizationMembership(
                id=new_id("omb"),
                organization_id=organization.id,
                user_id=owner_user_id,
                role=OrganizationRole.OWNER,
                state=MembershipState.ACTIVE,
                joined_at=moment,
            )
        )
        await recorder.audit(
            action="organization.member_added",
            outcome=AuditOutcome.SUCCESS,
            occurred_at=moment,
            actor_user_id=decided_by,
            resource_type="organization_membership",
            resource_id=owner_user_id,
            organization_id=organization.id,
            new_state=MembershipState.ACTIVE.value,
            detail={"role": OrganizationRole.OWNER.value},
        )

    active_state = require_transition("organization", organization.state, OrganizationState.ACTIVE)
    organization = await repositories.organizations.save(replace(organization, state=active_state))
    await recorder.audit(
        action="organization.activated",
        outcome=AuditOutcome.SUCCESS,
        occurred_at=moment,
        actor_user_id=decided_by,
        resource_type="organization",
        resource_id=organization.id,
        organization_id=organization.id,
        previous_state=OrganizationState.APPROVED.value,
        new_state=organization.state.value,
    )
    await recorder.event(
        event_type=EventType.ORGANIZATION_ACTIVATED,
        aggregate_type="organization",
        aggregate_id=organization.id,
        occurred_at=moment,
        idempotency_suffix="activated",
    )
    return organization, workspace.id


@dataclass(frozen=True, slots=True)
class ListMyOrganizationsQuery:
    actor: ActorContext
    page: Page
    request: RequestContext


class ListMyOrganizations:
    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, query: ListMyOrganizationsQuery) -> Paged[OrganizationView]:
        async with self._services.unit_of_work.begin() as repositories:
            page = await repositories.organizations.list_for_user(
                query.actor.actor_id or "", page=query.page
            )
            views = []
            for organization in page.items:
                workspace = await repositories.workspaces.get_for_organization(organization.id)
                views.append(_view(query.actor, organization, workspace.id if workspace else None))
        return Paged(items=tuple(views), total=page.total, page=page.page)


@dataclass(frozen=True, slots=True)
class GetOrganizationQuery:
    actor: ActorContext
    organization_id: str
    request: RequestContext


class GetOrganization:
    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, query: GetOrganizationQuery) -> OrganizationView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            await self._authorize(recorder, query, now)
            organization = await repositories.organizations.get(query.organization_id)
            if organization is None:
                raise NotFoundError("organization", query.organization_id)
            workspace = await repositories.workspaces.get_for_organization(organization.id)
        return _view(query.actor, organization, workspace.id if workspace else None)

    async def _authorize(
        self, recorder: ActivityRecorder, query: GetOrganizationQuery, now
    ) -> None:
        if Permission.PLATFORM_ORGANIZATION_READ_ANY in query.actor.platform_capabilities():
            return
        await self._services.authorization.require(
            query.actor,
            Permission.ORGANIZATION_READ,
            recorder=recorder,
            occurred_at=now,
            organization_id=query.organization_id,
        )


@dataclass(frozen=True, slots=True)
class UpdateOrganizationCommand:
    actor: ActorContext
    organization_id: str
    name: str | None
    description: str | None
    expected_version: int
    request: RequestContext


class UpdateOrganization:
    """Descriptive fields only. The slug is an identity and never changes."""

    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, command: UpdateOrganizationCommand) -> OrganizationView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            await self._services.authorization.require(
                command.actor,
                Permission.ORGANIZATION_UPDATE,
                recorder=recorder,
                occurred_at=now,
                organization_id=command.organization_id,
            )
            organization = await repositories.organizations.get(command.organization_id)
            if organization is None:
                raise NotFoundError("organization", command.organization_id)
            name = (command.name or organization.name).strip()
            if not name:
                raise ValidationError("an organization name is required", details={"field": "name"})
            organization = await repositories.organizations.save(
                replace(
                    organization,
                    name=name,
                    description=command.description
                    if command.description is not None
                    else organization.description,
                    version=command.expected_version,
                )
            )
            await recorder.audit(
                action="organization.updated",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="organization",
                resource_id=organization.id,
                organization_id=organization.id,
            )
            workspace = await repositories.workspaces.get_for_organization(organization.id)
        return _view(command.actor, organization, workspace.id if workspace else None)


@dataclass(frozen=True, slots=True)
class ListOrganizationRequestsQuery:
    actor: ActorContext
    page: Page
    request: RequestContext


class ListOrganizationRequests:
    """Platform review queue."""

    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, query: ListOrganizationRequestsQuery) -> Paged[Organization]:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, query.request)
            await self._services.authorization.require(
                query.actor,
                Permission.PLATFORM_ORGANIZATION_REVIEW,
                recorder=recorder,
                occurred_at=now,
            )
            return await repositories.organizations.list_by_states(
                (OrganizationState.REQUESTED, OrganizationState.PENDING), page=query.page
            )


@dataclass(frozen=True, slots=True)
class DecideOrganizationRequestCommand:
    actor: ActorContext
    organization_id: str
    approve: bool
    reason: str | None
    request: RequestContext


class DecideOrganizationRequest:
    """Platform-only approval or rejection of an organization request."""

    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, command: DecideOrganizationRequestCommand) -> OrganizationView:
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            await self._services.authorization.require(
                command.actor,
                Permission.PLATFORM_ORGANIZATION_APPROVE,
                recorder=recorder,
                occurred_at=now,
            )
            organization = await repositories.organizations.get(command.organization_id)
            if organization is None:
                raise NotFoundError("organization", command.organization_id)
            if not organization.is_under_review:
                raise ConflictError(
                    "this organization request has already been decided",
                    details={"state": organization.state.value},
                )

            if command.approve:
                organization, workspace_id = await _provision_approved_organization(
                    repositories,
                    recorder,
                    organization=organization,
                    decided_by=command.actor.actor_id,
                    reason=command.reason,
                    moment=now,
                )
            else:
                if not (command.reason or "").strip():
                    raise ValidationError(
                        "a rejection reason is required", details={"field": "reason"}
                    )
                rejected = require_transition(
                    "organization", organization.state, OrganizationState.REJECTED
                )
                organization = await repositories.organizations.save(
                    replace(
                        organization,
                        state=rejected,
                        approval_decided_by=command.actor.actor_id,
                        approval_decided_at=now,
                        approval_decision_reason=command.reason,
                    )
                )
                workspace_id = None
                await recorder.audit(
                    action="organization.rejected",
                    outcome=AuditOutcome.SUCCESS,
                    occurred_at=now,
                    actor_user_id=command.actor.actor_id,
                    resource_type="organization",
                    resource_id=organization.id,
                    organization_id=organization.id,
                    new_state=organization.state.value,
                    reason=command.reason,
                )
                await recorder.event(
                    event_type=EventType.ORGANIZATION_REJECTED,
                    aggregate_type="organization",
                    aggregate_id=organization.id,
                    occurred_at=now,
                    idempotency_suffix="rejected",
                )
        return _view(command.actor, organization, workspace_id)


@dataclass(frozen=True, slots=True)
class ChangeOrganizationLifecycleCommand:
    actor: ActorContext
    organization_id: str
    target_state: OrganizationState
    reason: str | None
    request: RequestContext


class ChangeOrganizationLifecycle:
    """Suspend, reactivate or deactivate an organization. Data is never touched."""

    _EVENTS = {
        OrganizationState.SUSPENDED: EventType.ORGANIZATION_SUSPENDED,
        OrganizationState.ACTIVE: EventType.ORGANIZATION_REACTIVATED,
        OrganizationState.DEACTIVATED: EventType.ORGANIZATION_DEACTIVATED,
    }

    def __init__(self, services: TenancyServices) -> None:
        self._services = services

    async def execute(self, command: ChangeOrganizationLifecycleCommand) -> OrganizationView:
        if command.target_state not in self._EVENTS:
            raise ValidationError(
                "unsupported organization lifecycle target",
                details={"field": "state", "allowed": sorted(s.value for s in self._EVENTS)},
            )
        now = self._services.clock.now()
        async with self._services.unit_of_work.begin() as repositories:
            recorder = ActivityRecorder(repositories, command.request)
            await self._services.authorization.require(
                command.actor,
                Permission.PLATFORM_ORGANIZATION_LIFECYCLE,
                recorder=recorder,
                occurred_at=now,
            )
            organization = await repositories.organizations.get(command.organization_id)
            if organization is None:
                raise NotFoundError("organization", command.organization_id)
            previous = organization.state
            target = require_transition("organization", previous, command.target_state)
            organization = await repositories.organizations.save(
                replace(
                    organization,
                    state=target,
                    suspended_at=now if target is OrganizationState.SUSPENDED else None,
                    deactivated_at=now if target is OrganizationState.DEACTIVATED else None,
                )
            )
            await recorder.audit(
                action=f"organization.{target.value}",
                outcome=AuditOutcome.SUCCESS,
                occurred_at=now,
                actor_user_id=command.actor.actor_id,
                resource_type="organization",
                resource_id=organization.id,
                organization_id=organization.id,
                previous_state=previous.value,
                new_state=target.value,
                reason=command.reason,
                # Stated explicitly in the trail: reachability changed, nothing
                # was deleted or transferred.
                detail={"resources_preserved": True},
            )
            await recorder.event(
                event_type=self._EVENTS[target],
                aggregate_type="organization",
                aggregate_id=organization.id,
                occurred_at=now,
            )
            workspace = await repositories.workspaces.get_for_organization(organization.id)
        return _view(command.actor, organization, workspace.id if workspace else None)


__all__ = [
    "ChangeOrganizationLifecycle",
    "ChangeOrganizationLifecycleCommand",
    "DecideOrganizationRequest",
    "DecideOrganizationRequestCommand",
    "GetOrganization",
    "GetOrganizationQuery",
    "ListMyOrganizations",
    "ListMyOrganizationsQuery",
    "ListOrganizationRequests",
    "ListOrganizationRequestsQuery",
    "OrganizationView",
    "RequestOrganization",
    "RequestOrganizationCommand",
    "UpdateOrganization",
    "UpdateOrganizationCommand",
]
