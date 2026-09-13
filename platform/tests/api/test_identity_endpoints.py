"""API/transport tests for the identity and tenancy endpoints.

The real FastAPI app is exercised over HTTP with real security services and
in-memory repositories, so cookie handling, CSRF enforcement, session
resolution, authorization refusals and the error envelope are genuinely tested.
No route is allowed to trust a client-supplied identity.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.application.use_cases.describe_scientific_capabilities import (
    DescribeScientificCapabilities,
)
from app.application.use_cases.get_readiness import GetReadiness
from app.domain.value_objects.enums import PlatformRole
from tests.support.actors import create_account, grant_platform_role
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


def csrf_headers(client: TestClient, harness: Harness) -> dict[str, str]:
    policy = harness.policy
    token = client.cookies.get(policy.csrf_cookie_name)
    return {policy.csrf_header_name: token} if token else {}


def sign_in(client: TestClient, harness: Harness, email: str) -> dict:
    response = client.post(
        "/api/v1/auth/sign-in", json={"email": email, "password": STRONG_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()


class TestRegistrationTransport:
    def test_registration_is_accepted_without_establishing_a_session(
        self, client: TestClient, harness: Harness
    ) -> None:
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": "New.User@Example.org",
                "password": STRONG_PASSWORD,
                "display_name": "New User",
            },
        )
        assert response.status_code == 202
        body = response.json()
        assert body["accepted"] is True
        # No session is issued by registration.
        assert harness.policy.session_cookie_name not in response.cookies

        token = body["development_only_token"]
        verified = client.post("/api/v1/auth/verify-email", json={"token": token})
        assert verified.status_code == 200
        assert verified.json()["verified"] is True

    def test_a_known_address_is_indistinguishable_from_an_unknown_one(
        self, client: TestClient, harness: Harness
    ) -> None:
        payload = {
            "email": "duplicate@example.org",
            "password": STRONG_PASSWORD,
            "display_name": "Duplicate",
        }
        first = client.post("/api/v1/auth/register", json=payload)
        second = client.post("/api/v1/auth/register", json=payload)
        assert first.status_code == second.status_code == 202
        assert first.json()["message"] == second.json()["message"]

    def test_a_weak_password_is_refused_with_the_error_envelope(
        self, client: TestClient
    ) -> None:
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "weak@example.org", "password": "short", "display_name": "Weak"},
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"


class TestSessionTransport:
    async def test_sign_in_sets_an_httponly_session_cookie_and_a_csrf_cookie(
        self, client: TestClient, harness: Harness
    ) -> None:
        await create_account(harness, "signin@example.org")
        response = client.post(
            "/api/v1/auth/sign-in",
            json={"email": "signin@example.org", "password": STRONG_PASSWORD},
        )
        assert response.status_code == 200
        raw = "; ".join(response.headers.get_list("set-cookie"))
        assert harness.policy.session_cookie_name in raw
        assert "HttpOnly" in raw
        # The session token itself is never part of the response body.
        assert harness.policy.session_cookie_name not in response.text

    async def test_bad_credentials_are_refused_uniformly(
        self, client: TestClient, harness: Harness
    ) -> None:
        await create_account(harness, "uniform@example.org")
        unknown = client.post(
            "/api/v1/auth/sign-in",
            json={"email": "nobody@example.org", "password": STRONG_PASSWORD},
        )
        wrong = client.post(
            "/api/v1/auth/sign-in",
            json={"email": "uniform@example.org", "password": "Wrong-Password-12345"},
        )
        assert unknown.status_code == wrong.status_code == 401
        assert unknown.json()["error"] == {
            **wrong.json()["error"],
            "correlation_id": unknown.json()["error"]["correlation_id"],
        }

    def test_protected_endpoints_refuse_an_anonymous_caller(self, client: TestClient) -> None:
        for path in ("/api/v1/me", "/api/v1/workspaces", "/api/v1/projects"):
            response = client.get(path)
            assert response.status_code == 401, path
            assert response.json()["error"]["code"] == "authentication_error"

    async def test_a_forged_session_cookie_is_rejected(
        self, client: TestClient, harness: Harness
    ) -> None:
        await create_account(harness, "forged@example.org")
        client.cookies.set(harness.policy.session_cookie_name, "clearly-not-a-real-token")
        assert client.get("/api/v1/me").status_code == 401

    async def test_me_reports_the_resolved_identity(
        self, client: TestClient, harness: Harness
    ) -> None:
        await create_account(harness, "me@example.org", "Me Myself")
        sign_in(client, harness, "me@example.org")
        body = client.get("/api/v1/me").json()
        assert body["account"]["email"] == "me@example.org"
        assert body["account"]["display_name"] == "Me Myself"
        assert body["session"]["id"]
        assert body["requires_reauthentication"] is False

    async def test_sign_out_clears_the_cookie_and_kills_the_session(
        self, client: TestClient, harness: Harness
    ) -> None:
        await create_account(harness, "out@example.org")
        sign_in(client, harness, "out@example.org")
        response = client.post(
            "/api/v1/auth/sign-out",
            json={"all_sessions": False},
            headers=csrf_headers(client, harness),
        )
        assert response.status_code == 204
        assert client.get("/api/v1/me").status_code == 401


class TestCsrfProtection:
    async def test_an_unsafe_request_without_the_csrf_header_is_refused(
        self, client: TestClient, harness: Harness
    ) -> None:
        await create_account(harness, "csrf@example.org")
        sign_in(client, harness, "csrf@example.org")
        response = client.post("/api/v1/auth/sign-out", json={"all_sessions": False})
        assert response.status_code == 401
        # The session survives a refused request.
        assert client.get("/api/v1/me").status_code == 200

    async def test_a_wrong_csrf_header_is_refused(
        self, client: TestClient, harness: Harness
    ) -> None:
        await create_account(harness, "csrf2@example.org")
        sign_in(client, harness, "csrf2@example.org")
        response = client.post(
            "/api/v1/auth/sign-out",
            json={"all_sessions": False},
            headers={harness.policy.csrf_header_name: "not-the-token"},
        )
        assert response.status_code == 401

    async def test_a_safe_request_needs_no_csrf_header(
        self, client: TestClient, harness: Harness
    ) -> None:
        await create_account(harness, "safe@example.org")
        sign_in(client, harness, "safe@example.org")
        assert client.get("/api/v1/workspaces").status_code == 200


class TestTenancyTransport:
    async def test_a_new_account_sees_only_its_personal_workspace(
        self, client: TestClient, harness: Harness
    ) -> None:
        await create_account(harness, "solo@example.org")
        sign_in(client, harness, "solo@example.org")
        body = client.get("/api/v1/workspaces").json()
        assert len(body["items"]) == 1
        assert body["items"][0]["kind"] == "personal"

    async def test_another_accounts_workspace_is_not_found(
        self, client: TestClient, harness: Harness
    ) -> None:
        await create_account(harness, "owner@example.org")
        intruder_id = await create_account(harness, "intruder@example.org")
        sign_in(client, harness, "owner@example.org")
        mine = client.get("/api/v1/workspaces").json()["items"][0]["id"]

        client.post(
            "/api/v1/auth/sign-out",
            json={"all_sessions": False},
            headers=csrf_headers(client, harness),
        )
        sign_in(client, harness, "intruder@example.org")
        assert intruder_id
        # Knowing the identifier grants nothing.
        response = client.get(f"/api/v1/workspaces/{mine}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    async def test_an_organization_request_starts_pending_review(
        self, client: TestClient, harness: Harness
    ) -> None:
        await create_account(harness, "requester@example.org")
        sign_in(client, harness, "requester@example.org")
        response = client.post(
            "/api/v1/organizations",
            json={"slug": "lab-one", "name": "Lab One", "description": "A lab"},
            headers=csrf_headers(client, harness),
        )
        assert response.status_code in (200, 201), response.text
        assert response.json()["state"] != "active"

    async def test_administration_is_closed_to_an_ordinary_account(
        self, client: TestClient, harness: Harness
    ) -> None:
        await create_account(harness, "plain@example.org")
        sign_in(client, harness, "plain@example.org")
        response = client.get("/api/v1/admin/users")
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "authorization_error"

    async def test_administration_is_open_to_a_platform_administrator(
        self, client: TestClient, harness: Harness
    ) -> None:
        admin_id = await create_account(harness, "root@example.org", "Root")
        await grant_platform_role(harness, admin_id, PlatformRole.PLATFORM_ADMINISTRATOR)
        sign_in(client, harness, "root@example.org")
        response = client.get("/api/v1/admin/users")
        assert response.status_code == 200
        assert response.json()["items"]


class TestOpenApiSurface:
    def test_identity_and_tenancy_paths_are_documented(self, client: TestClient) -> None:
        paths = client.get("/api/v1/openapi.json").json()["paths"]
        for path in (
            "/api/v1/auth/register",
            "/api/v1/auth/sign-in",
            "/api/v1/me",
            "/api/v1/workspaces",
            "/api/v1/organizations",
            "/api/v1/projects",
            "/api/v1/admin/users",
        ):
            assert path in paths, path
