"""Scientific integration endpoints.

These endpoints expose the scientific subsystem's *declared identity and
capabilities* only. No scientific computation is triggered or implemented here.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import AuthorizationContextDep, get_scientific_capabilities_use_case
from app.api.v1.schemas.common import ERROR_RESPONSES
from app.api.v1.schemas.system import (
    CapabilityResponse,
    EngineIdentityResponse,
    EnvironmentIdentityResponse,
    ReferenceResourceResponse,
    ScientificCapabilitiesResponse,
)
from app.application.use_cases.describe_scientific_capabilities import (
    DescribeScientificCapabilities,
)

router = APIRouter(prefix="/scientific", tags=["scientific"])


@router.get(
    "/capabilities",
    response_model=ScientificCapabilitiesResponse,
    summary="Describe the scientific subsystem",
    description="Relays the engine identity, environment identity, reference-resource "
    "identity and declared capabilities reported by the independently deployed "
    "scientific compute subsystem.",
    responses=ERROR_RESPONSES,
)
async def describe_capabilities(
    _: AuthorizationContextDep,
    use_case: Annotated[
        DescribeScientificCapabilities, Depends(get_scientific_capabilities_use_case)
    ],
) -> ScientificCapabilitiesResponse:
    capabilities = await use_case.execute()
    return ScientificCapabilitiesResponse(
        engine=EngineIdentityResponse(
            engine_id=capabilities.engine.engine_id,
            engine_version=capabilities.engine.engine_version,
            build_revision=capabilities.engine.build_revision,
        ),
        environment=EnvironmentIdentityResponse(
            environment_id=capabilities.environment.environment_id,
            environment_version=capabilities.environment.environment_version,
            container_digest=capabilities.environment.container_digest,
        ),
        capabilities=[
            CapabilityResponse(
                capability_id=item.capability_id,
                capability_version=item.capability_version,
                description=item.description,
            )
            for item in capabilities.capabilities
        ],
        reference_resources=[
            ReferenceResourceResponse(
                resource_id=item.resource_id,
                resource_version=item.resource_version,
                genome_assembly=item.genome_assembly,
                checksum=item.checksum,
            )
            for item in capabilities.reference_resources
        ],
        is_development_adapter=capabilities.is_development_adapter,
    )
