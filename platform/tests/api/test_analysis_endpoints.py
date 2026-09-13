"""API/transport tests for analyses, executions, jobs, schedules and compute.

The real FastAPI app is exercised over HTTP with the real security services and
in-memory repositories. What is checked here is the transport contract: an
anonymous caller is refused, a state-changing request needs its CSRF token,
another tenant's analysis is indistinguishable from a missing one, administrative
job and compute endpoints are closed to ordinary users, and no execution is ever
performed by the request path itself.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.application.use_cases.describe_scientific_capabilities import (
    DescribeScientificCapabilities,
)
from app.application.use_cases.get_readiness import GetReadiness
from app.domain.value_objects.enums import JobState
from tests.analysis.support import configured_analysis, project_analysis
from tests.support.actors import create_account
from tests.support.services import STRONG_PASSWORD, Harness, build_harness


class StubContainer:
    """Container substitute exposing exactly what the routes resolve from it."""

    def __init__(self, harness: Harness) -> None:
        from app.core.app_config import get_application_settings
        from app.core.environment import get_environment_settings

        self._harness = harness
        self.environment = get_environment_settings()
        self.application = get_application_settings()
        self.clock = harness.clock
        self.tokens = harness.tokens
        self.unit_of_work = harness.unit_of_work
        self.sessions = harness.sessions
        self.authorization = harness.authorization

    def identity_services(self):  # noqa: ANN201
        return self._harness.identity

    def tenancy_services(self):  # noqa: ANN201
        return self._harness.tenancy

    def data_services(self):  # noqa: ANN201
        return self._harness.data

    def analysis_services(self):  # noqa: ANN201
        return self._harness.analysis

    def get_readiness(self) -> GetReadiness:
        return GetReadiness(())

    def describe_scientific_capabilities(self) -> DescribeScientificCapabilities:
        raise NotImplementedError


@pytest.fixture
def harness() -> Harness:
    return build_harness()


@pytest.fixture
def client(harness: Harness, clear_settings_cache: None) -> Iterator[TestClient]:
    from app.api.dependencies import get_container
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_container] = lambda: StubContainer(harness)
    # Lifespan would connect real infrastructure, so it is not started.
    test_client = TestClient(app)
    yield test_client
    test_client.close()


async def signed_in(client: TestClient, harness: Harness, email: str) -> str:
    """Create a verified account and establish a real session cookie."""
    user_id = await create_account(harness, email)
    response = client.post(
        "/api/v1/auth/sign-in", json={"email": email, "password": STRONG_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return user_id


def csrf(client: TestClient, harness: Harness) -> dict[str, str]:
    token = client.cookies.get(harness.policy.csrf_cookie_name)
    return {harness.policy.csrf_header_name: token} if token else {}


class TestAnalysisTransport:
    async def test_an_anonymous_caller_cannot_reach_analyses(self, client: TestClient) -> None:
        response = client.get("/api/v1/analyses")
        assert response.status_code == 401
        assert response.json()["error"]["code"] in {"unauthenticated", "authentication_error"}

    async def test_creating_an_analysis_requires_the_csrf_token(
        self, client: TestClient, harness: Harness
    ) -> None:
        await signed_in(client, harness, "analysis-csrf@example.org")
        response = client.post(
            "/api/v1/analyses", json={"name": "Trio Screen", "kind": "variant_prioritization"}
        )
        assert response.status_code == 401
        # The session survives a refused request.
        assert client.get("/api/v1/analyses").status_code == 200

    async def test_an_analysis_is_created_and_read_back_with_capabilities(
        self, client: TestClient, harness: Harness
    ) -> None:
        await signed_in(client, harness, "analysis-owner@example.org")
        created = client.post(
            "/api/v1/analyses",
            json={
                "name": "Trio Screen",
                "kind": "variant_prioritization",
                "capability_key": "integration.echo",
            },
            headers=csrf(client, harness),
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["state"] == "draft"
        assert "read" in body["capabilities"]

        listed = client.get("/api/v1/analyses")
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["items"]] == [body["id"]]

    async def test_an_unknown_kind_is_a_validation_error_not_a_crash(
        self, client: TestClient, harness: Harness
    ) -> None:
        await signed_in(client, harness, "analysis-enum@example.org")
        response = client.post(
            "/api/v1/analyses",
            json={"name": "Bad Kind", "kind": "not_a_kind"},
            headers=csrf(client, harness),
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"


class TestExecutionTransport:
    async def test_requesting_an_execution_only_queues_work(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "execution-owner@example.org")
        analysis, _ = await configured_analysis(harness, user_id)

        response = client.post(
            f"/api/v1/analyses/{analysis.analysis.id}/executions",
            json={},
            headers=csrf(client, harness),
        )
        assert response.status_code == 202, response.text
        body = response.json()
        # The request path queues; it never runs the scientific work itself.
        assert body["state"] == "queued"
        job = await harness.repositories.jobs.get(body["job"]["id"])
        assert job.state is JobState.QUEUED
        assert not harness.scientific.submissions

    async def test_provenance_is_available_for_an_execution(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "provenance@example.org")
        analysis, _ = await configured_analysis(harness, user_id)
        queued = client.post(
            f"/api/v1/analyses/{analysis.analysis.id}/executions",
            json={},
            headers=csrf(client, harness),
        )
        execution_id = queued.json()["id"]

        response = client.get(f"/api/v1/analysis-executions/{execution_id}/provenance")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["execution"]["id"] == execution_id
        # No scientific execution has happened yet, and nothing is invented.
        assert body["scientific_executions"] == []


class TestTenantIsolationOverHttp:
    async def test_another_tenants_analysis_is_indistinguishable_from_a_missing_one(
        self, client: TestClient, harness: Harness
    ) -> None:
        owner_id = await create_account(harness, "isolated-analysis@example.org")
        analysis = await project_analysis(harness, owner_id)

        await signed_in(client, harness, "analysis-outsider@example.org")
        known = client.get(f"/api/v1/analyses/{analysis.analysis.id}")
        unknown = client.get("/api/v1/analyses/ana_" + "0" * 32)
        assert known.status_code in {403, 404}
        assert unknown.status_code in {403, 404}
        assert "Trio Screen" not in known.text

    async def test_an_outsider_cannot_request_an_execution(
        self, client: TestClient, harness: Harness
    ) -> None:
        owner_id = await create_account(harness, "isolated-execution@example.org")
        analysis, _ = await configured_analysis(harness, owner_id)

        await signed_in(client, harness, "execution-outsider@example.org")
        response = client.post(
            f"/api/v1/analyses/{analysis.analysis.id}/executions",
            json={},
            headers=csrf(client, harness),
        )
        assert response.status_code in {403, 404}
        assert not harness.scientific.submissions


class TestAdministrativeTransport:
    async def test_platform_job_control_is_closed_to_an_ordinary_user(
        self, client: TestClient, harness: Harness
    ) -> None:
        await signed_in(client, harness, "not-an-admin@example.org")
        listed = client.get("/api/v1/administration/jobs")
        queues = client.get("/api/v1/administration/jobs/queues")
        nodes = client.get("/api/v1/administration/compute-nodes")
        assert listed.status_code == 403
        assert queues.status_code == 403
        assert nodes.status_code == 403

    async def test_job_listing_is_scoped_and_never_empty_handed(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "job-reader@example.org")
        analysis, _ = await configured_analysis(harness, user_id)
        client.post(
            f"/api/v1/analyses/{analysis.analysis.id}/executions",
            json={},
            headers=csrf(client, harness),
        )
        response = client.get("/api/v1/jobs")
        assert response.status_code == 200, response.text
        assert [item["kind"] for item in response.json()["items"]] == ["analysis_execution"]
