"""Governance of saved filters, presets, rankings and saved views.

These tests are about *custody* rather than filtering: who may create a
configuration in a given scope, what happens to a concurrent edit, and whether a
version's content can ever be rewritten. The filtering behaviour itself is
covered by the domain and execution suites.
"""

from __future__ import annotations

import pytest

from app.application.use_cases.query.definitions import (
    AddVersionCommand,
    CreateConfigurationCommand,
    FilterPresetService,
    GetConfigurationQuery,
    LifecycleCommand,
    ListConfigurationsQuery,
    SavedFilterService,
    SavedRankingService,
    UpdateMetadataCommand,
)
from app.application.use_cases.query.views import (
    CreateSavedViewCommand,
    ListSavedViewsQuery,
    SavedViewQuery,
    SavedViewService,
    UpdateSavedViewCommand,
)
from app.domain.errors import (
    AuthorizationError,
    ConcurrencyConflictError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.domain.value_objects.enums import PlatformRole, QueryDefinitionState, QueryScope
from app.application.repositories import Page
from tests.support.actors import actor_for, create_account, grant_platform_role
from tests.query.support import condition, group, query_services

from tests.support.memory import build_harness

async def build(tmp_path):
    harness = build_harness()
    user_id = await create_account(harness, "curator@example.org")
    services = query_services(harness, tmp_path)
    return harness, user_id, services


async def workspace_of(harness, user_id: str) -> str:
    workspace = await harness.repositories.workspaces.get_personal_for_user(user_id)
    assert workspace is not None
    return workspace.id


async def personal_filter(services, harness, user_id, *, name="Rare", gene="CFTR"):
    return await SavedFilterService(services).create(
        CreateConfigurationCommand(
            actor=await actor_for(harness, user_id),
            request=harness.request,
            name=name,
            scope=QueryScope.PERSONAL,
            workspace_id=await workspace_of(harness, user_id),
            content=group(condition("gene_symbol", "equals", gene)),
        )
    )


def ranking_configuration():
    return {
        "method_id": "weighted_field_score",
        "method_version": "1.0.0",
        "direction": "descending",
        "components": [
            {
                "field_id": "allele_frequency",
                "kind": "numeric_ascending",
                "weight": 1.0,
                "scale_minimum": 0.0,
                "scale_maximum": 0.01,
                "missing_behaviour": "exclude",
            }
        ],
    }


class TestCreationScope:
    async def test_a_personal_configuration_requires_its_workspace(self, tmp_path) -> None:
        harness, user_id, services = await build(tmp_path)
        with pytest.raises(ValidationError):
            await SavedFilterService(services).create(
                CreateConfigurationCommand(
                    actor=await actor_for(harness, user_id),
                    request=harness.request,
                    name="No home",
                    scope=QueryScope.PERSONAL,
                    content=group(condition("gene_symbol", "equals", "CFTR")),
                )
            )

    async def test_a_platform_scope_cannot_be_claimed_by_an_ordinary_user(
        self, tmp_path
    ) -> None:
        harness, user_id, services = await build(tmp_path)
        with pytest.raises(AuthorizationError):
            await FilterPresetService(services).create(
                CreateConfigurationCommand(
                    actor=await actor_for(harness, user_id),
                    request=harness.request,
                    name="Global",
                    scope=QueryScope.PLATFORM,
                    content=group(condition("gene_symbol", "equals", "CFTR")),
                )
            )

    async def test_a_platform_administrator_may_publish_a_platform_preset(
        self, tmp_path
    ) -> None:
        harness, user_id, services = await build(tmp_path)
        await grant_platform_role(harness, user_id, PlatformRole.PLATFORM_ADMINISTRATOR)
        view = await FilterPresetService(services).create(
            CreateConfigurationCommand(
                actor=await actor_for(harness, user_id),
                request=harness.request,
                name="Global",
                scope=QueryScope.PLATFORM,
                content=group(condition("gene_symbol", "equals", "CFTR")),
                publish=True,
            )
        )
        assert view.definition.scope is QueryScope.PLATFORM
        assert view.definition.state is QueryDefinitionState.PUBLISHED


class TestPersonalIsolation:
    async def test_another_account_neither_lists_nor_reads_a_personal_filter(
        self, tmp_path
    ) -> None:
        harness, user_id, services = await build(tmp_path)
        saved = await personal_filter(services, harness, user_id)
        outsider = await create_account(harness, "outsider@example.org")

        listing = await SavedFilterService(services).list(
            ListConfigurationsQuery(
                actor=await actor_for(harness, outsider),
                request=harness.request,
                page=Page(number=1, size=20),
            )
        )
        assert all(item.id != saved.definition.id for item in listing.items)

        with pytest.raises((AuthorizationError, NotFoundError)):
            await SavedFilterService(services).get(
                GetConfigurationQuery(
                    actor=await actor_for(harness, outsider),
                    request=harness.request,
                    definition_id=saved.definition.id,
                )
            )

    async def test_an_outsider_cannot_append_a_version(self, tmp_path) -> None:
        harness, user_id, services = await build(tmp_path)
        saved = await personal_filter(services, harness, user_id)
        outsider = await create_account(harness, "outsider2@example.org")
        with pytest.raises((AuthorizationError, NotFoundError)):
            await SavedFilterService(services).add_version(
                AddVersionCommand(
                    actor=await actor_for(harness, outsider),
                    request=harness.request,
                    definition_id=saved.definition.id,
                    expected_version=saved.definition.version,
                    content=group(condition("gene_symbol", "equals", "ABCA4")),
                )
            )


class TestConcurrencyAndVersioning:
    async def test_a_stale_edit_is_refused_rather_than_overwriting(self, tmp_path) -> None:
        harness, user_id, services = await build(tmp_path)
        saved = await personal_filter(services, harness, user_id)
        service = SavedFilterService(services)
        await service.update_metadata(
            UpdateMetadataCommand(
                actor=await actor_for(harness, user_id),
                request=harness.request,
                definition_id=saved.definition.id,
                expected_version=saved.definition.version,
                name="Renamed once",
            )
        )
        with pytest.raises(ConcurrencyConflictError):
            await service.update_metadata(
                UpdateMetadataCommand(
                    actor=await actor_for(harness, user_id),
                    request=harness.request,
                    definition_id=saved.definition.id,
                    expected_version=saved.definition.version,
                    name="Renamed from a stale read",
                )
            )

    async def test_identical_content_is_not_issued_as_a_new_version(self, tmp_path) -> None:
        harness, user_id, services = await build(tmp_path)
        saved = await personal_filter(services, harness, user_id)
        with pytest.raises(ConflictError):
            await SavedFilterService(services).add_version(
                AddVersionCommand(
                    actor=await actor_for(harness, user_id),
                    request=harness.request,
                    definition_id=saved.definition.id,
                    expected_version=saved.definition.version,
                    content=group(condition("gene_symbol", "equals", "CFTR")),
                )
            )

    async def test_appending_a_version_leaves_the_previous_content_intact(
        self, tmp_path
    ) -> None:
        harness, user_id, services = await build(tmp_path)
        saved = await personal_filter(services, harness, user_id)
        service = SavedFilterService(services)
        first_hash = saved.latest_version.canonical_hash
        updated = await service.add_version(
            AddVersionCommand(
                actor=await actor_for(harness, user_id),
                request=harness.request,
                definition_id=saved.definition.id,
                expected_version=saved.definition.version,
                content=group(condition("gene_symbol", "equals", "ABCA4")),
            )
        )
        assert updated.latest_version.version_number == 2
        versions = await service.list_versions(
            GetConfigurationQuery(
                actor=await actor_for(harness, user_id),
                request=harness.request,
                definition_id=saved.definition.id,
            )
        )
        by_number = {version.version_number: version for version in versions}
        assert by_number[1].canonical_hash == first_hash
        assert by_number[2].canonical_hash != first_hash

    async def test_an_earlier_version_is_still_readable_by_number(self, tmp_path) -> None:
        harness, user_id, services = await build(tmp_path)
        saved = await personal_filter(services, harness, user_id)
        service = SavedFilterService(services)
        await service.add_version(
            AddVersionCommand(
                actor=await actor_for(harness, user_id),
                request=harness.request,
                definition_id=saved.definition.id,
                expected_version=saved.definition.version,
                content=group(condition("gene_symbol", "equals", "ABCA4")),
            )
        )
        view = await service.get(
            GetConfigurationQuery(
                actor=await actor_for(harness, user_id),
                request=harness.request,
                definition_id=saved.definition.id,
                version_number=1,
            )
        )
        assert view.latest_version.version_number == 1
        assert view.latest_version.canonical_hash == saved.latest_version.canonical_hash


class TestLifecycle:
    async def test_archive_then_restore_keeps_the_version_history(self, tmp_path) -> None:
        harness, user_id, services = await build(tmp_path)
        saved = await personal_filter(services, harness, user_id)
        service = SavedFilterService(services)
        archived = await service.archive(
            LifecycleCommand(
                actor=await actor_for(harness, user_id),
                request=harness.request,
                definition_id=saved.definition.id,
                expected_version=saved.definition.version,
            )
        )
        assert archived.definition.state is QueryDefinitionState.ARCHIVED
        restored = await service.restore(
            LifecycleCommand(
                actor=await actor_for(harness, user_id),
                request=harness.request,
                definition_id=saved.definition.id,
                expected_version=archived.definition.version,
            )
        )
        assert restored.definition.state is QueryDefinitionState.PUBLISHED
        versions = await service.list_versions(
            GetConfigurationQuery(
                actor=await actor_for(harness, user_id),
                request=harness.request,
                definition_id=saved.definition.id,
            )
        )
        assert len(versions) == 1

    async def test_a_withdrawn_definition_keeps_its_versions(self, tmp_path) -> None:
        harness, user_id, services = await build(tmp_path)
        saved = await personal_filter(services, harness, user_id)
        service = SavedFilterService(services)
        await service.soft_delete(
            LifecycleCommand(
                actor=await actor_for(harness, user_id),
                request=harness.request,
                definition_id=saved.definition.id,
                expected_version=saved.definition.version,
            )
        )
        stored = await harness.repositories.filter_definitions.list_versions(
            saved.definition.id
        )
        assert len(stored) == 1


class TestRankingConfigurations:
    async def test_a_ranking_is_a_separate_configuration_from_a_filter(
        self, tmp_path
    ) -> None:
        harness, user_id, services = await build(tmp_path)
        await personal_filter(services, harness, user_id)
        ranking = await SavedRankingService(services).create(
            CreateConfigurationCommand(
                actor=await actor_for(harness, user_id),
                request=harness.request,
                name="Priority",
                scope=QueryScope.PERSONAL,
                workspace_id=await workspace_of(harness, user_id),
                content=ranking_configuration(),
                method_id="weighted_field_score",
            )
        )
        filters = await SavedFilterService(services).list(
            ListConfigurationsQuery(
                actor=await actor_for(harness, user_id),
                request=harness.request,
                page=Page(number=1, size=20),
            )
        )
        assert all(item.id != ranking.definition.id for item in filters.items)

    async def test_a_filter_expression_is_refused_as_a_ranking(self, tmp_path) -> None:
        harness, user_id, services = await build(tmp_path)
        with pytest.raises(ValidationError):
            await SavedRankingService(services).create(
                CreateConfigurationCommand(
                    actor=await actor_for(harness, user_id),
                    request=harness.request,
                    name="Not a ranking",
                    scope=QueryScope.PERSONAL,
                    workspace_id=await workspace_of(harness, user_id),
                    content=group(condition("gene_symbol", "equals", "CFTR")),
                )
            )


class TestSavedViews:
    async def test_a_saved_view_is_presentation_state_only(self, tmp_path) -> None:
        harness, user_id, services = await build(tmp_path)
        view = await SavedViewService(services).create(
            CreateSavedViewCommand(
                actor=await actor_for(harness, user_id),
                request=harness.request,
                name="Dense",
                scope=QueryScope.PERSONAL,
                workspace_id=await workspace_of(harness, user_id),
                columns=("gene_symbol", "allele_frequency"),
                sort_field_id="position",
                page_size=25,
            )
        )
        assert view.view.columns == ("gene_symbol", "allele_frequency")
        assert view.view.page_size == 25

    async def test_an_outsider_neither_lists_nor_reads_a_personal_view(
        self, tmp_path
    ) -> None:
        harness, user_id, services = await build(tmp_path)
        view = await SavedViewService(services).create(
            CreateSavedViewCommand(
                actor=await actor_for(harness, user_id),
                request=harness.request,
                name="Mine",
                scope=QueryScope.PERSONAL,
                workspace_id=await workspace_of(harness, user_id),
                columns=("gene_symbol",),
            )
        )
        outsider = await create_account(harness, "view-outsider@example.org")
        listing = await SavedViewService(services).list(
            ListSavedViewsQuery(
                actor=await actor_for(harness, outsider),
                request=harness.request,
                page=Page(number=1, size=20),
            )
        )
        assert all(item.id != view.view.id for item in listing.items)
        with pytest.raises((AuthorizationError, NotFoundError)):
            await SavedViewService(services).get(
                SavedViewQuery(
                    actor=await actor_for(harness, outsider),
                    request=harness.request,
                    view_id=view.view.id,
                )
            )

    async def test_a_stale_view_edit_is_refused(self, tmp_path) -> None:
        harness, user_id, services = await build(tmp_path)
        service = SavedViewService(services)
        view = await service.create(
            CreateSavedViewCommand(
                actor=await actor_for(harness, user_id),
                request=harness.request,
                name="Mine",
                scope=QueryScope.PERSONAL,
                workspace_id=await workspace_of(harness, user_id),
                columns=("gene_symbol",),
            )
        )
        await service.update(
            UpdateSavedViewCommand(
                actor=await actor_for(harness, user_id),
                request=harness.request,
                view_id=view.view.id,
                expected_version=view.view.version,
                changes={"name": "Renamed"},
            )
        )
        with pytest.raises(ConcurrencyConflictError):
            await service.update(
                UpdateSavedViewCommand(
                    actor=await actor_for(harness, user_id),
                    request=harness.request,
                    view_id=view.view.id,
                    expected_version=view.view.version,
                    changes={"name": "Stale"},
                )
            )
