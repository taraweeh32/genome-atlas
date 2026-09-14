"""A run keeps the exact filter and prioritization configuration it used.

This is the reproducibility property of Package 7 stated as a test: an execution
resolves every reference to an exact version number, copies the canonical content
into its own snapshot, and marks those versions referenced. Publishing a new
version of a saved filter or preset afterwards must leave the historical run
completely unchanged.
"""

from __future__ import annotations

import pytest

from app.application.repositories import Page
from app.application.use_cases.analysis.configurations import (
    ConfigurationInputRequest,
    CreateConfigurationVersion,
    CreateConfigurationVersionCommand,
)
from app.application.use_cases.analysis.definitions import (
    ChangeAnalysisState,
    ChangeAnalysisStateCommand,
)
from app.application.use_cases.analysis.executions import (
    RequestExecution,
    RequestExecutionCommand,
)
from app.application.use_cases.query.definitions import (
    AddVersionCommand,
    CreateConfigurationCommand,
    FilterPresetService,
    SavedFilterService,
    SavedRankingService,
)
from app.domain.errors import NotFoundError, ValidationError
from app.domain.query.fields import FIELD_DICTIONARY_VERSION
from app.domain.value_objects.enums import AnalysisState, PlatformRole, QueryScope
from tests.analysis.support import dataset_version_for, project_analysis
from tests.query.support import condition, group, query_services
from tests.support.actors import actor_for, create_account, grant_platform_role
from tests.support.services import build_harness

PAGE = Page(number=1, size=25)


def ranking_content() -> dict:
    return {
        "configuration": {
            "method_id": "weighted_field_score",
            "method_version": "1.0.0",
            "components": [
                {
                    "field_id": "allele_frequency",
                    "kind": "numeric_ascending",
                    "weight": 1.0,
                    "scale_min": 0.0,
                    "scale_max": 0.01,
                }
            ],
        }
    }


async def workspace_of(harness, user_id: str) -> str:
    workspace = await harness.repositories.workspaces.get_personal_for_user(user_id)
    assert workspace is not None
    return workspace.id


async def saved_filter(services, harness, user_id, *, name="Rare Disease", genes=("CFTR",)):
    return await SavedFilterService(services).create(
        CreateConfigurationCommand(
            actor=await actor_for(harness, user_id),
            request=harness.request,
            name=name,
            scope=QueryScope.PERSONAL,
            workspace_id=await workspace_of(harness, user_id),
            content=group(condition("gene_symbol", "in", *genes)),
        )
    )


async def saved_ranking(services, harness, user_id, *, name="Weighted Priority"):
    return await SavedRankingService(services).create(
        CreateConfigurationCommand(
            actor=await actor_for(harness, user_id),
            request=harness.request,
            name=name,
            scope=QueryScope.PERSONAL,
            workspace_id=await workspace_of(harness, user_id),
            content=ranking_content()["configuration"],
            method_id="weighted_field_score",
        )
    )


async def bound_execution(
    harness,
    user_id: str,
    *,
    filtering: dict | None = None,
    ranking: dict | None = None,
    name: str = "Bound Screen",
):
    """An execution requested from a configuration that binds filter and ranking."""
    analysis = await project_analysis(harness, user_id, name=name)
    version = await dataset_version_for(harness, user_id, name=f"{name} Inputs")
    await CreateConfigurationVersion(harness.analysis).execute(
        CreateConfigurationVersionCommand(
            actor=await actor_for(harness, user_id),
            analysis_id=analysis.analysis.id,
            request=harness.request,
            label="v1",
            inputs=(ConfigurationInputRequest(dataset_version_id=version.id, role="primary"),),
            filtering_configuration={"variant_filter": filtering} if filtering else None,
            ranking_configuration={"variant_ranking": ranking} if ranking else None,
            execution_parameters={"threads": 2},
            activate=True,
        )
    )
    await ChangeAnalysisState(harness.analysis).execute(
        ChangeAnalysisStateCommand(
            actor=await actor_for(harness, user_id),
            analysis_id=analysis.analysis.id,
            target=AnalysisState.READY,
            request=harness.request,
        )
    )
    return await RequestExecution(harness.analysis).execute(
        RequestExecutionCommand(
            actor=await actor_for(harness, user_id),
            analysis_id=analysis.analysis.id,
            request=harness.request,
        )
    )


