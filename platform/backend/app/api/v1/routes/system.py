"""System endpoints: liveness, readiness and API metadata.

Thin transport: each handler resolves a use case or settings object and shapes a
response. No business rules here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from app import __version__
from app.api.dependencies import ContainerDep, get_readiness_use_case
from app.api.v1.schemas.common import ERROR_RESPONSES
from app.api.v1.schemas.system import (
    DependencyStatusResponse,
    HealthResponse,
    MetaResponse,
    ReadinessResponse,
)
from app.application.use_cases.get_readiness import GetReadiness
from app.domain.entities.base import utc_now

router = APIRouter(tags=["system"])


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Liveness probe",
    description="Reports that the process is running and able to serve HTTP. "
    "This is NOT a statement that dependencies are available.",
    responses=ERROR_RESPONSES,
)
async def get_health(container: ContainerDep) -> HealthResponse:
    return HealthResponse(
        status="ok",
        environment=container.environment.environment.value,
        version=__version__,
        checked_at=utc_now(),
    )


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description="Aggregates dependency probes. Returns 503 when a required "
    "dependency is unavailable so orchestration does not route traffic here.",
    responses=ERROR_RESPONSES,
)
async def get_ready(
    response: Response,
    use_case: Annotated[GetReadiness, Depends(get_readiness_use_case)],
) -> ReadinessResponse:
    report = await use_case.execute()
    if not report.ready:
        response.status_code = 503
    return ReadinessResponse(
        ready=report.ready,
        checked_at=report.checked_at,
        dependencies=[
            DependencyStatusResponse(
                name=probe.name,
                status=probe.status.value,
                required=probe.required,
                latency_ms=probe.latency_ms,
                detail=probe.detail,
            )
            for probe in report.dependencies
        ],
    )


@router.get(
    "/meta",
    response_model=MetaResponse,
    summary="API metadata",
    responses=ERROR_RESPONSES,
)
async def get_meta(container: ContainerDep) -> MetaResponse:
    return MetaResponse(
        name=container.environment.name,
        api_version=container.application.api_version,
        environment=container.environment.environment.value,
        version=__version__,
    )
