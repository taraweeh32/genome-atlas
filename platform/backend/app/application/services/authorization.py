"""Resolution of the effective authorization context, and guarded checks.

The transport layer supplies a session; this service turns it into an
``ActorContext`` by reading what the database actually contains. Nothing the
client sends contributes a grant.

Every denial is written to the security trail, because a stream of denials is a
security signal and losing it would leave probing invisible.
"""

from __future__ import annotations

from datetime import datetime

from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.domain.authorization.context import (
    ActorContext,
    OrganizationGrant,
    ProjectGrant,
    WorkspaceGrant,
)
from app.domain.authorization.permissions import Permission
from app.domain.authorization.policy import AuthorizationDecision, AuthorizationPolicy
from app.domain.identity.entities import Session, UserAccount
from app.domain.value_objects.enums import (
    ActorType,
    AuditOutcome,
    MembershipState,
    OrganizationState,
    ProjectRole,
    WorkspaceKind,
)


class AuthorizationService:
    """Resolves grants and evaluates permissions, recording every denial."""

    def __init__(self, policy: AuthorizationPolicy) -> None:
        self._policy = policy

    async def resolve(
        self,
        repositories,  # noqa: ANN001 - TransactionalRepositories protocol
        account: UserAccount,
        *,
        session: Session | None = None,
    ) -> ActorContext:
        platform_roles = await repositories.platform_roles.list_active_for_user(account.id)

        organization_grants: dict[str, OrganizationGrant] = {}
        for membership in await repositories.organization_memberships.list_for_user(account.id):
            organization = await repositories.organizations.get(membership.organization_id)
            if organization is None:
                continue
            organization_grants[membership.organization_id] = OrganizationGrant(
                organization_id=membership.organization_id,
                role=membership.role,
                membership_state=membership.state,
                organization_state=organization.state,
            )

        workspace_grants: dict[str, WorkspaceGrant] = {}
        for workspace in await repositories.workspaces.list_for_user(account.id):
            workspace_grants[workspace.id] = WorkspaceGrant(
                workspace_id=workspace.id,
                kind=workspace.kind,
                organization_id=workspace.organization_id,
                owner_user_id=workspace.owner_user_id,
                usable=workspace.is_usable,
            )

        project_grants: dict[str, ProjectGrant] = {}
        for membership in await repositories.project_memberships.list_for_user(account.id):
            project = await repositories.projects.get(membership.project_id)
            if project is None:
                continue
            project_grants[membership.project_id] = ProjectGrant(
                project_id=membership.project_id,
                workspace_id=project.workspace_id,
                role=membership.role,
                membership_state=membership.state,
                project_state=project.state,
            )
            # An organization administrator's reach over a project is evaluated
            # through the project's workspace, so make that workspace visible
            # even when the actor holds no project membership of their own.
            if project.workspace_id not in workspace_grants:
                workspace = await repositories.workspaces.get(project.workspace_id)
                if workspace is not None:
                    workspace_grants[workspace.id] = WorkspaceGrant(
                        workspace_id=workspace.id,
                        kind=workspace.kind,
                        organization_id=workspace.organization_id,
                        owner_user_id=workspace.owner_user_id,
                        usable=workspace.is_usable,
                    )

        return ActorContext(
            actor_id=account.id,
            actor_type=ActorType.USER,
            account_state=account.account_state,
            session_id=session.id if session else None,
            platform_roles=platform_roles,
            organizations=organization_grants,
            workspaces=workspace_grants,
            projects=project_grants,
            mfa_satisfied=bool(session and session.mfa_satisfied),
            reauthenticated_at_epoch=(
                session.reauthenticated_at.timestamp()
                if session and session.reauthenticated_at
                else None
            ),
        )

    async def ensure_project_scope(
        self,
        repositories,  # noqa: ANN001
        actor: ActorContext,
        project_id: str,
    ) -> ActorContext:
        """Add the addressed project to the context if the actor can reach it.

        Called before a project-scoped check so that an organization
        administrator's reach is evaluated even without a project membership. It
        adds *scope*, never permission: an unrelated project yields no grant and
        the subsequent check fails closed.
        """
        if project_id in actor.projects:
            return actor
        project = await repositories.projects.get(project_id)
        if project is None:
            return actor
        workspace = await repositories.workspaces.get(project.workspace_id)
        if workspace is None or workspace.kind is WorkspaceKind.PERSONAL:
            return actor
        organization = actor.organizations.get(workspace.organization_id or "")
        if organization is None or not organization.is_usable:
            return actor
        workspaces = dict(actor.workspaces)
        workspaces[workspace.id] = WorkspaceGrant(
            workspace_id=workspace.id,
            kind=workspace.kind,
            organization_id=workspace.organization_id,
            owner_user_id=workspace.owner_user_id,
            usable=workspace.is_usable,
        )
        projects = dict(actor.projects)
        projects[project.id] = ProjectGrant(
            project_id=project.id,
            workspace_id=project.workspace_id,
            # No project role of their own. The role value is inert because the
            # membership state below makes the grant unusable; only the
            # organization's administrative reach applies.
            role=ProjectRole.VIEWER,
            membership_state=MembershipState.REMOVED,
            project_state=project.state,
        )
        return ActorContext(
            actor_id=actor.actor_id,
            actor_type=actor.actor_type,
            account_state=actor.account_state,
            session_id=actor.session_id,
            platform_roles=actor.platform_roles,
            organizations=actor.organizations,
            workspaces=workspaces,
            projects=projects,
            mfa_satisfied=actor.mfa_satisfied,
            reauthenticated_at_epoch=actor.reauthenticated_at_epoch,
        )

    async def require(
        self,
        actor: ActorContext | None,
        permission: Permission,
        *,
        recorder: ActivityRecorder | None = None,
        occurred_at: datetime | None = None,
        organization_id: str | None = None,
        workspace_id: str | None = None,
        project_id: str | None = None,
    ) -> AuthorizationDecision:
        decision = self._policy.decide(
            actor,
            permission,
            organization_id=organization_id,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        if not decision.allowed and recorder is not None and occurred_at is not None:
            await recorder.security(
                event_kind="authorization.denied",
                outcome=AuditOutcome.DENIED,
                occurred_at=occurred_at,
                subject_user_id=actor.actor_id if actor else None,
                detail={
                    "permission": permission.value,
                    "reason": decision.reason,
                    "scope": decision.scope.value,
                    "scope_id": decision.scope_id,
                },
            )
        decision.require()
        return decision

    def require_privileged(
        self,
        actor: ActorContext | None,
        permission: Permission,
        *,
        require_mfa: bool,
    ) -> AuthorizationDecision:
        return self._policy.require_privileged(actor, permission, require_mfa=require_mfa)

    @staticmethod
    def organization_is_usable(state: OrganizationState) -> bool:
        return state in (OrganizationState.ACTIVE, OrganizationState.APPROVED)


__all__ = ["AuthorizationService"]
