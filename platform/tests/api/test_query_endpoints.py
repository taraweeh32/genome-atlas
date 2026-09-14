"""API/transport tests for filtering, ranking, variant queries and saved views.

The real FastAPI app is exercised over HTTP with the real security services, the
real authorization policy, in-memory repositories and a **real Parquet surface
read through the real DuckDB engine**. What is checked here is the transport
contract and the boundaries that must hold at it:

* anonymous callers reach nothing, and state-changing requests need CSRF;
* a filter arrives as structured data and is validated, never repaired;
* pages are bounded by the contract itself, so no request can become an export;
* another user's personal configuration is indistinguishable from a missing one;
* scope is not something a request may claim: a platform preset needs the
  platform permission;
* a concurrent edit is rejected with a conflict rather than silently merged;
* ranking arrives as its own payload and reports its own execution record, and a
  row with nothing to score is reported as unscored rather than as low priority.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from tests.query.support import (
    condition,
    group,
    query_services,
    surface_result_set,
    write_surface,
)
from tests.support.actors import create_account, grant_platform_role
from tests.support.services import STRONG_PASSWORD, Harness, build_harness

from app.application.use_cases.describe_scientific_capabilities import (
    DescribeScientificCapabilities,
)
from app.application.use_cases.get_readiness import GetReadiness
from app.domain.value_objects.enums import PlatformRole


class StubContainer:
    """Container substitute exposing exactly what the query routes resolve."""

    def __init__(self, harness: Harness, root: Path) -> None:
        from app.core.app_config import get_application_settings
        from app.core.environment import get_environment_settings

        self._harness = harness
        self._queries = query_services(harness, root)
        self.environment = get_environment_settings()
        self.application = get_application_settings()
        self.clock = harness.clock
        self.tokens = harness.tokens
        self.unit_of_work = harness.unit_of_work
        self.sessions = harness.sessions
        self.authorization = harness.authorization

    def identity_services(self):
        return self._harness.identity

    def tenancy_services(self):
        return self._harness.tenancy

    def data_services(self):
        return self._harness.data

    def analysis_services(self):
        return self._harness.analysis

    def result_services(self):
        return self._harness.results

    def query_services(self):
        return self._queries

    def annotation_field_dictionary(self):  # noqa: ANN201
        return self._harness.field_dictionary

    def get_readiness(self) -> GetReadiness:
        return GetReadiness(())

    def describe_scientific_capabilities(self) -> DescribeScientificCapabilities:
        raise NotImplementedError


@pytest.fixture
def harness() -> Harness:
    return build_harness()


@pytest.fixture
def surface(tmp_path: Path) -> str:
    return write_surface(tmp_path)


@pytest.fixture
def client(
    harness: Harness, tmp_path: Path, clear_settings_cache: None
) -> Iterator[TestClient]:
    from app.api.dependencies import get_container
    from app.main import create_app

    app = create_app()
    app.dependency_overrides[get_container] = lambda: StubContainer(harness, tmp_path)
    test_client = TestClient(app)
    yield test_client
    test_client.close()


def sign_in(client: TestClient, email: str) -> None:
    response = client.post(
        "/api/v1/auth/sign-in", json={"email": email, "password": STRONG_PASSWORD}
    )
    assert response.status_code == 200, response.text


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


async def workspace_of(harness: Harness, user_id: str) -> str:
    workspace = await harness.repositories.workspaces.get_personal_for_user(user_id)
    assert workspace is not None
    return workspace.id


class TestFieldDictionaryTransport:
    async def test_an_anonymous_caller_reaches_nothing(
        self, client: TestClient
    ) -> None:
        for path in (
            "/api/v1/filter-fields",
            "/api/v1/filter-fields/gene_symbol",
            "/api/v1/filters",
            "/api/v1/filter-presets",
            "/api/v1/ranking-methods",
            "/api/v1/rankings",
            "/api/v1/saved-views",
            "/api/v1/administration/query/limits",
        ):
            response = client.get(path)
            assert response.status_code == 401, path

        refused = client.post(
            "/api/v1/variants/query", json={"result_set_id": "rs_missing"}
        )
        assert refused.status_code == 401

    async def test_the_dictionary_publishes_type_aware_operators(
        self, client: TestClient, harness: Harness
    ) -> None:
        await signed_in(client, harness, "fields-reader@example.org")

        response = client.get("/api/v1/filter-fields")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["version"]
        # No surface was named, so availability is unknown — which is reported as
        # null rather than as an empty list.
        assert body["available_field_ids"] is None
        by_id = {item["id"]: item for item in body["fields"]}

        frequency = by_id["allele_frequency"]
        assert "between" in frequency["supported_operators"]
        assert "contains" not in frequency["supported_operators"]
        gene = by_id["gene_symbol"]
        assert gene["high_cardinality"] is True
        assert gene["searchable"] is True
        assert "is_missing" in gene["supported_operators"]

    async def test_a_named_surface_narrows_availability(
        self, client: TestClient, harness: Harness, surface: str
    ) -> None:
        user_id = await signed_in(client, harness, "fields-surface@example.org")
        result_set = await surface_result_set(harness, user_id, surface)

        response = client.get(
            "/api/v1/filter-fields", params={"result_set_id": result_set.id}
        )
        assert response.status_code == 200, response.text
        available = response.json()["available_field_ids"]
        assert "gene_symbol" in available
        # The fixture surface carries no sample column, so the field is not
        # advertised as available for it.
        assert "sample_id" not in available

    async def test_distinct_values_are_searched_server_side_and_bounded(
        self, client: TestClient, harness: Harness, surface: str
    ) -> None:
        user_id = await signed_in(client, harness, "fields-values@example.org")
        result_set = await surface_result_set(harness, user_id, surface)

        response = client.get(
            "/api/v1/filter-fields/gene_symbol/values",
            params={"result_set_id": result_set.id, "search": "cf", "with_counts": True},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert [item["value"] for item in body["values"]] == ["CFTR"]
        assert body["values"][0]["count"] == 2

        oversized = client.get(
            "/api/v1/filter-fields/gene_symbol/values",
            params={"result_set_id": result_set.id, "limit": 5000},
        )
        assert oversized.status_code == 422

    async def test_a_field_that_is_not_a_picker_refuses_value_search(
        self, client: TestClient, harness: Harness, surface: str
    ) -> None:
        user_id = await signed_in(client, harness, "fields-nonsearch@example.org")
        result_set = await surface_result_set(harness, user_id, surface)

        response = client.get(
            "/api/v1/filter-fields/allele_frequency/values",
            params={"result_set_id": result_set.id},
        )
        assert response.status_code == 422, response.text

    async def test_distinct_values_of_an_inaccessible_surface_are_refused(
        self, client: TestClient, harness: Harness, surface: str
    ) -> None:
        owner = await create_account(harness, "values-owner@example.org")
        result_set = await surface_result_set(harness, owner, surface)

        await signed_in(client, harness, "values-outsider@example.org")
        response = client.get(
            "/api/v1/filter-fields/gene_symbol/values",
            params={"result_set_id": result_set.id},
        )
        assert response.status_code in {403, 404}


class TestFilterValidationTransport:
    async def test_a_valid_expression_is_canonicalized_without_being_saved(
        self, client: TestClient, harness: Harness
    ) -> None:
        await signed_in(client, harness, "validate-ok@example.org")

        response = client.post(
            "/api/v1/filters/validate",
            json={
                "expression": group(
                    condition("gene_symbol", "in", "CFTR", "ABCA4"),
                    group(
                        condition("allele_frequency", "less_than", 0.01),
                        condition("allele_frequency", "is_missing"),
                        operator="or",
                    ),
                )
            },
            headers=csrf(client, harness),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["valid"] is True
        assert body["canonical_hash"]
        assert body["condition_count"] == 3
        assert body["depth"] == 3
        assert body["issues"] == []
        assert client.get("/api/v1/filters").json()["items"] == []

    async def test_an_unknown_field_is_reported_and_never_repaired(
        self, client: TestClient, harness: Harness
    ) -> None:
        await signed_in(client, harness, "validate-bad@example.org")

        response = client.post(
            "/api/v1/filters/validate",
            json={"expression": group(condition("not_a_field", "equals", "x"))},
            headers=csrf(client, harness),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["valid"] is False
        assert body["canonical"] is None
        assert body["issues"]
        assert body["issues"][0]["path"]

    async def test_an_operator_the_type_does_not_support_is_reported(
        self, client: TestClient, harness: Harness
    ) -> None:
        await signed_in(client, harness, "validate-operator@example.org")

        response = client.post(
            "/api/v1/filters/validate",
            json={"expression": group(condition("allele_frequency", "contains", "0.01"))},
            headers=csrf(client, harness),
        )
        assert response.json()["valid"] is False


class TestSavedFilterTransport:
    async def _create(self, client: TestClient, harness: Harness, user_id: str, **over):
        payload = {
            "name": "Rare in CFTR",
            "scope": "personal",
            "workspace_id": await workspace_of(harness, user_id),
            "content": group(condition("gene_symbol", "equals", "CFTR")),
        }
        payload.update(over)
        return client.post(
            "/api/v1/filters", json=payload, headers=csrf(client, harness)
        )

    async def test_a_saved_filter_is_created_versioned_and_listed(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "filter-owner@example.org")

        created = await self._create(client, harness, user_id)
        assert created.status_code == 201, created.text
        body = created.json()
        definition_id = body["id"]
        assert body["scope"] == "personal"
        assert body["state"] == "published"
        assert body["latest_version_number"] == 1
        assert body["latest_version"]["canonical_hash"]
        assert "manage" in body["capabilities"]

        added = client.post(
            f"/api/v1/filters/{definition_id}/versions",
            json={
                "expected_version": body["version"],
                "content": group(condition("gene_symbol", "equals", "ABCA4")),
                "change_note": "switch gene",
            },
            headers=csrf(client, harness),
        )
        assert added.status_code == 201, added.text
        assert added.json()["latest_version_number"] == 2

        versions = client.get(f"/api/v1/filters/{definition_id}/versions")
        assert versions.status_code == 200
        numbers = [item["version_number"] for item in versions.json()["items"]]
        assert numbers == [1, 2]
        # The first version still says what it always said: history is append-only.
        first = client.get(
            f"/api/v1/filters/{definition_id}", params={"version_number": 1}
        ).json()
        assert first["latest_version"]["canonical"]["children"][0]["values"] == ["CFTR"]

        listed = client.get("/api/v1/filters")
        assert [item["id"] for item in listed.json()["items"]] == [definition_id]

    async def test_a_stale_expected_version_is_a_conflict_not_a_merge(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "filter-concurrent@example.org")
        created = (await self._create(client, harness, user_id)).json()

        first = client.patch(
            f"/api/v1/filters/{created['id']}",
            json={"expected_version": created["version"], "name": "First writer"},
            headers=csrf(client, harness),
        )
        assert first.status_code == 200, first.text

        second = client.patch(
            f"/api/v1/filters/{created['id']}",
            json={"expected_version": created["version"], "name": "Second writer"},
            headers=csrf(client, harness),
        )
        assert second.status_code == 409, second.text
        current = client.get(f"/api/v1/filters/{created['id']}").json()
        assert current["name"] == "First writer"

    async def test_identical_content_is_not_issued_as_a_new_version(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "filter-identical@example.org")
        created = (await self._create(client, harness, user_id)).json()

        response = client.post(
            f"/api/v1/filters/{created['id']}/versions",
            json={
                "expected_version": created["version"],
                "content": group(condition("gene_symbol", "equals", "CFTR")),
            },
            headers=csrf(client, harness),
        )
        assert response.status_code == 409, response.text

    async def test_another_users_personal_filter_is_indistinguishable_from_missing(
        self, client: TestClient, harness: Harness
    ) -> None:
        owner = await create_account(harness, "filter-private-owner@example.org")
        owner_workspace = await workspace_of(harness, owner)
        from tests.support.actors import actor_for

        from app.application.use_cases.query.definitions import (
            CreateConfigurationCommand,
            SavedFilterService,
        )
        from app.domain.value_objects.enums import QueryScope

        services = StubContainer(harness, Path("/tmp")).query_services()
        view = await SavedFilterService(services).create(
            CreateConfigurationCommand(
                actor=await actor_for(harness, owner),
                request=harness.request,
                name="Owner only",
                scope=QueryScope.PERSONAL,
                workspace_id=owner_workspace,
                content=group(condition("gene_symbol", "equals", "CFTR")),
            )
        )

        await signed_in(client, harness, "filter-outsider@example.org")
        response = client.get(f"/api/v1/filters/{view.definition.id}")
        assert response.status_code in {403, 404}
        assert client.get("/api/v1/filters").json()["items"] == []

    async def test_a_platform_scope_cannot_simply_be_claimed(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "filter-climber@example.org")

        refused = await self._create(
            client, harness, user_id, scope="platform", workspace_id=None
        )
        assert refused.status_code == 403, refused.text

    async def test_a_platform_administrator_publishes_a_platform_preset(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await create_account(harness, "preset-admin@example.org")
        await grant_platform_role(harness, user_id, PlatformRole.PLATFORM_ADMINISTRATOR)
        sign_in(client, "preset-admin@example.org")

        created = client.post(
            "/api/v1/filter-presets",
            json={
                "name": "Platform rare variants",
                "scope": "platform",
                "content": group(condition("allele_frequency", "less_than", 0.01)),
                "applicable_contexts": ["result_set"],
            },
            headers=csrf(client, harness),
        )
        assert created.status_code == 201, created.text
        assert created.json()["scope"] == "platform"
        assert created.json()["applicable_contexts"] == ["result_set"]

    async def test_a_write_without_the_csrf_token_is_refused(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "filter-csrf@example.org")
        response = client.post(
            "/api/v1/filters",
            json={
                "name": "No token",
                "scope": "personal",
                "workspace_id": await workspace_of(harness, user_id),
                "content": group(condition("gene_symbol", "equals", "CFTR")),
            },
        )
        # A missing CSRF token invalidates the request's authentication itself.
        assert response.status_code == 401
        # The session survives a refused request.
        assert client.get("/api/v1/filters").status_code == 200


class TestRankingTransport:
    async def test_registered_methods_are_published_as_prioritization_only(
        self, client: TestClient, harness: Harness
    ) -> None:
        await signed_in(client, harness, "ranking-methods@example.org")

        response = client.get("/api/v1/ranking-methods")
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert items
        for method in items:
            assert method["deterministic"] is True
            # Nothing shipped here claims scientific validation.
            assert method["scientifically_validated"] is False

        missing = client.get("/api/v1/ranking-methods/not_a_method")
        assert missing.status_code == 404

    async def test_a_ranking_configuration_is_saved_and_versioned(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "ranking-owner@example.org")
        content = {
            "method_id": "weighted_field_score",
                    "method_version": "1.0.0",
            "components": [
                {
                    "kind": "numeric_descending",
                    "field_id": "read_depth",
                    "weight": 1.0,
                    "scale_min": 0,
                    "scale_max": 100,
                }
            ],
        }

        created = client.post(
            "/api/v1/rankings",
            json={
                "name": "Depth first",
                "scope": "personal",
                "workspace_id": await workspace_of(harness, user_id),
                "content": content,
            },
            headers=csrf(client, harness),
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["method_id"] == "weighted_field_score"
        assert body["latest_version"]["component_count"] == 1

        # A ranking cannot be reached through the filter resource: they are two
        # separately governed kinds, not two views of one thing.
        assert client.get(f"/api/v1/filters/{body['id']}").status_code in {403, 404}

    async def test_a_ranking_naming_an_unknown_field_is_refused(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "ranking-bad@example.org")
        response = client.post(
            "/api/v1/rankings",
            json={
                "name": "Nonsense",
                "scope": "personal",
                "workspace_id": await workspace_of(harness, user_id),
                "content": {
                    "method_id": "weighted_field_score",
                    "method_version": "1.0.0",
                    "components": [
                        {
                            "kind": "numeric_descending",
                            "field_id": "not_a_field",
                            "weight": 1.0,
                            "scale_min": 0,
                            "scale_max": 1,
                        }
                    ],
                },
            },
            headers=csrf(client, harness),
        )
        assert response.status_code == 422, response.text


class TestVariantQueryTransport:
    async def test_a_filtered_page_reports_what_it_ran(
        self, client: TestClient, harness: Harness, surface: str
    ) -> None:
        user_id = await signed_in(client, harness, "query-owner@example.org")
        result_set = await surface_result_set(harness, user_id, surface)

        response = client.post(
            "/api/v1/variants/query",
            json={
                "result_set_id": result_set.id,
                "filter": {"expression": group(condition("gene_symbol", "equals", "CFTR"))},
                "field_ids": ["contig", "position", "gene_symbol", "allele_frequency"],
                "page_size": 10,
                "include_total": True,
            },
            headers=csrf(client, harness),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["returned_count"] == 2
        assert body["total_count"] == 2
        assert {row["gene_symbol"] for row in body["rows"]} == {"CFTR"}
        execution = body["execution"]
        assert execution["outcome"] == "completed"
        assert execution["effective_hash"]
        assert execution["field_dictionary_version"]
        assert body["ranking_execution"] is None

    async def test_a_missing_value_is_neither_zero_nor_a_match(
        self, client: TestClient, harness: Harness, surface: str
    ) -> None:
        user_id = await signed_in(client, harness, "query-missing@example.org")
        result_set = await surface_result_set(harness, user_id, surface)

        def run(expression):
            return client.post(
                "/api/v1/variants/query",
                json={
                    "result_set_id": result_set.id,
                    "filter": {"expression": expression},
                    "field_ids": ["contig", "position", "allele_frequency"],
                },
                headers=csrf(client, harness),
            ).json()

        below = run(group(condition("allele_frequency", "less_than", 0.01)))
        # The reported zero matches; the two never-reported rows do not.
        assert sorted(row["position"] for row in below["rows"]) == [1000, 4000]

        absent = run(group(condition("allele_frequency", "is_missing")))
        assert sorted(row["position"] for row in absent["rows"]) == [3000, 5000]

        present = run(group(condition("allele_frequency", "is_present")))
        assert sorted(row["position"] for row in present["rows"]) == [1000, 2000, 4000]

    async def test_pages_are_bounded_and_resumable_in_a_deterministic_order(
        self, client: TestClient, harness: Harness, surface: str
    ) -> None:
        user_id = await signed_in(client, harness, "query-paged@example.org")
        result_set = await surface_result_set(harness, user_id, surface)
        body = {
            "result_set_id": result_set.id,
            "field_ids": ["contig", "position"],
            "page_size": 2,
        }

        first = client.post(
            "/api/v1/variants/query", json=body, headers=csrf(client, harness)
        ).json()
        assert [row["position"] for row in first["rows"]] == [1000, 2000]
        assert first["next_cursor"]

        second = client.post(
            "/api/v1/variants/query",
            json={**body, "cursor": first["next_cursor"]},
            headers=csrf(client, harness),
        ).json()
        assert [row["position"] for row in second["rows"]] == [3000, 4000]

        oversized = client.post(
            "/api/v1/variants/query",
            json={**body, "page_size": 5000},
            headers=csrf(client, harness),
        )
        assert oversized.status_code == 422

        foreign = client.post(
            "/api/v1/variants/query",
            json={
                **body,
                "cursor": first["next_cursor"],
                "filter": {"expression": group(condition("gene_symbol", "equals", "CFTR"))},
            },
            headers=csrf(client, harness),
        )
        # A cursor from a different query is refused rather than reinterpreted.
        assert foreign.status_code == 422

    async def test_a_ranked_page_records_its_own_execution(
        self, client: TestClient, harness: Harness, surface: str
    ) -> None:
        user_id = await signed_in(client, harness, "query-ranked@example.org")
        result_set = await surface_result_set(harness, user_id, surface)

        response = client.post(
            "/api/v1/variants/query",
            json={
                "result_set_id": result_set.id,
                "field_ids": ["contig", "position", "read_depth"],
                "ranking": {
                    "configuration": {
                        "method_id": "weighted_field_score",
                        "method_version": "1.0.0",
                        "components": [
                            {
                                "kind": "numeric_descending",
                                "field_id": "read_depth",
                                "weight": 1.0,
                                "scale_min": 0,
                                "scale_max": 100,
                            }
                        ],
                    }
                },
            },
            headers=csrf(client, harness),
        )
        assert response.status_code == 200, response.text
        body = response.json()
        ranking = body["ranking_execution"]
        assert ranking["method_id"] == "weighted_field_score"
        assert ranking["tie_breakers"]
        # The row that reports no depth is unscored, not bottom-ranked by a zero.
        assert ranking["unscored_count"] == 1
        assert ranking["scored_count"] == 4
        assert body["rows"][0]["position"] == 4000

    async def test_ranking_never_reintroduces_a_filtered_out_row(
        self, client: TestClient, harness: Harness, surface: str
    ) -> None:
        user_id = await signed_in(client, harness, "query-separation@example.org")
        result_set = await surface_result_set(harness, user_id, surface)

        body = client.post(
            "/api/v1/variants/query",
            json={
                "result_set_id": result_set.id,
                "field_ids": ["contig", "position", "gene_symbol", "read_depth"],
                "filter": {"expression": group(condition("gene_symbol", "equals", "CFTR"))},
                "ranking": {
                    "configuration": {
                        "method_id": "weighted_field_score",
                        "method_version": "1.0.0",
                        "components": [
                            {
                                "kind": "numeric_descending",
                                "field_id": "read_depth",
                                "weight": 1.0,
                                "scale_min": 0,
                                "scale_max": 100,
                            }
                        ],
                    }
                },
            },
            headers=csrf(client, harness),
        ).json()
        assert {row["gene_symbol"] for row in body["rows"]} == {"CFTR"}
        assert body["returned_count"] == 2

    async def test_another_tenants_surface_cannot_be_queried(
        self, client: TestClient, harness: Harness, surface: str
    ) -> None:
        owner = await create_account(harness, "query-tenant-owner@example.org")
        result_set = await surface_result_set(harness, owner, surface)

        await signed_in(client, harness, "query-outsider@example.org")
        response = client.post(
            "/api/v1/variants/query",
            json={"result_set_id": result_set.id},
            headers=csrf(client, harness),
        )
        assert response.status_code in {403, 404}

    async def test_an_expensive_query_is_accepted_as_a_durable_job(
        self, client: TestClient, harness: Harness, surface: str
    ) -> None:
        user_id = await signed_in(client, harness, "query-deferred@example.org")
        result_set = await surface_result_set(harness, user_id, surface)

        response = client.post(
            "/api/v1/variants/query/deferred",
            json={
                "result_set_id": result_set.id,
                "filter": {"expression": group(condition("gene_symbol", "equals", "CFTR"))},
                "max_rows": 1000,
            },
            headers=csrf(client, harness),
        )
        assert response.status_code == 202, response.text
        body = response.json()
        assert body["job_id"].startswith("job")
        assert body["max_rows"] == 1000
        job = harness.repositories.jobs.jobs[body["job_id"]]
        assert job.kind.value == "variant_query"


class TestSavedViewTransport:
    async def test_a_saved_view_carries_presentation_state_only(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "view-owner@example.org")

        created = client.post(
            "/api/v1/saved-views",
            json={
                "name": "Dense table",
                "scope": "personal",
                "workspace_id": await workspace_of(harness, user_id),
                "columns": ["contig", "position", "gene_symbol"],
                "pinned_columns": ["contig"],
                "column_widths": {"contig": 80},
                "sort_field_id": "position",
                "page_size": 100,
            },
            headers=csrf(client, harness),
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["columns"] == ["contig", "position", "gene_symbol"]
        assert body["sort_field_id"] == "position"

        updated = client.patch(
            f"/api/v1/saved-views/{body['id']}",
            json={"expected_version": body["version"], "page_size": 25},
            headers=csrf(client, harness),
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["page_size"] == 25
        assert updated.json()["columns"] == ["contig", "position", "gene_symbol"]

        stale = client.patch(
            f"/api/v1/saved-views/{body['id']}",
            json={"expected_version": body["version"], "page_size": 50},
            headers=csrf(client, harness),
        )
        assert stale.status_code == 409

        deleted = client.request(
            "DELETE",
            f"/api/v1/saved-views/{body['id']}",
            json={"expected_version": updated.json()["version"]},
            headers=csrf(client, harness),
        )
        assert deleted.status_code == 200, deleted.text
        assert deleted.json()["deletion_state"] == "soft_deleted"

    async def test_an_unknown_column_is_refused(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await signed_in(client, harness, "view-bad@example.org")
        response = client.post(
            "/api/v1/saved-views",
            json={
                "name": "Broken",
                "scope": "personal",
                "workspace_id": await workspace_of(harness, user_id),
                "columns": ["not_a_field"],
            },
            headers=csrf(client, harness),
        )
        assert response.status_code == 422, response.text


class TestQueryAdministrationTransport:
    async def test_the_registries_are_closed_to_ordinary_users(
        self, client: TestClient, harness: Harness
    ) -> None:
        await signed_in(client, harness, "admin-ordinary@example.org")
        for path in (
            "/api/v1/administration/query/filter-fields",
            "/api/v1/administration/query/ranking-methods",
        ):
            assert client.get(path).status_code == 403, path

    async def test_a_platform_administrator_reads_the_registries_and_limits(
        self, client: TestClient, harness: Harness
    ) -> None:
        user_id = await create_account(harness, "admin-platform@example.org")
        await grant_platform_role(harness, user_id, PlatformRole.PLATFORM_ADMINISTRATOR)
        sign_in(client, "admin-platform@example.org")

        fields = client.get("/api/v1/administration/query/filter-fields")
        assert fields.status_code == 200, fields.text
        assert fields.json()["fields"]

        methods = client.get("/api/v1/administration/query/ranking-methods")
        assert methods.status_code == 200, methods.text

        limits = client.get("/api/v1/administration/query/limits")
        assert limits.status_code == 200, limits.text
        body = limits.json()
        assert body["max_conditions"] >= 1
        assert body["max_page_size"] >= 1
        assert body["field_dictionary_version"]
