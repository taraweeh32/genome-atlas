"""FastAPI dependency providers.

Routes resolve services from the single composition root stored on app state;
they never construct infrastructure themselves.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from app.application.container import Container
from app.application.use_cases.describe_scientific_capabilities import (
    DescribeScientificCapabilities,
)
from app.application.use_cases.get_readiness import GetReadiness
from app.core.correlation import require_correlation_id
from app.domain.errors import InfrastructureError
from app.domain.workspace.context import AuthorizationContext


def get_container(request: Request) -> Container:
    container: Container | None = getattr(request.app.state, "container", None)
    if container is None:
        raise InfrastructureError("application container is not initialized")
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


def get_readiness_use_case(container: ContainerDep) -> GetReadiness:
    return container.get_readiness()


def get_scientific_capabilities_use_case(
    container: ContainerDep,
) -> DescribeScientificCapabilities:
    return container.describe_scientific_capabilities()


def get_authorization_context() -> AuthorizationContext:
    """Authorization context propagated into every use case.

    Package 1 propagates an anonymous context. Authentication, workspace
    resolution and RBAC populate it in later packages; no route may invent an
    authenticated identity in the meantime.
    """
    return AuthorizationContext.anonymous()


def get_correlation_id_dep() -> str:
    return require_correlation_id()


AuthorizationContextDep = Annotated[AuthorizationContext, Depends(get_authorization_context)]
CorrelationIdDep = Annotated[str, Depends(get_correlation_id_dep)]
