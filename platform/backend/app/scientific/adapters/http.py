"""HTTP adapter to an independently deployed scientific compute node.

Transport only: it serializes contract objects, calls the remote node and maps
transport/remote failures into ScientificIntegrationError. It contains no
scientific logic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from app.core.logging import get_logger
from app.core.scientific_config import ScientificSettings
from app.domain.errors import ScientificIntegrationError
from app.scientific.contracts import (
    ArtifactReference,
    EngineIdentity,
    EnvironmentIdentity,
    ExecutionStatus,
    ProvenanceMetadata,
    ReferenceResourceIdentity,
    ScientificCapabilities,
    ScientificCapability,
    ScientificExecutionRequest,
    ScientificExecutionResponse,
    ScientificFailure,
)

logger = get_logger(__name__)


class HttpScientificAdapter:
    def __init__(self, settings: ScientificSettings) -> None:
        if not settings.service_base_url:  # defensive: config validation covers this
            raise ScientificIntegrationError("scientific service base URL is not configured")
        headers = {"Accept": "application/json"}
        if settings.service_token:
            headers["Authorization"] = f"Bearer {settings.service_token}"
        self._client = httpx.AsyncClient(
            base_url=settings.service_base_url.rstrip("/"),
            timeout=settings.request_timeout_seconds,
            headers=headers,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def ping(self) -> None:
        await self._request("GET", "/health")

    async def describe_capabilities(self) -> ScientificCapabilities:
        payload = await self._request("GET", "/capabilities")
        return _parse_capabilities(payload)

    async def submit_execution(
        self, request: ScientificExecutionRequest
    ) -> ScientificExecutionResponse:
        payload = await self._request("POST", "/executions", json=_serialize_request(request))
        return _parse_execution(payload)

    async def get_execution(self, execution_id: str) -> ScientificExecutionResponse:
        payload = await self._request("GET", f"/executions/{execution_id}")
        return _parse_execution(payload)

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self._client.request(method, path, **kwargs)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            # Remote detail is logged, never returned verbatim to API clients.
            logger.warning(
                "scientific subsystem returned an error",
                extra={"scientific_status": exc.response.status_code, "scientific_path": path},
            )
            raise ScientificIntegrationError(
                "the scientific subsystem reported a failure",
                details={"status": exc.response.status_code},
            ) from exc
        except httpx.HTTPError as exc:
            raise ScientificIntegrationError("the scientific subsystem is unreachable") from exc
        if response.status_code == 204:
            return {}
        parsed: dict[str, Any] = response.json()
        return parsed


# -- parsing ---------------------------------------------------------------


def _serialize_request(request: ScientificExecutionRequest) -> dict[str, Any]:
    return {
        "capability_id": request.capability_id,
        "capability_version": request.capability_version,
        "correlation_id": request.correlation_id,
        "inputs": [
            {"artifact_id": item.artifact_id, "kind": item.kind, "storage_uri": item.storage_uri}
            for item in request.inputs
        ],
        "parameters": request.parameters,
        "requested_by_execution_id": request.requested_by_execution_id,
    }


def _parse_engine(raw: dict[str, Any]) -> EngineIdentity:
    return EngineIdentity(
        engine_id=str(raw["engine_id"]),
        engine_version=str(raw["engine_version"]),
        build_revision=raw.get("build_revision"),
    )


def _parse_environment(raw: dict[str, Any]) -> EnvironmentIdentity:
    return EnvironmentIdentity(
        environment_id=str(raw["environment_id"]),
        environment_version=str(raw["environment_version"]),
        container_digest=raw.get("container_digest"),
    )


def _parse_resource(raw: dict[str, Any]) -> ReferenceResourceIdentity:
    return ReferenceResourceIdentity(
        resource_id=str(raw["resource_id"]),
        resource_version=str(raw["resource_version"]),
        genome_assembly=raw.get("genome_assembly"),
        checksum=raw.get("checksum"),
    )


def _parse_capabilities(raw: dict[str, Any]) -> ScientificCapabilities:
    try:
        return ScientificCapabilities(
            engine=_parse_engine(raw["engine"]),
            environment=_parse_environment(raw["environment"]),
            capabilities=tuple(
                ScientificCapability(
                    capability_id=str(item["capability_id"]),
                    capability_version=str(item["capability_version"]),
                    description=item.get("description"),
                )
                for item in raw.get("capabilities", [])
            ),
            reference_resources=tuple(
                _parse_resource(item) for item in raw.get("reference_resources", [])
            ),
            is_development_adapter=False,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ScientificIntegrationError("malformed scientific capability response") from exc


def _parse_execution(raw: dict[str, Any]) -> ScientificExecutionResponse:
    try:
        provenance_raw = raw.get("provenance")
        provenance = (
            ProvenanceMetadata(
                engine=_parse_engine(provenance_raw["engine"]),
                environment=_parse_environment(provenance_raw["environment"]),
                reference_resources=tuple(
                    _parse_resource(item) for item in provenance_raw.get("reference_resources", [])
                ),
                started_at=_parse_time(provenance_raw.get("started_at")),
                completed_at=_parse_time(provenance_raw.get("completed_at")),
                parameters_digest=provenance_raw.get("parameters_digest"),
            )
            if provenance_raw
            else None
        )
        failure_raw = raw.get("failure")
        failure = (
            ScientificFailure(
                code=str(failure_raw["code"]),
                message=str(failure_raw["message"]),
                retryable=bool(failure_raw.get("retryable", False)),
                details=dict(failure_raw.get("details", {})),
            )
            if failure_raw
            else None
        )
        return ScientificExecutionResponse(
            execution_id=str(raw["execution_id"]),
            status=ExecutionStatus(raw["status"]),
            correlation_id=str(raw["correlation_id"]),
            artifacts=tuple(
                ArtifactReference(
                    artifact_id=str(item["artifact_id"]),
                    kind=str(item["kind"]),
                    storage_uri=str(item["storage_uri"]),
                    media_type=item.get("media_type"),
                    size_bytes=item.get("size_bytes"),
                    checksum=item.get("checksum"),
                )
                for item in raw.get("artifacts", [])
            ),
            provenance=provenance,
            failure=failure,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ScientificIntegrationError("malformed scientific execution response") from exc


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ScientificIntegrationError("malformed timestamp in scientific response") from exc
