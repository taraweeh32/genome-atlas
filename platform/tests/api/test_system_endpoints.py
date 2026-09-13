"""API/transport tests for the system endpoints.

The application is built by the real factory (``create_app``) so middleware,
routing, error mapping and OpenAPI generation are genuinely exercised. Only the
composition root is replaced by a stub, so no live PostgreSQL/Redis/S3/scientific
subsystem is required. The stubs implement the same ports as production adapters.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.application.ports import DependencyProbe, DependencyStatus, HealthProbe
from app.application.use_cases.describe_scientific_capabilities import (
    DescribeScientificCapabilities,
)
from app.application.use_cases.get_readiness import GetReadiness
from app.core.app_config import get_application_settings
from app.core.environment import Environment, get_environment_settings
from app.domain.errors import NotFoundError, ScientificIntegrationError
from app.main import create_app
from app.scientific.adapters.development import DevelopmentScientificAdapter


@dataclass
class StubProbe:
    name: str
    status: DependencyStatus
    required: bool

    async def probe(self) -> DependencyProbe:
        return DependencyProbe(name=self.name, status=self.status, required=self.required)


class ExplodingProbe:
    name = "exploding"
    required = True

    async def probe(self) -> DependencyProbe:
        raise RuntimeError("probe blew up")


class StubContainer:
    """Stands in for the composition root, exposing the same accessors."""

    def __init__(self, probes: tuple[HealthProbe, ...]) -> None:
        self.environment = get_environment_settings()
        self.application = get_application_settings()
        self._probes = probes
        self.scientific = DevelopmentScientificAdapter(Environment.TEST)

    def get_readiness(self) -> GetReadiness:
        return GetReadiness(self._probes)

    def describe_scientific_capabilities(self) -> DescribeScientificCapabilities:
        return DescribeScientificCapabilities(self.scientific)


def build_client(probes: tuple[HealthProbe, ...]) -> TestClient:
    app = create_app()
    # Bypass lifespan: the stub container replaces real infrastructure wiring.
    app.state.container = StubContainer(probes)

    @app.get("/api/v1/_test/domain-error")
    async def _domain_error() -> None:
        raise NotFoundError("dataset not found", details={"dataset_id": "dts_x"})

    @app.get("/api/v1/_test/scientific-error")
    async def _scientific_error() -> None:
        raise ScientificIntegrationError("scientific subsystem unreachable")

    @app.get("/api/v1/_test/boom")
    async def _boom() -> None:
        raise RuntimeError("unexpected internal failure with secret=hunter2")

    return TestClient(app, raise_server_exceptions=False)


UP_PROBES = (
    StubProbe("postgresql", DependencyStatus.UP, True),
    StubProbe("redis", DependencyStatus.UP, True),
    StubProbe("object_storage", DependencyStatus.UP, True),
    StubProbe("scientific", DependencyStatus.NOT_CONFIGURED, False),
)


@pytest.fixture
def client() -> TestClient:
    return build_client(UP_PROBES)


# -- health / readiness ----------------------------------------------------


def test_health_is_liveness_only(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["environment"] == "test"
    # Liveness must not report dependency state.
    assert "dependencies" not in body


def test_readiness_reports_every_dependency(client: TestClient) -> None:
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert {item["name"] for item in body["dependencies"]} == {
        "postgresql",
        "redis",
        "object_storage",
        "scientific",
    }


def test_readiness_fails_when_required_dependency_is_down() -> None:
    probes = (
        StubProbe("postgresql", DependencyStatus.DOWN, True),
        StubProbe("redis", DependencyStatus.UP, True),
    )
    response = build_client(probes).get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["ready"] is False


def test_readiness_ignores_optional_dependency_outage() -> None:
    probes = (
        StubProbe("postgresql", DependencyStatus.UP, True),
        StubProbe("scientific", DependencyStatus.DOWN, False),
    )
    response = build_client(probes).get("/api/v1/ready")
    assert response.status_code == 200
    assert response.json()["ready"] is True


def test_readiness_survives_a_raising_probe() -> None:
    response = build_client((ExplodingProbe(),)).get("/api/v1/ready")
    assert response.status_code == 503
    dependency = response.json()["dependencies"][0]
    assert dependency["status"] == "down"


def test_readiness_when_container_missing() -> None:
    app = create_app()
    app.state.container = None
    response = TestClient(app, raise_server_exceptions=False).get("/api/v1/ready")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "infrastructure_error"


# -- error envelope --------------------------------------------------------


def test_domain_error_maps_to_stable_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/_test/domain-error")
    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert error["details"] == {"dataset_id": "dts_x"}
    assert error["correlation_id"]


def test_scientific_integration_error_maps_to_502(client: TestClient) -> None:
    response = client.get("/api/v1/_test/scientific-error")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "scientific_integration_error"


def test_unexpected_error_does_not_leak_internals(client: TestClient) -> None:
    response = client.get("/api/v1/_test/boom")
    assert response.status_code == 500
    body = response.text
    assert "hunter2" not in body
    assert "Traceback" not in body
    assert response.json()["error"]["code"] == "internal_error"


def test_unknown_route_uses_the_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


# -- correlation and security headers --------------------------------------


def test_correlation_id_is_generated_when_absent(client: TestClient) -> None:
    response = client.get("/api/v1/health")
    assert response.headers["x-correlation-id"]


def test_incoming_correlation_id_is_propagated(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Correlation-ID": "corr-123"})
    assert response.headers["x-correlation-id"] == "corr-123"


def test_security_headers_are_present(client: TestClient) -> None:
    headers = client.get("/api/v1/health").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert "x-frame-options" in headers


# -- metadata / OpenAPI ----------------------------------------------------


def test_meta_reports_api_version(client: TestClient) -> None:
    body = client.get("/api/v1/meta").json()
    assert body["api_version"] == "v1"
    assert body["environment"] == "test"


def test_openapi_document_is_generated(client: TestClient) -> None:
    document = client.get("/api/v1/openapi.json").json()
    assert document["info"]["title"]
    assert "/api/v1/health" in document["paths"]
    assert "/api/v1/ready" in document["paths"]
    assert "/api/v1/scientific/capabilities" in document["paths"]


# -- scientific boundary through transport ---------------------------------


def test_capabilities_endpoint_flags_the_development_adapter(client: TestClient) -> None:
    body = client.get("/api/v1/scientific/capabilities").json()
    assert body["is_development_adapter"] is True
    assert body["engine"]["engine_version"].endswith("development-only")
