"""Transport-side authentication: session resolution, CSRF and actor context.

This module decides nothing about permissions. It establishes *who* is calling by
re-reading the session from the database on every request, and refuses unsafe
requests without a valid CSRF header. Authorization itself is evaluated by the
application layer against the resolved ``ActorContext``.

Nothing here trusts a client-supplied identity: no header, body field or query
parameter can name the actor.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from app.api.dependencies import ContainerDep
from app.application.container import Container
from app.application.services.context import RequestContext
from app.core.correlation import get_correlation_id
from app.domain.authorization.context import ActorContext
from app.domain.errors import AuthenticationError
from app.domain.identity.entities import Session, UserAccount
from app.domain.value_objects.enums import AuditChannel
from app.infrastructure.security.tokens import summarize_user_agent

#: Methods that may not be replayed cross-site without a CSRF token.
_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _client_address(request: Request) -> str | None:
    # A forwarded address is only trusted for rate limiting and hashing, never
    # for authorization.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def get_request_context(request: Request, container: ContainerDep) -> RequestContext:
    address = _client_address(request)
    ip_hash = container.tokens.hash_client_attribute(address)
    return RequestContext(
        correlation_id=get_correlation_id(),
        ip_hash=ip_hash,
        user_agent_summary=summarize_user_agent(request.headers.get("user-agent")),
        channel=AuditChannel.API,
        # A hash, so a rate-limit key never carries a raw address into Redis.
        rate_limit_key=ip_hash or "unknown",
    )


RequestContextDep = Annotated[RequestContext, Depends(get_request_context)]


@dataclass(frozen=True, slots=True)
class AuthenticatedCaller:
    account: UserAccount
    session: Session
    actor: ActorContext


async def _resolve(
    request: Request,
    container: Container,
    context: RequestContext,
) -> AuthenticatedCaller | None:
    token = request.cookies.get(container.application.security.session_cookie_name)
    if not token:
        return None
    now = container.clock.now()
    async with container.unit_of_work.begin() as repositories:
        resolved = await container.sessions.resolve(repositories, token, moment=now)
        if request.method in _UNSAFE_METHODS:
            # Verified before any state change is attempted.
            container.sessions.verify_csrf(
                resolved.session,
                request.headers.get(container.application.security.csrf_header_name),
            )
        actor = await container.authorization.resolve(
            repositories, resolved.account, session=resolved.session
        )
    return AuthenticatedCaller(
        account=resolved.account, session=resolved.session, actor=actor
    )


async def get_optional_caller(
    request: Request,
    container: ContainerDep,
    context: RequestContextDep,
) -> AuthenticatedCaller | None:
    """Resolves a caller when a valid session exists, otherwise ``None``.

    Used by endpoints that behave differently when signed in. An invalid or
    revoked session is treated as absent rather than as an error, but a missing
    CSRF token on an unsafe method still fails.
    """
    try:
        return await _resolve(request, container, context)
    except AuthenticationError:
        return None


async def get_caller(
    request: Request,
    container: ContainerDep,
    context: RequestContextDep,
) -> AuthenticatedCaller:
    caller = await _resolve(request, container, context)
    if caller is None:
        raise AuthenticationError("authentication is required")
    return caller


CallerDep = Annotated[AuthenticatedCaller, Depends(get_caller)]
OptionalCallerDep = Annotated["AuthenticatedCaller | None", Depends(get_optional_caller)]


__all__ = [
    "AuthenticatedCaller",
    "CallerDep",
    "OptionalCallerDep",
    "RequestContextDep",
    "get_caller",
    "get_optional_caller",
    "get_request_context",
]
