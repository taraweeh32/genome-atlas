"""Datasets, versions, tenant isolation and the acceptance gate.

These tests pin the rules the frontend is never allowed to decide: who may see a
dataset, who may change it, when a version may become a scientific input, and
what soft deletion does and does not destroy.
"""

from __future__ import annotations

import pytest

from app.application.repositories import Page
from app.application.use_cases.data.datasets import (
    ChangeDatasetState,
    ChangeDatasetStateCommand,
    CreateDataset,
    CreateDatasetCommand,
    DecideDatasetVersion,
    DecideDatasetVersionCommand,
    GetDataset,
    GetDatasetQuery,
    ListDatasets,
    ListDatasetsQuery,
    SoftDeleteDataset,
    SoftDeleteDatasetCommand,
    UpdateDataset,
    UpdateDatasetCommand,
)
from app.domain.errors import (
    AuthorizationError,
    ConflictError,
    InvalidStateTransitionError,
    NotFoundError,
)
from app.domain.value_objects.enums import (
    DatasetKind,
    DatasetState,
    DatasetVersionState,
    DeletionState,
    ReferenceBuildDeclaration,
)
from tests.data.support import draft_version, personal_dataset, uploaded_artifact
from tests.support.actors import actor_for, create_account
from tests.support.services import build_harness

PAGE = Page(number=1, size=25)


async def test_a_new_dataset_starts_as_a_draft_owned_by_its_creator() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")

    view = await personal_dataset(harness, owner)

    assert view.dataset.state is DatasetState.DRAFT
    assert view.dataset.created_by == owner
    assert view.dataset.owner_user_id == owner
    # No version exists yet: creating a dataset never fabricates an input.
    assert view.dataset.current_version_id is None
    assert "write" in view.capabilities and "download" in view.capabilities
    assert any(record.action == "dataset.created" for record in harness.repositories.audit.records)


async def test_two_datasets_cannot_share_a_name_in_the_same_scope() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    await personal_dataset(harness, owner, name="Cohort A")

    with pytest.raises(ConflictError):
        await personal_dataset(harness, owner, name="cohort a")


async def test_another_users_dataset_is_not_readable_even_with_its_identifier() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    stranger = await create_account(harness, "stranger@example.test")
    view = await personal_dataset(harness, owner)

    # Existence is never disclosed by probing: the refusal names neither the
    # dataset nor whether it exists at all.
    with pytest.raises((AuthorizationError, NotFoundError)):
        await GetDataset(harness.data).execute(
            GetDatasetQuery(
                actor=await actor_for(harness, stranger),
                dataset_id=view.dataset.id,
                request=harness.request,
            )
        )

    listing = await ListDatasets(harness.data).execute(
        ListDatasetsQuery(
            actor=await actor_for(harness, stranger), page=PAGE, request=harness.request
        )
    )
    assert listing.total == 0


async def test_a_stranger_cannot_write_to_a_dataset_it_cannot_reach() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    stranger = await create_account(harness, "stranger@example.test")
    view = await personal_dataset(harness, owner)

    with pytest.raises((AuthorizationError, NotFoundError)):
        await UpdateDataset(harness.data).execute(
            UpdateDatasetCommand(
                actor=await actor_for(harness, stranger),
                dataset_id=view.dataset.id,
                name="Renamed By Stranger",
                description=None,
                request=harness.request,
            )
        )
    stored = await harness.repositories.datasets.get(view.dataset.id)
    assert stored.name == view.dataset.name


async def test_creating_a_dataset_in_an_unreachable_workspace_is_refused() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    stranger = await create_account(harness, "stranger@example.test")
    workspace = await harness.repositories.workspaces.get_personal_for_user(owner)

    with pytest.raises((AuthorizationError, NotFoundError)):
        await CreateDataset(harness.data).execute(
            CreateDatasetCommand(
                actor=await actor_for(harness, stranger),
                workspace_id=workspace.id,
                project_id=None,
                name="Planted",
                kind=DatasetKind.VARIANT_CALLS,
                description=None,
                reference_build_declared=ReferenceBuildDeclaration.GRCH38,
                request=harness.request,
            )
        )


async def test_an_archived_dataset_is_hidden_from_listings_and_refuses_edits() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    view = await personal_dataset(harness, owner)

    await ChangeDatasetState(harness.data).execute(
        ChangeDatasetStateCommand(
            actor=await actor_for(harness, owner),
            dataset_id=view.dataset.id,
            target_state=DatasetState.ARCHIVED,
            reason="cohort retired",
            request=harness.request,
        )
    )

    listing = await ListDatasets(harness.data).execute(
        ListDatasetsQuery(
            actor=await actor_for(harness, owner), page=PAGE, request=harness.request
        )
    )
    assert listing.total == 0

    with pytest.raises(ConflictError):
        await UpdateDataset(harness.data).execute(
            UpdateDatasetCommand(
                actor=await actor_for(harness, owner),
                dataset_id=view.dataset.id,
                name="Renamed",
                description=None,
                request=harness.request,
            )
        )


