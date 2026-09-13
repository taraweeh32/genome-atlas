"""API/transport tests for the system endpoints.

These exercise the real FastAPI app with stubbed infrastructure so that routing,
health vs readiness semantics, the structured error envelope and correlation-ID
propagation are genuinely verified. No assertion is trivially true.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.ports import DependencyProbe, DependencyStatus, HealthProbe
from app.application.use_cases.get_readiness import GetReadiness
from app.domain.errors import AuthorizationError, NotFoundError


class StubProbe(HealthProbe):
    """Deterministic probe standing in for real infrastructure."""

    def __init__(
        self,
        name: str,
        status: DependencyStatus,
        *,
        required: bool = True,
        raises: bool = False,
    ) -> None:
        self._name = name
        self._status = status
        self._required = required
        self._raises = raises

    @property
    def name(self) -> str:
        return self._name

    @property
    def required(self) -> bool:
        return self._required

    async def probe(self) -> DependencyProbe:
        if self._raises:
            raise RuntimeError("postgresql://user:secret@10.0.0.4:5432 refused the connection")
        return DependencyProbe(
            name=self._name,
            status=self._status,
            required=self._required,
            latency_ms=1.5,
        )


class StubContainer:
    """Container substitute: same surface the routes depend on, no real clients."""

    def __init__(self, probes: tuple[HealthProbe, ...]) -> None:
        self._probes = probes
        from app.core.app_config import get_application_settings
        from app.core.environment import get_environment_settings

        self.environment = get_environment_settings()
        self.application = get_application_settings()

    def get_readiness(self) -> GetReadiness:
        return GetReadiness(self._probes)


def build_client(probes: tuple[HealthProbe, ...]) -> TestClient:
    """Build the real app, then replace only the container on app state."""
    from app.api.dependencies import get_container
    from app.main import create_app

    app: FastAPI = create_app()
    container = StubContainer(probes)
    app.dependency_overrides[get_container] = lambda: container
    # TestClient(...) would run lifespan (and connect real infrastructure), so
    # the context manager is deliberately not used here.
    return TestClient(app)


@pytest.fixture
def healthy_client(clear_settings_cache: None) -> Iterator[TestClient]:
    client = build_client(
        (
            StubProbe("postgresql", DependencyStatus.UP),
            StubProbe("redis", DependencyStatus.UP),
            StubProbe("object_storage", DependencyStatus.UP),
            StubProbe("scientific", DependencyStatus.NOT_CONFIGURED, required=False),
        )
    )
    yield client
    client.close()


class TestHealth:
    def test_health_reports_liveness_only(self, healthy_client: TestClient) -> None:
        response = healthy_client.get("/api/v1/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["environment"] == "test"
        # Liveness must not carry dependency state; that is readiness' job.
        assert "dependencies" not in body

    def test_health_stays_ok_when_a_dependency_is_down(self, clear_settings_cache: None) -> None:
        client = build_client((StubProbe("postgresql", DependencyStatus.DOWN),))
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/ready").status_code == 503


class TestReadiness:
    def test_ready_when_all_required_dependencies_are_up(self, healthy_client: TestClient) -> None:
        response = healthy_client.get("/api/v1/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["ready"] is True
        assert {item["name"] for item in body["dependencies"]} == {
            "postgresql",
            "redis",
            "object_storage",
            "scientific",
        }

    def test_optional_dependency_does_not_block_readiness(self, clear_settings_cache: None) -> None:
        client = build_client(
            (
                StubProbe("postgresql", DependencyStatus.UP),
                StubProbe("scientific", DependencyStatus.DOWN, required=False),
            )
        )
        response = client.get("/api/v1/ready")
        assert response.status_code == 200
        assert response.json()["ready"] is True

    def test_required_dependency_down_returns_503(self, clear_settings_cache: None) -> None:
        client = build_client(
            (
                StubProbe("postgresql", DependencyStatus.UP),
                StubProbe("redis", DependencyStatus.DOWN),
            )
        )
        response = client.get("/api/v1/ready")
        assert response.status_code == 503
        assert response.json()["ready"] is False

    def test_probe_exception_is_contained_and_leaks_nothing(
        self, clear_settings_cache: None
    ) -> None:
        client = build_client((StubProbe("postgresql", DependencyStatus.UP, raises=True),))
        response = client.get("/api/v1/ready")
        assert response.status_code == 503
        payload = response.text
        # A raising probe must degrade readiness, never expose credentials or hosts.
        assert "secret" not in payload
        assert "10.0.0.4" not in payload


class TestCorrelationId:
    def test_supplied_correlation_id_is_echoed(self, healthy_client: TestClient) -> None:
        response = healthy_client.get(
            "/api/v1/health", headers={"X-Correlation-ID": "corr-supplied"}
        )
        assert response.headers["X-Correlation-ID"] == "corr-supplied"

    def test_correlation_id_is_generated_when_absent(self, healthy_client: TestClient) -> None:
        response = healthy_client.get("/api/v1/health")
        assert response.headers.get("X-Correlation-ID")


class TestErrorEnvelope:
    def test_unknown_route_uses_the_structured_envelope(self, healthy_client: TestClient) -> None:
        response = healthy_client.get("/api/v1/does-not-exist")
        assert response.status_code == 404
        error = response.json()["error"]
        assert error["code"] == "not_found"
        assert error["correlation_id"]

    def test_domain_errors_map_to_stable_codes_and_statuses(
        self, clear_settings_cache: None
    ) -> None:
        from app.api.dependencies import get_container
        from app.main import create_app

        app = create_app()
        app.dependency_overrides[get_container] = lambda: StubContainer(())

        @app.get("/api/v1/_test/forbidden")
        async def _forbidden() -> None:
            raise AuthorizationError("not permitted")

        @app.get("/api/v1/_test/missing")
        async def _missing() -> None:
            raise NotFoundError("dataset not found")

        @app.get("/api/v1/_test/boom")
        async def _boom() -> None:
            raise RuntimeError("psycopg: password authentication failed for user 'app'")

        client = TestClient(app, raise_server_exceptions=False)

        forbidden = client.get("/api/v1/_test/forbidden")
        assert forbidden.status_code == 403
        assert forbidden.json()["error"]["code"] == "authorization_error"

        missing = client.get("/api/v1/_test/missing")
        assert missing.status_code == 404
        assert missing.json()["error"]["code"] == "not_found"

        boom = client.get("/api/v1/_test/boom")
        assert boom.status_code == 500
        body = boom.json()
        # The caller always gets the stable opaque code and message; the raw
        # exception text is never the message, and no stack trace is returned.
        assert body["error"]["code"] == "internal_error"
        assert body["error"]["message"] == "an internal error occurred"
        assert "Traceback" not in boom.text
        assert "psycopg" not in body["error"]["message"]

    def test_production_like_environments_expose_no_diagnostics(self) -> None:
        """Diagnostic detail is an environment-gated concession, never the default."""
        from app.core.environment import Environment

        assert Environment.PRODUCTION.exposes_diagnostics is False
        assert Environment.STAGING.exposes_diagnostics is False
        assert Environment.DEVELOPMENT.exposes_diagnostics is True

    def test_oversized_request_is_rejected_with_the_envelope(
        self, healthy_client: TestClient
    ) -> None:
        response = healthy_client.post(
            "/api/v1/_none",
            content=b"x" * 32,
            headers={"Content-Length": str(64 * 1024 * 1024)},
        )
        assert response.status_code == 413
        assert response.json()["error"]["code"] == "validation_error"


class TestSecurityHeaders:
    def test_security_headers_are_applied(self, healthy_client: TestClient) -> None:
        headers = healthy_client.get("/api/v1/health").headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert headers["Referrer-Policy"] == "no-referrer"
        assert headers["Cache-Control"] == "no-store"


class TestOpenApi:
    def test_openapi_document_describes_the_versioned_api(self, healthy_client: TestClient) -> None:
        document = healthy_client.get("/api/v1/openapi.json").json()
        assert "/api/v1/health" in document["paths"]
        assert "/api/v1/ready" in document["paths"]
        assert {tag["name"] for tag in document["tags"]} >= {"system"}