def binding_of(execution) -> dict:
    snapshot = execution.execution.configuration_snapshot
    assert "query_binding" in snapshot, "an execution must record what it filtered by"
    return snapshot["query_binding"]


async def build(tmp_path):
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.org")
    services = query_services(harness, tmp_path / "analytics")
    return harness, user_id, services


async def test_a_saved_filter_and_ranking_are_pinned_to_exact_versions(tmp_path):
    harness, user_id, services = await build(tmp_path)
    saved = await saved_filter(services, harness, user_id)
    ranking = await saved_ranking(services, harness, user_id)

    execution = await bound_execution(
        harness,
        user_id,
        filtering={"filter_definition_id": saved.definition.id},
        ranking={"ranking_definition_id": ranking.definition.id},
    )
    binding = binding_of(execution)

    assert binding["filter"]["saved_filter"]["version_number"] == 1
    assert binding["filter"]["saved_filter"]["canonical_hash"]
    assert binding["ranking"]["saved_ranking"]["version_number"] == 1
    # The dictionary version is part of the snapshot: a field identifier means
    # what the dictionary of that version said it meant.
    assert binding["field_dictionary_version"] == FIELD_DICTIONARY_VERSION
    assert binding["software_version"]


async def test_editing_the_saved_filter_afterwards_leaves_the_run_untouched(tmp_path):
    harness, user_id, services = await build(tmp_path)
    saved = await saved_filter(services, harness, user_id)
    execution = await bound_execution(
        harness, user_id, filtering={"filter_definition_id": saved.definition.id}
    )
    before = binding_of(execution)["filter"]["saved_filter"]

    updated = await SavedFilterService(services).add_version(
        AddVersionCommand(
            actor=await actor_for(harness, user_id),
            request=harness.request,
            definition_id=saved.definition.id,
            expected_version=saved.definition.version,
            content=group(condition("gene_symbol", "in", "CFTR", "ABCA4")),
            change_note="widened the gene list",
        )
    )
    assert updated.latest_version.version_number == 2

    reread = await harness.repositories.analysis_executions.get(execution.execution.id)
    after = reread.configuration_snapshot["query_binding"]["filter"]["saved_filter"]
    assert after == before
    assert after["version_number"] == 1


async def test_a_referenced_version_is_never_rewritten_in_place(tmp_path):
    harness, user_id, services = await build(tmp_path)
    saved = await saved_filter(services, harness, user_id)
    await bound_execution(
        harness, user_id, filtering={"filter_definition_id": saved.definition.id}
    )

    version = await harness.repositories.filter_definitions.find_version(
        definition_id=saved.definition.id, version_number=1
    )
    assert version.is_referenced, "an executed version must be marked referenced"

    await SavedFilterService(services).add_version(
        AddVersionCommand(
            actor=await actor_for(harness, user_id),
            request=harness.request,
            definition_id=saved.definition.id,
            expected_version=saved.definition.version,
            content=group(condition("gene_symbol", "in", "ABCA4")),
        )
    )
    unchanged = await harness.repositories.filter_definitions.find_version(
        definition_id=saved.definition.id, version_number=1
    )
    assert unchanged.canonical == version.canonical
    assert unchanged.canonical_hash == version.canonical_hash