async def test_soft_deleting_a_dataset_keeps_its_versions_and_stored_objects() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    dataset = (await personal_dataset(harness, owner)).dataset
    version = (await draft_version(harness, owner, dataset.id)).version
    _, artifact, _ = await uploaded_artifact(harness, owner, version.id)

    await SoftDeleteDataset(harness.data).execute(
        SoftDeleteDatasetCommand(
            actor=await actor_for(harness, owner),
            dataset_id=dataset.id,
            reason="mistake",
            request=harness.request,
        )
    )

    stored = await harness.repositories.datasets.get(dataset.id)
    assert stored.deletion_state is DeletionState.SOFT_DELETED
    assert stored.retention_expires_at is not None
    # Lineage and bytes survive: this is a retention state, not destruction.
    assert await harness.repositories.dataset_versions.get(version.id) is not None
    assert artifact.storage_key in harness.storage.objects
    assert harness.storage.deleted == []

    with pytest.raises(NotFoundError):
        await GetDataset(harness.data).execute(
            GetDatasetQuery(
                actor=await actor_for(harness, owner),
                dataset_id=dataset.id,
                request=harness.request,
            )
        )


async def test_a_version_without_artifacts_cannot_be_accepted() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    dataset = (await personal_dataset(harness, owner)).dataset
    view = await draft_version(harness, owner, dataset.id)

    assert view.acceptance_blocked_reason == "no_artifacts"
    with pytest.raises(ConflictError):
        await DecideDatasetVersion(harness.data).execute(
            DecideDatasetVersionCommand(
                actor=await actor_for(harness, owner),
                version_id=view.version.id,
                accept=True,
                reason=None,
                request=harness.request,
            )
        )


async def test_accepting_a_second_version_supersedes_the_first_without_rewriting_it() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    dataset = (await personal_dataset(harness, owner)).dataset

    first = (await draft_version(harness, owner, dataset.id)).version
    await uploaded_artifact(harness, owner, first.id, filename="first.tsv")
    accepted_first = await DecideDatasetVersion(harness.data).execute(
        DecideDatasetVersionCommand(
            actor=await actor_for(harness, owner),
            version_id=first.id,
            accept=True,
            reason=None,
            request=harness.request,
        )
    )
    assert accepted_first.version.state is DatasetVersionState.ACCEPTED

    second = (await draft_version(harness, owner, dataset.id)).version
    await uploaded_artifact(harness, owner, second.id, filename="second.tsv")
    await DecideDatasetVersion(harness.data).execute(
        DecideDatasetVersionCommand(
            actor=await actor_for(harness, owner),
            version_id=second.id,
            accept=True,
            reason=None,
            request=harness.request,
        )
    )

    superseded = await harness.repositories.dataset_versions.get(first.id)
    assert superseded.state is DatasetVersionState.SUPERSEDED
    assert superseded.superseded_by_version_id == second.id
    # The historical version keeps its own checksum and acceptance record: a
    # correction never rewrites the input a past result was produced from.
    assert superseded.accepted_at == accepted_first.version.accepted_at
    assert superseded.version_number < second.version_number

    dataset_now = await harness.repositories.datasets.get(dataset.id)
    assert dataset_now.current_version_id == second.id


async def test_a_decided_version_cannot_be_decided_again() -> None:
    harness = build_harness()
    owner = await create_account(harness, "owner@example.test")
    dataset = (await personal_dataset(harness, owner)).dataset
    version = (await draft_version(harness, owner, dataset.id)).version
    await uploaded_artifact(harness, owner, version.id)

    decide = DecideDatasetVersion(harness.data)

    def command(*, accept: bool) -> DecideDatasetVersionCommand:
        return DecideDatasetVersionCommand(
            actor=actor,
            version_id=version.id,
            accept=accept,
            reason="reviewed",
            request=harness.request,
        )

    actor = await actor_for(harness, owner)
    await decide.execute(command(accept=True))

    # An accepted version is a settled scientific input: neither a second
    # acceptance nor a late rejection may rewrite it.
    with pytest.raises(InvalidStateTransitionError):
        await decide.execute(command(accept=False))
    with pytest.raises((ConflictError, InvalidStateTransitionError)):
        await decide.execute(command(accept=True))
