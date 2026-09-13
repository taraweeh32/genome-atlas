"""Schemas for the system endpoints (health, readiness, meta, scientific info)."""

from __future__ import annotations

from datetime import datetime

from pydantic import Field

from app.api.v1.schemas.common import ApiModel


class HealthResponse(ApiModel):
    status: str = Field(description="'ok' when the process can serve HTTP.")
    environment: str
    version: str
    checked_at: datetime


class DependencyStatusResponse(ApiModel):
    name: str
    status: str = Field(description="up | degraded | down | not_configured")
    required: bool
    latency_ms: float | None = None
    detail: str | None = None


class ReadinessResponse(ApiModel):
    ready: bool
    checked_at: datetime
    dependencies: list[DependencyStatusResponse]


class MetaResponse(ApiModel):
    name: str
    api_version: str
    environment: str
    version: str


class EngineIdentityResponse(ApiModel):
    engine_id: str
    engine_version: str
    build_revision: str | None = None


class EnvironmentIdentityResponse(ApiModel):
    environment_id: str
    environment_version: str
    container_digest: str | None = None


class ReferenceResourceResponse(ApiModel):
    resource_id: str
    resource_version: str
    genome_assembly: str | None = None
    checksum: str | None = None


class CapabilityResponse(ApiModel):
    capability_id: str
    capability_version: str
    description: str | None = None


class ScientificCapabilitiesResponse(ApiModel):
    engine: EngineIdentityResponse
    environment: EnvironmentIdentityResponse
    capabilities: list[CapabilityResponse]
    reference_resources: list[ReferenceResourceResponse]
    is_development_adapter: bool = Field(
        description="True when a DEVELOPMENT ONLY adapter answered. Never scientifically valid."
    )
