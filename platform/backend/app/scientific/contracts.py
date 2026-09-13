"""SCIENTIFIC INTEGRATION CONTRACT (application side only).

This module is the *entire* surface through which the application talks to the
independently deployed scientific compute subsystem. It contains no scientific
algorithm: no VEP invocation, no normalization, no annotation, no ACMG rules, no
evidence computation, no population-frequency computation, no pipeline logic.

The contract assumes the engine runs **out of process**, on separate,
independently versioned scientific nodes.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable


# --------------------------------------------------------------------------
# Identity
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EngineIdentity:
    """Which scientific engine answered, and in which version."""

    engine_id: str
    engine_version: str
    build_revision: str | None = None


@dataclass(frozen=True, slots=True)
class EnvironmentIdentity:
    """The containerized scientific environment the engine ran in."""

    environment_id: str
    environment_version: str
    container_digest: str | None = None


@dataclass(frozen=True, slots=True)
class ReferenceResourceIdentity:
    """An independently versioned scientific reference resource."""

    resource_id: str
    resource_version: str
    genome_assembly: str | None = None
    checksum: str | None = None


@dataclass(frozen=True, slots=True)
class ScientificCapability:
    """One declared capability of the subsystem (e.g. an execution kind)."""

    capability_id: str
    capability_version: str
    description: str | None = None


@dataclass(frozen=True, slots=True)
class ScientificCapabilities:
    """Capability discovery result: what the subsystem can do, and as what."""

    engine: EngineIdentity
    environment: EnvironmentIdentity
    capabilities: tuple[ScientificCapability, ...]
    reference_resources: tuple[ReferenceResourceIdentity, ...]
    is_development_adapter: bool = False


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------


class ExecutionStatus(str, enum.Enum):
    ACCEPTED = "accepted"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ArtifactReference:
    """A pointer to a produced artifact. Artifacts are never inlined."""

    artifact_id: str
    kind: str
    storage_uri: str
    media_type: str | None = None
    size_bytes: int | None = None
    checksum: str | None = None


@dataclass(frozen=True, slots=True)
class ProvenanceMetadata:
    """Scientific provenance, distinct from operational logs and from audit."""

    engine: EngineIdentity
    environment: EnvironmentIdentity
    reference_resources: tuple[ReferenceResourceIdentity, ...]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    parameters_digest: str | None = None


@dataclass(frozen=True, slots=True)
class ScientificExecutionRequest:
    """A request for the subsystem to perform a declared capability.

    ``inputs`` carries artifact references and parameters only. The application
    does not describe *how* the computation should be performed.
    """

    capability_id: str
    capability_version: str | None
    correlation_id: str
    inputs: tuple[ArtifactReference, ...] = ()
    parameters: dict[str, Any] = field(default_factory=dict)
    requested_by_execution_id: str | None = None


@dataclass(frozen=True, slots=True)
class ScientificExecutionResponse:
    """The subsystem's structured answer. Never a scientific interpretation."""

    execution_id: str
    status: ExecutionStatus
    correlation_id: str
    artifacts: tuple[ArtifactReference, ...] = ()
    provenance: ProvenanceMetadata | None = None
    failure: ScientificFailure | None = None


@dataclass(frozen=True, slots=True)
class ScientificFailure:
    """Structured scientific/integration failure detail."""

    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------
# Gateway
# --------------------------------------------------------------------------


@runtime_checkable
class ScientificEngineGateway(Protocol):
    """Port implemented by every scientific adapter."""

    async def ping(self) -> None:
        """Raise ScientificIntegrationError when the subsystem is unreachable."""
        ...

    async def describe_capabilities(self) -> ScientificCapabilities: ...

    async def submit_execution(
        self, request: ScientificExecutionRequest
    ) -> ScientificExecutionResponse: ...

    async def get_execution(self, execution_id: str) -> ScientificExecutionResponse: ...

    async def close(self) -> None: ...
