"""The caller's own identity.

``GET /me`` is the frontend's only source of truth about the session. The client
never infers a signed-in state from local storage, and the capabilities returned
here are advisory: the server re-checks every operation.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.authentication import CallerDep, RequestContextDep
from app.api.dependencies import ContainerDep
from app.api.v1.routes.authentication import account_response, session_summary
from app.api.v1.schemas.common import ERROR_RESPONSES
from app.api.v1.schemas.identity import IdentityResponse

router = APIRouter(tags=["identity"])


@router.get(
    "/me",
    response_model=IdentityResponse,
    summary="The signed-in account and session",
    responses=ERROR_RESPONSES,
)
async def get_me(
    caller: CallerDep,
    container: ContainerDep,
    context: RequestContextDep,
) -> IdentityResponse:
    requires_reauthentication = container.sessions.requires_reauthentication(
        caller.session, moment=container.clock.now()
    )
    return IdentityResponse(
        account=account_response(caller.account),
        session=session_summary(caller.session),
        platform_roles=sorted(role.value for role in caller.actor.platform_roles),
        capabilities=sorted(p.value for p in caller.actor.platform_capabilities()),
        requires_reauthentication=requires_reauthentication,
    )


__all__ = ["router"]
