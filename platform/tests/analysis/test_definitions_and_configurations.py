"""Analysis definitions, configuration versioning and immutability.

What these tests pin:

* A configuration version is never edited. Editing produces a new numbered
  version, and an execution that referenced an older version keeps referencing
  exactly what it used.
* Definition state and configuration state are separate facts.
* An identifier alone opens nothing: a member of another workspace gets the same
  answer as for a resource that does not exist.
"""

from __future__ import annotations

import pytest

from app.application.use_cases.analysis.configurations import (
    ActivateConfiguration,
    ActivateConfigurationCommand,
    ConfigurationInputRequest,
    CreateConfigurationVersion,
    CreateConfigurationVersionCommand,
    GetConfiguration,
    GetConfigurationQuery,
    ListConfigurations,
    ListConfigurationsQuery,
)
from app.application.use_cases.analysis.definitions import (
    ChangeAnalysisState,
    ChangeAnalysisStateCommand,
    CreateAnalysis,
    CreateAnalysisCommand,
    DeleteAnalysis,
    DeleteAnalysisCommand,
    GetAnalysis,
    GetAnalysisQuery,
    ListAnalyses,
    ListAnalysesQuery,
    UpdateAnalysis,
    UpdateAnalysisCommand,
)
from app.domain.errors import (
    AuthorizationError,
    ConflictError,
    InvalidStateTransitionError,
    NotFoundError,
    ValidationError,
)
from app.domain.value_objects.enums import AnalysisKind, AnalysisState, DeletionState
from tests.analysis.support import PAGE, configured_analysis, dataset_version_for, project_analysis
from tests.support.actors import actor_for, create_account
from tests.support.services import build_harness
from tests.tenancy.test_projects_and_isolation import personal_project

pytestmark = pytest.mark.anyio


async def _reuse_inputs(harness, analysis_id: str):
    """The inputs the current configuration declares, re-declared verbatim."""
    analysis = await harness.repositories.analyses.get(analysis_id)
    inputs = await harness.repositories.analysis_configurations.list_inputs(
        analysis.current_configuration_id
    )
    return tuple(
        ConfigurationInputRequest(dataset_version_id=item.dataset_version_id, role=item.role)
        for item in inputs
    )


async def test_analysis_is_created_in_the_projects_workspace() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    project = await personal_project(harness, user_id)

    view = await project_analysis(harness, user_id, project_id=project.project.id)

    workspace = await harness.repositories.workspaces.get_personal_for_user(user_id)
    assert view.analysis.workspace_id == workspace.id
    assert view.analysis.state is AnalysisState.DRAFT
    # A definition with no configuration is never executable.
    assert view.analysis.is_executable is False


async def test_duplicate_analysis_name_in_a_project_is_rejected() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    project = await personal_project(harness, user_id)
    await project_analysis(harness, user_id, project_id=project.project.id, name="Screen")

    with pytest.raises(ConflictError):
        await project_analysis(harness, user_id, project_id=project.project.id, name="Screen")


async def test_creating_an_analysis_in_another_users_project_is_not_found() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.test")
    stranger_id = await create_account(harness, "stranger@example.test")
    project = await personal_project(harness, owner_id)

    with pytest.raises((AuthorizationError, NotFoundError)):
        await CreateAnalysis(harness.analysis).execute(
            CreateAnalysisCommand(
                actor=await actor_for(harness, stranger_id),
                workspace_id="",
                project_id=project.project.id,
                name="Intrusion",
                kind=AnalysisKind.VARIANT_PRIORITIZATION,
                description=None,
                capability_key=None,
                request=harness.request,
            )
        )


async def test_editing_a_configuration_creates_a_new_version() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    analysis, first = await configured_analysis(harness, user_id)

    second = await CreateConfigurationVersion(harness.analysis).execute(
        CreateConfigurationVersionCommand(
            actor=await actor_for(harness, user_id),
            analysis_id=analysis.analysis.id,
            request=harness.request,
            label="v2",
            inputs=await _reuse_inputs(harness, analysis.analysis.id),
            filtering_configuration={"min_depth": 30},
            activate=True,
        )
    )

    assert first.configuration.version_number == 1
    assert second.configuration.version_number == 2
    # The first version is untouched: history is never rewritten in place.
    reloaded = await GetConfiguration(harness.analysis).execute(
        GetConfigurationQuery(
            actor=await actor_for(harness, user_id),
            analysis_id=analysis.analysis.id,
            configuration_id=first.configuration.id,
            request=harness.request,
        )
    )
    assert reloaded.configuration.filtering_configuration == {"min_depth": 10}
    assert reloaded.is_current is False


async def test_activation_moves_the_current_configuration_pointer() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    analysis, first = await configured_analysis(harness, user_id)
    second = await CreateConfigurationVersion(harness.analysis).execute(
        CreateConfigurationVersionCommand(
            actor=await actor_for(harness, user_id),
            analysis_id=analysis.analysis.id,
            request=harness.request,
            label="v2",
            inputs=await _reuse_inputs(harness, analysis.analysis.id),
        )
    )

    activated = await ActivateConfiguration(harness.analysis).execute(
        ActivateConfigurationCommand(
            actor=await actor_for(harness, user_id),
            analysis_id=analysis.analysis.id,
            configuration_id=second.configuration.id,
            request=harness.request,
        )
    )

    assert activated.is_current is True
    current = await GetAnalysis(harness.analysis).execute(
        GetAnalysisQuery(
            actor=await actor_for(harness, user_id),
            analysis_id=analysis.analysis.id,
            request=harness.request,
        )
    )
    assert current.analysis.current_configuration_id == second.configuration.id
    assert current.analysis.current_configuration_id != first.configuration.id


