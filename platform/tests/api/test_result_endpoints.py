"""API/transport tests for result surfaces and variant records.

The real FastAPI app is exercised over HTTP with the real security services and
in-memory repositories. What is checked here is the transport contract:

* anonymous callers reach nothing, and state-changing requests need CSRF;
* metadata, content and bytes are three separately authorized exposures;
* a surface that has not been verified is not readable through the API either;
* a variant read without a dataset version is refused by the contract itself;
* withdrawal lives on the administrative router and is closed to ordinary users;
* development payloads are still marked when they reach the wire.
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
from tests.results.support import (
    available_result,
    execution_for,
    ingest_variants,
    normalized_claim,
    submitted_result,
)
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

    def data_services(self):  # noqa: ANN201
        return self._harness.data

    def analysis_services(self):  # noqa: ANN201
        return self._harness.analysis

    def result_services(self):  # noqa: ANN201
        return self._harness.results

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
    user_id = await create_account(harness, email)
    response = client.post(
        "/api/v1/auth/sign-in", json={"email": email, "password": STRONG_PASSWORD}
    )
    assert response.status_code == 200, response.text
    return user_id


def csrf(client: TestClient, harness: Harness) -> dict[str, str]:
    token = client.cookies.get(harness.policy.csrf_cookie_name)
    return {harness.policy.csrf_header_name: token} if token else {}


class TestResultSetTransport:
    async def test_an_anonymous_caller_cannot_reach_result_surfaces(
        self, client: TestClient
    ) -> None:
        for path in (
            "/api/v1/result-sets",
            "/api/v1/result-sets/rs_missing",
            "/api/v1/result-sets/rs_missing/content",
            "/api/v1/variants?dataset_version_id=dsv_missing",
        ):
            response = client.get(path)
            assert response.status_code == 401, path
            assert response.json()["error"]["code"] in {
                "unauthenticated",
                "authentication_error",
            }

    async def test_a_verified_surface_is_listed_read_and_marked_as_development(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "result-owner@example.org")
        _, execution, _ = await execution_for(harness, user_id)
        view = await available_result(harness, user_id, execution.id)

        listed = client.get("/api/v1/result-sets")
        assert listed.status_code == 200, listed.text
        assert [item["id"] for item in listed.json()["items"]] == [view.result_set.id]

        detail = client.get(f"/api/v1/result-sets/{view.result_set.id}")
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["state"] == "available"
        assert body["is_readable"] is True
        # The mark travels all the way to the wire: nothing here can be mistaken
        # for a scientifically valid result.
        assert body["is_development_payload"] is True
        assert body["provenance"]["engine_version"]
        assert "read" in body["capabilities"]

        content = client.get(f"/api/v1/result-sets/{view.result_set.id}/content")
        assert content.status_code == 200, content.text
        page = content.json()
        assert [column["name"] for column in page["columns"]] == ["variant_id", "score"]
        assert page["rows"] == [["v1", 1]]
        assert page["is_development_payload"] is True

    async def test_an_unverified_surface_is_not_readable_through_the_api(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "result-unverified@example.org")
        _, execution, _ = await execution_for(harness, user_id)
        view = await submitted_result(harness, user_id, execution.id)

        response = client.get(f"/api/v1/result-sets/{view.result_set.id}/content")
        # A conflict, with the state as the reason — not an empty page.
        assert response.status_code == 409, response.text
        assert response.json()["error"]["details"]["state"] == "validated"

    async def test_an_oversized_content_window_is_refused_by_the_contract(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "result-window@example.org")
        _, execution, _ = await execution_for(harness, user_id)
        view = await available_result(harness, user_id, execution.id)

        response = client.get(
            f"/api/v1/result-sets/{view.result_set.id}/content", params={"limit": 10_000}
        )
        assert response.status_code == 422

    async def test_another_tenants_surface_is_indistinguishable_from_a_missing_one(
        self, client: TestClient, harness: Harness
    ) -> None:
        owner = await create_account(harness, "result-tenant-owner@example.org")
        _, execution, _ = await execution_for(harness, owner)
        view = await available_result(harness, owner, execution.id)

        await signed_in(client, harness, "result-outsider@example.org")
        response = client.get(f"/api/v1/result-sets/{view.result_set.id}")
        assert response.status_code in {403, 404}
        assert client.get("/api/v1/result-sets").json()["items"] == []

    async def test_a_download_grant_requires_the_csrf_token(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "result-download@example.org")
        _, execution, _ = await execution_for(harness, user_id)
        view = await available_result(harness, user_id, execution.id)
        artifact_id = view.artifacts[0].id
        path = (
            f"/api/v1/result-sets/{view.result_set.id}/artifacts/{artifact_id}/download"
        )

        refused = client.post(path)
        assert refused.status_code == 401

        granted = client.post(path, headers=csrf(client, harness))
        assert granted.status_code == 200, granted.text
        body = granted.json()
        assert body["artifact_id"] == artifact_id
        assert body["url"]
        assert body["expires_in_seconds"] > 0

    async def test_invalidation_is_administrative_and_leaves_content_alone(
        self, client: TestClient, harness: Harness
    ) -> None:
        owner = await create_account(harness, "result-invalidate-owner@example.org")
        _, execution, _ = await execution_for(harness, owner)
        view = await available_result(harness, owner, execution.id)
        path = f"/api/v1/administration/result-sets/{view.result_set.id}/invalidate"

        user_id = await signed_in(client, harness, "result-ordinary@example.org")
        refused = client.post(
            path, json={"reason": "withdrawn"}, headers=csrf(client, harness)
        )
        assert refused.status_code in {403, 404}

        await grant_platform_role(harness, user_id, PlatformRole.PLATFORM_ADMINISTRATOR)
        accepted = client.post(
            path, json={"reason": "withdrawn"}, headers=csrf(client, harness)
        )
        assert accepted.status_code == 200, accepted.text
        body = accepted.json()
        assert body["state"] == "invalidated"
        assert body["invalidation_reason"] == "withdrawn"
        # Withdrawal is a lifecycle statement; the recorded content is untouched.
        assert body["row_count"] == view.result_set.row_count
        assert body["analytical_location"] == view.result_set.analytical_location


class TestVariantTransport:
    async def test_a_variant_list_requires_a_dataset_version(
        self, client: TestClient, harness: Harness
    ) -> None:
        await signed_in(client, harness, "variant-contract@example.org")
        assert client.get("/api/v1/variants").status_code == 422

    async def test_variants_are_listed_and_read_through_a_dataset_version(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "variant-owner@example.org")
        _, execution, dataset_version_id = await execution_for(harness, user_id)
        await ingest_variants(
            harness,
            user_id,
            analysis_execution_id=execution.id,
            dataset_version_id=dataset_version_id,
            variants=(normalized_claim(),),
        )

        listed = client.get(
            "/api/v1/variants", params={"dataset_version_id": dataset_version_id}
        )
        assert listed.status_code == 200, listed.text
        items = listed.json()["items"]
        assert len(items) == 1
        assert items[0]["contig"] == "chr1"
        assert items[0]["position"] == 1000
        assert items[0]["normalization_state"] == "normalized"

        detail = client.get(
            f"/api/v1/variants/{items[0]['id']}",
            params={"dataset_version_id": dataset_version_id},
        )
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["source_representations"][0]["source_record_key"] == "rec-1"

    async def test_knowing_a_variant_id_reveals_nothing_to_another_tenant(
        self, client: TestClient, harness: Harness
    ) -> None:
        owner = await create_account(harness, "variant-tenant-owner@example.org")
        _, execution, dataset_version_id = await execution_for(harness, owner)
        await ingest_variants(
            harness,
            owner,
            analysis_execution_id=execution.id,
            dataset_version_id=dataset_version_id,
            variants=(normalized_claim(),),
        )
        variant_id = next(iter(harness.repositories.variants.rows))

        await signed_in(client, harness, "variant-outsider@example.org")
        response = client.get(
            f"/api/v1/variants/{variant_id}",
            params={"dataset_version_id": dataset_version_id},
        )
        assert response.status_code in {403, 404}
