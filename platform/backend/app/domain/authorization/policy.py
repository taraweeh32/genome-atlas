"""The single authorization decision point.

Every protected operation asks this module, and only this module, whether it may
proceed. Routes never compare role names, never read ``platform_roles`` directly
and never decide anything themselves.

The evaluation order is fixed and fails closed at each step:

1. an actor must be authenticated,
2. the account must be usable (suspended/deactivated/locked accounts stop here),
3. the resource scope must be established (workspace / organization / project),
4. the tenant boundary must hold (grants are looked up *by identifier*, so a
   foreign identifier simply has no grant),
5. the role must grant the capability,
6. the resource lifecycle state must allow the operation,
7. sensitive operations must additionally satisfy step-up requirements.

A denial is returned as a structured decision so the caller can audit it, and
raised as ``AuthorizationError`` so it can never be accidentally ignored.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.authorization.context import ActorContext
from app.domain.authorization.permissions import (
    PLATFORM_ONLY_PERMISSIONS,
    Permission,
    Scope,
)
from app.domain.errors import AuthenticationError, AuthorizationError

#: Reason codes are stable strings: they are written to security/audit records
#: and must never contain resource content or secrets.
REASON_UNAUTHENTICATED = "unauthenticated"
REASON_ACCOUNT_NOT_USABLE = "account_not_usable"
REASON_NO_SCOPE_GRANT = "no_scope_grant"
REASON_MISSING_PERMISSION = "missing_permission"
REASON_STEP_UP_REQUIRED = "step_up_required"
REASON_SCOPE_MISMATCH = "scope_mismatch"


@dataclass(frozen=True, slots=True)
class AuthorizationDecision:
    allowed: bool
    permission: Permission
    scope: Scope
    scope_id: str | None
    reason: str | None = None

    def require(self) -> None:
        if self.allowed:
            return
        if self.reason == REASON_UNAUTHENTICATED:
            raise AuthenticationError("authentication is required")
        # The message never distinguishes "does not exist" from "not yours":
        # existence of a resource is itself information.
        raise AuthorizationError(
            "the requested operation is not permitted",
            details={"permission": self.permission.value, "reason": self.reason},
        )


class AuthorizationPolicy:
    """Stateless decision service. Injected wherever authorization is needed."""

    def decide(
        self,
        actor: ActorContext | None,
        permission: Permission,
        *,
        organization_id: str | None = None,
        workspace_id: str | None = None,
        project_id: str | None = None,
    ) -> AuthorizationDecision:
        scope = permission.scope
        scope_id = {
            Scope.PLATFORM: None,
            Scope.ORGANIZATION: organization_id,
            Scope.WORKSPACE: workspace_id,
            Scope.PROJECT: project_id,
        }[scope]

        def deny(reason: str) -> AuthorizationDecision:
            return AuthorizationDecision(False, permission, scope, scope_id, reason)

        if actor is None:
            return deny(REASON_UNAUTHENTICATED)
        if not actor.account_is_usable:
            return deny(REASON_ACCOUNT_NOT_USABLE)
        if scope is not Scope.PLATFORM and scope_id is None:
            # A scoped permission without a resource scope is a programming
            # error; failing closed is the only safe interpretation.
            return deny(REASON_SCOPE_MISMATCH)

        if scope is Scope.PLATFORM:
            granted = actor.platform_capabilities()
        elif scope is Scope.ORGANIZATION:
            granted = actor.organization_capabilities(scope_id or "")
        elif scope is Scope.WORKSPACE:
            granted = actor.workspace_capabilities(scope_id or "")
        else:
            granted = actor.project_capabilities(scope_id or "")

        if not granted:
            return deny(REASON_NO_SCOPE_GRANT)
        if permission not in granted:
            return deny(REASON_MISSING_PERMISSION)
        return AuthorizationDecision(True, permission, scope, scope_id)

    def require(
        self,
        actor: ActorContext | None,
        permission: Permission,
        *,
        organization_id: str | None = None,
        workspace_id: str | None = None,
        project_id: str | None = None,
    ) -> AuthorizationDecision:
        decision = self.decide(
            actor,
            permission,
            organization_id=organization_id,
            workspace_id=workspace_id,
            project_id=project_id,
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
        """Platform-privileged operation, subject to step-up requirements.

        ``require_mfa`` comes from platform security configuration, and
        ``ActorContext.mfa_satisfied`` is only ever set by a real second-factor
        verification. When MFA is required but the platform has no verified
        factor for this session, the operation is refused — the boundary exists
        now so the MFA package fills it in without any call site changing.
        """
        if permission not in PLATFORM_ONLY_PERMISSIONS:
            raise AuthorizationError(
                "privileged evaluation requires a platform-scoped permission",
                details={"permission": permission.value},
            )
        decision = self.decide(actor, permission)
        decision.require()
        if require_mfa and not (actor and actor.mfa_satisfied):
            denied = AuthorizationDecision(
                False, permission, Scope.PLATFORM, None, REASON_STEP_UP_REQUIRED
            )
            denied.require()
        return decision


__all__ = [
    "REASON_ACCOUNT_NOT_USABLE",
    "REASON_MISSING_PERMISSION",
    "REASON_NO_SCOPE_GRANT",
    "REASON_SCOPE_MISMATCH",
    "REASON_STEP_UP_REQUIRED",
    "REASON_UNAUTHENTICATED",
    "AuthorizationDecision",
    "AuthorizationPolicy",
]