async def test_configuration_input_must_be_a_readable_dataset_version() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.test")
    stranger_id = await create_account(harness, "stranger@example.test")
    version = await dataset_version_for(harness, stranger_id, name="Foreign")
    analysis = await project_analysis(harness, owner_id)

    with pytest.raises((NotFoundError, AuthorizationError)):
        await CreateConfigurationVersion(harness.analysis).execute(
            CreateConfigurationVersionCommand(
                actor=await actor_for(harness, owner_id),
                analysis_id=analysis.analysis.id,
                request=harness.request,
                inputs=(
                    ConfigurationInputRequest(dataset_version_id=version.id, role="primary"),
                ),
            )
        )


async def test_duplicate_input_role_is_rejected() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    analysis = await project_analysis(harness, user_id)
    version = await dataset_version_for(harness, user_id)

    with pytest.raises(ValidationError):
        await CreateConfigurationVersion(harness.analysis).execute(
            CreateConfigurationVersionCommand(
                actor=await actor_for(harness, user_id),
                analysis_id=analysis.analysis.id,
                request=harness.request,
                inputs=(
                    ConfigurationInputRequest(dataset_version_id=version.id, role="primary"),
                    ConfigurationInputRequest(dataset_version_id=version.id, role="primary"),
                ),
            )
        )


async def test_invalid_analysis_state_transition_is_refused() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    analysis = await project_analysis(harness, user_id)

    with pytest.raises((InvalidStateTransitionError, ValidationError)):
        await ChangeAnalysisState(harness.analysis).execute(
            ChangeAnalysisStateCommand(
                actor=await actor_for(harness, user_id),
                analysis_id=analysis.analysis.id,
                target=AnalysisState.ACTIVE,
                request=harness.request,
            )
        )


async def test_update_and_listing_stay_scoped_to_the_caller() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.test")
    stranger_id = await create_account(harness, "stranger@example.test")
    analysis = await project_analysis(harness, owner_id)

    await UpdateAnalysis(harness.analysis).execute(
        UpdateAnalysisCommand(
            actor=await actor_for(harness, owner_id),
            analysis_id=analysis.analysis.id,
            request=harness.request,
            description="Trio workflow",
            execution_defaults={"priority": 50},
        )
    )

    mine = await ListAnalyses(harness.analysis).execute(
        ListAnalysesQuery(
            actor=await actor_for(harness, owner_id), page=PAGE, request=harness.request
        )
    )
    theirs = await ListAnalyses(harness.analysis).execute(
        ListAnalysesQuery(
            actor=await actor_for(harness, stranger_id), page=PAGE, request=harness.request
        )
    )

    assert [view.analysis.id for view in mine.items] == [analysis.analysis.id]
    assert mine.items[0].analysis.description == "Trio workflow"
    assert theirs.items == ()

    with pytest.raises((NotFoundError, AuthorizationError)):
        await GetAnalysis(harness.analysis).execute(
            GetAnalysisQuery(
                actor=await actor_for(harness, stranger_id),
                analysis_id=analysis.analysis.id,
                request=harness.request,
            )
        )


async def test_soft_deleted_analysis_is_retained_and_hidden() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    analysis = await project_analysis(harness, user_id)

    await DeleteAnalysis(harness.analysis).execute(
        DeleteAnalysisCommand(
            actor=await actor_for(harness, user_id),
            analysis_id=analysis.analysis.id,
            reason="superseded",
            request=harness.request,
        )
    )

    stored = await harness.repositories.analyses.get(analysis.analysis.id)
    assert stored.deletion_state is DeletionState.SOFT_DELETED
    assert stored.retention_expires_at is not None

    with pytest.raises((NotFoundError, AuthorizationError)):
        await GetAnalysis(harness.analysis).execute(
            GetAnalysisQuery(
                actor=await actor_for(harness, user_id),
                analysis_id=analysis.analysis.id,
                request=harness.request,
            )
        )


async def test_configuration_listing_is_ordered_and_marks_the_current_version() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    analysis, first = await configured_analysis(harness, user_id)
    await CreateConfigurationVersion(harness.analysis).execute(
        CreateConfigurationVersionCommand(
            actor=await actor_for(harness, user_id),
            analysis_id=analysis.analysis.id,
            request=harness.request,
            label="v2",
            inputs=await _reuse_inputs(harness, analysis.analysis.id),
        )
    )

    listing = await ListConfigurations(harness.analysis).execute(
        ListConfigurationsQuery(
            actor=await actor_for(harness, user_id),
            analysis_id=analysis.analysis.id,
            page=PAGE,
            request=harness.request,
        )
    )

    numbers = [view.configuration.version_number for view in listing.items]
    assert sorted(numbers, reverse=True) == numbers
    current = [view for view in listing.items if view.is_current]
    assert [view.configuration.id for view in current] == [first.configuration.id]
