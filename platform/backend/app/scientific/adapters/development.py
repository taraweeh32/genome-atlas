"""DEVELOPMENT ONLY scientific adapter.

=============================================================================
THIS ADAPTER IS NOT SCIENTIFICALLY VALID.
It performs no genomic computation of any kind. It exists solely so that the
application's scientific *integration* (contract, correlation, artifact
references, provenance shape, failure handling) can be exercised without the
production scientific compute environment.

Its results must never be presented as scientific output, and it refuses to
initialize when APP_ENVIRONMENT=production.
=============================================================================
"""

from __future__ import annotations

import hashlib

from app.core.environment import Environment
from app.core.errors import ConfigurationError
from app.core.logging import get_logger
from app.domain.entities.base import utc_now
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
)

logger = get_logger(__name__)

DEVELOPMENT_ENGINE = EngineIdentity(
    engine_id="development-stub",
    engine_version="0.0.0-development-only",
    build_revision="not-scientifically-valid",
)
DEVELOPMENT_ENVIRONMENT = EnvironmentIdentity(
    environment_id="development-stub-environment",
    environment_version="0.0.0-development-only",
)


class DevelopmentScientificAdapter:
    """Deterministic, in-process stand-in behind the real scientific contract."""

    def __init__(self, environment: Environment) -> None:
        if environment is Environment.PRODUCTION:
            raise ConfigurationError(
                "the development scientific adapter must never be enabled in production",
                key="SCIENTIFIC_ADAPTER",
            )
        logger.warning(
            "development scientific adapter enabled - results are not scientifically valid",
            extra={"environment": environment.value},
        )
        self._executions: dict[str, ScientificExecutionResponse] = {}

    async def close(self) -> None:
        self._executions.clear()

    async def ping(self) -> None:
        return None

    async def describe_capabilities(self) -> ScientificCapabilities:
        return ScientificCapabilities(
            engine=DEVELOPMENT_ENGINE,
            environment=DEVELOPMENT_ENVIRONMENT,
            capabilities=(
                ScientificCapability(
                    capability_id="integration.echo",
                    capability_version="1",
                    description="DEVELOPMENT ONLY integration probe. Performs no analysis.",
                ),
            ),
            reference_resources=(
                ReferenceResourceIdentity(
                    resource_id="development-stub-reference",
                    resource_version="0.0.0-development-only",
                ),
            ),
            is_development_adapter=True,
        )

    async def submit_execution(
        self, request: ScientificExecutionRequest
    ) -> ScientificExecutionResponse:
        if request.capability_id != "integration.echo":
            raise ScientificIntegrationError(
                "the development adapter implements no scientific capability",
                details={"capability_id": request.capability_id},
            )
        # Deterministic identifier: same request -> same execution id.
        digest = hashlib.sha256(
            f"{request.capability_id}|{request.correlation_id}".encode()
        ).hexdigest()[:32]
        now = utc_now()
        response = ScientificExecutionResponse(
            execution_id=f"devexec_{digest}",
            status=ExecutionStatus.SUCCEEDED,
            correlation_id=request.correlation_id,
            artifacts=(
                ArtifactReference(
                    artifact_id=f"devart_{digest}",
                    kind="development.integration-probe",
                    storage_uri=f"memory://development/{digest}",
                    media_type="application/json",
                ),
            ),
            provenance=ProvenanceMetadata(
                engine=DEVELOPMENT_ENGINE,
                environment=DEVELOPMENT_ENVIRONMENT,
                reference_resources=(),
                started_at=now,
                completed_at=now,
                parameters_digest=digest,
            ),
        )
        self._executions[response.execution_id] = response
        return response

    async def get_execution(self, execution_id: str) -> ScientificExecutionResponse:
        try:
            return self._executions[execution_id]
        except KeyError as exc:
            raise ScientificIntegrationError(
                "unknown execution", details={"execution_id": execution_id}
            ) from exc