async def test_an_explicit_version_number_is_honoured_over_the_latest(tmp_path):
    harness, user_id, services = await build(tmp_path)
    saved = await saved_filter(services, harness, user_id)
    updated = await SavedFilterService(services).add_version(
        AddVersionCommand(
            actor=await actor_for(harness, user_id),
            request=harness.request,
            definition_id=saved.definition.id,
            expected_version=saved.definition.version,
            content=group(condition("gene_symbol", "in", "ABCA4")),
        )
    )
    assert updated.latest_version.version_number == 2

    execution = await bound_execution(
        harness,
        user_id,
        filtering={
            "filter_definition_id": saved.definition.id,
            "filter_version_number": 1,
        },
    )
    assert binding_of(execution)["filter"]["saved_filter"]["version_number"] == 1


async def test_an_inline_filter_is_frozen_in_canonical_form(tmp_path):
    harness, user_id, _services = await build(tmp_path)
    execution = await bound_execution(
        harness,
        user_id,
        filtering={
            "expression": group(
                condition("gene_symbol", "in", "CFTR", "ABCA4"),
                condition("allele_frequency", "less_than", 0.01),
            )
        },
        ranking=ranking_content(),
    )
    binding = binding_of(execution)

    assert binding["filter"]["custom"]["canonical_hash"].startswith("sha256:")
    assert binding["ranking"]["custom"]["canonical_hash"].startswith("sha256:")
    # Filter and ranking stay in separate sections of the snapshot: neither can be
    # read as part of the other.
    assert "canonical" in binding["filter"]["custom"]
    assert "components" in binding["ranking"]["custom"]["canonical"]


async def test_a_preset_and_a_custom_expression_are_both_recorded(tmp_path):
    harness, user_id, services = await build(tmp_path)
    administrator = await create_account(harness, "platform@example.org")
    await grant_platform_role(harness, administrator, PlatformRole.PLATFORM_ADMINISTRATOR)
    preset = await FilterPresetService(services).create(
        CreateConfigurationCommand(
            actor=await actor_for(harness, administrator),
            request=harness.request,
            name="Rare Disease",
            scope=QueryScope.PLATFORM,
            content=group(condition("allele_frequency", "less_than", 0.01)),
        )
    )
    execution = await bound_execution(
        harness,
        user_id,
        filtering={
            "filter_preset_id": preset.definition.id,
            "expression": group(condition("gene_symbol", "in", "CFTR", "ABCA4")),
        },
    )
    binding = binding_of(execution)

    # Both survive separately, so "which preset was used" and "what the user added"
    # remain answerable years later.
    assert binding["filter"]["preset"]["definition_id"] == preset.definition.id
    assert binding["filter"]["preset"]["version_number"] == 1
    assert binding["filter"]["custom"]["canonical_hash"]


async def test_a_configuration_naming_an_unknown_field_is_refused_at_configuration_time(
    tmp_path,
):
    harness, user_id, _ = await build(tmp_path)
    with pytest.raises(ValidationError):
        await bound_execution(
            harness,
            user_id,
            filtering={"expression": group(condition("pathogenicity_verdict", "equals", "yes"))},
        )


async def test_a_ranking_cannot_be_smuggled_into_the_filter_section(tmp_path):
    harness, user_id, _ = await build(tmp_path)
    with pytest.raises(ValidationError):
        await bound_execution(
            harness,
            user_id,
            filtering={"configuration": ranking_content()["configuration"]},
        )


async def test_a_run_referencing_a_deleted_filter_is_refused_not_silently_dropped(tmp_path):
    harness, user_id, _ = await build(tmp_path)
    with pytest.raises(NotFoundError):
        await bound_execution(
            harness, user_id, filtering={"filter_definition_id": "flt_missing"}
        )


async def test_an_unbound_analysis_records_no_query_binding_content(tmp_path):
    harness, user_id, _ = await build(tmp_path)
    execution = await bound_execution(harness, user_id)
    binding = binding_of(execution)
    # No filter is recorded as no filter, never as a filter that keeps everything.
    assert binding["filter"] == {}
    assert binding["ranking"] == {}
