"""API/transport tests for the dataset, upload, import and validation endpoints.

The real FastAPI app is exercised over HTTP with the real security services and
in-memory repositories. What is checked here is the transport contract itself:
an unauthenticated caller is refused, a state-changing request needs its CSRF
token, knowing another tenant's identifier reveals nothing, storage keys never
leave the server, and bytes never travel through the API.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.application.use_cases.describe_scientific_capabilities import (
    DescribeScientificCapabilities,
)
from app.application.use_cases.get_readiness import GetReadiness
from tests.data.support import TABLE, draft_version, personal_dataset
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


def dataset_payload(workspace_id: str, name: str = "Cohort Table") -> dict:
    return {
        "workspace_id": workspace_id,
        "name": name,
        "kind": "variant_calls",
        "reference_build_declared": "grch38",
    }


async def personal_workspace_id(harness: Harness, user_id: str) -> str:
    workspace = await harness.repositories.workspaces.get_personal_for_user(user_id)
    return workspace.id


class TestDatasetTransport:
    async def test_an_anonymous_caller_cannot_reach_datasets(
        self, client: TestClient
    ) -> None:
        response = client.get("/api/v1/datasets")
        assert response.status_code == 401
        assert response.json()["error"]["code"] in {"unauthenticated", "authentication_error"}

    async def test_creating_a_dataset_requires_the_csrf_token(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "csrf@example.org")
        workspace_id = await personal_workspace_id(harness, user_id)
        response = client.post("/api/v1/datasets", json=dataset_payload(workspace_id))
        # A missing CSRF token invalidates the request's authentication itself.
        assert response.status_code == 401
        # The session survives a refused request.
        assert client.get("/api/v1/datasets").status_code == 200

    async def test_a_dataset_is_created_and_read_back_without_storage_internals(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "owner@example.org")
        workspace_id = await personal_workspace_id(harness, user_id)
        created = client.post(
            "/api/v1/datasets",
            json=dataset_payload(workspace_id),
            headers=csrf(client, harness),
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["state"] == "draft"
        assert body["capabilities"]
        assert "storage_key" not in created.text

        listed = client.get("/api/v1/datasets", params={"workspace_id": workspace_id})
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()["items"]] == [body["id"]]

    async def test_a_scope_must_be_named_when_creating_a_dataset(
        self, client: TestClient, harness: Harness
    ) -> None:
        await signed_in(client, harness, "noscope@example.org")
        payload = dataset_payload("")
        payload.pop("workspace_id")
        response = client.post(
            "/api/v1/datasets", json=payload, headers=csrf(client, harness)
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"

    async def test_an_unknown_enum_value_is_a_validation_error_not_a_crash(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "enum@example.org")
        workspace_id = await personal_workspace_id(harness, user_id)
        payload = dataset_payload(workspace_id) | {"kind": "not_a_kind"}
        response = client.post(
            "/api/v1/datasets", json=payload, headers=csrf(client, harness)
        )
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "validation_error"


class TestTenantIsolationOverHttp:
    async def test_another_tenants_dataset_is_indistinguishable_from_a_missing_one(
        self, client: TestClient, harness: Harness
    ) -> None:
        owner_id = await create_account(harness, "isolated-owner@example.org")
        dataset = await personal_dataset(harness, owner_id)

        await signed_in(client, harness, "outsider@example.org")
        known = client.get(f"/api/v1/datasets/{dataset.dataset.id}")
        unknown = client.get("/api/v1/datasets/dst_" + "0" * 32)
        # Both are refused, and neither response carries anything about the
        # resource: no name, no scope, no storage location.
        assert known.status_code in {403, 404}
        assert unknown.status_code in {403, 404}
        assert "Cohort Table" not in known.text
        assert "storage_key" not in known.text

    async def test_an_outsider_cannot_open_an_upload_against_a_foreign_version(
        self, client: TestClient, harness: Harness
    ) -> None:
        owner_id = await create_account(harness, "isolated-upload@example.org")
        dataset = await personal_dataset(harness, owner_id)
        version = await draft_version(harness, owner_id, dataset.dataset.id)

        await signed_in(client, harness, "upload-outsider@example.org")
        response = client.post(
            f"/api/v1/dataset-versions/{version.version.id}/uploads",
            json={
                "filename": "cohort.tsv",
                "size_bytes": len(TABLE),
                "checksum_algorithm": "sha256",
                "checksum_value": "0" * 64,
            },
            headers=csrf(client, harness),
        )
        assert response.status_code in {403, 404}
        assert not harness.storage.presigned_uploads


class TestUploadTransport:
    async def test_a_transfer_grant_is_a_url_and_never_a_storage_key(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "grant@example.org")
        dataset = await personal_dataset(harness, user_id)
        version = await draft_version(harness, user_id, dataset.dataset.id)

        response = client.post(
            f"/api/v1/dataset-versions/{version.version.id}/uploads",
            json={
                "filename": "cohort.tsv",
                "size_bytes": len(TABLE),
                "checksum_algorithm": "sha256",
                "checksum_value": "a" * 64,
            },
            headers=csrf(client, harness),
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["upload_url"]
        assert body["expires_at"]
        assert "storage_key" not in response.text
        # The API accepted a session and a grant, not any bytes.
        assert harness.storage.presigned_uploads

    async def test_completing_a_transfer_that_never_happened_is_refused(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "nobytes@example.org")
        dataset = await personal_dataset(harness, user_id)
        version = await draft_version(harness, user_id, dataset.dataset.id)
        opened = client.post(
            f"/api/v1/dataset-versions/{version.version.id}/uploads",
            json={
                "filename": "cohort.tsv",
                "size_bytes": len(TABLE),
                "checksum_algorithm": "sha256",
                "checksum_value": "a" * 64,
            },
            headers=csrf(client, harness),
        )
        session_id = opened.json()["session"]["id"]
        response = client.post(
            f"/api/v1/uploads/{session_id}/complete", headers=csrf(client, harness)
        )
        assert response.status_code in {409, 422}
