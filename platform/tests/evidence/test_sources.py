"""The evidence source registry: identity, versioning, lifecycle, authorization."""

from __future__ import annotations

import pytest

from app.application.use_cases.evidence.sources import (
    EvidenceSourceCatalogue,
    ListSourcesQuery,
    RegisterEvidenceSource,
    RegisterSourceCommand,
    TransitionEvidenceSource,
    TransitionSourceCommand,
)
from app.domain.errors import AuthorizationError, ConflictError, ValidationError
from app.domain.value_objects.enums import (
    EvidenceCategory,
    EvidenceSourceCategory,
    ScientificResourceState,
)
from tests.evidence.support import (
    PAGE,
    RELEASED_AT,
    RETRIEVED_AT,
    SOURCE_KEY,
    SOURCE_VERSION,
    SUPPLIES,
    activate_source,
    platform_admin,
    registered_source,
)
from tests.support.actors import actor_for, create_account
from tests.support.services import build_harness


async def test_registration_records_source_identity_release_and_retrieval():
    harness = build_harness()
    admin_id = await platform_admin(harness)

    source = await registered_source(harness, admin_id, activate=False)

    assert (source.source_key, source.version) == (SOURCE_KEY, SOURCE_VERSION)
    # Release identity and retrieval time are separate facts and stay separate.
    assert source.released_at == RELEASED_AT
    assert source.retrieved_at == RETRIEVED_AT
    assert source.release_label == "fixture-release-1"
    assert source.supplies == SUPPLIES
    assert source.checksum_value == "0" * 64
    # A newly registered version cannot supply evidence until it is activated.
    assert source.state is ScientificResourceState.REGISTERED
    assert source.is_usable is False


async def test_a_source_must_declare_which_evidence_categories_it_supplies():
    harness = build_harness()
    admin_id = await platform_admin(harness)

    with pytest.raises(ValidationError):
        await RegisterEvidenceSource(harness.evidence).execute(
            RegisterSourceCommand(
                actor=await actor_for(harness, admin_id),
                request=harness.request,
                source_key="fixture-undeclared",
                version="1",
                display_name="Declares nothing",
                category=EvidenceSourceCategory.OTHER,
                supplies=(),
            )
        )


async def test_the_same_source_version_cannot_be_registered_twice():
    harness = build_harness()
    admin_id = await platform_admin(harness)
    await registered_source(harness, admin_id, activate=False)

    with pytest.raises(ConflictError):
        await registered_source(harness, admin_id, activate=False)


async def test_a_new_release_is_a_new_version_not_a_rewrite():
    harness = build_harness()
    admin_id = await platform_admin(harness)
    first = await registered_source(harness, admin_id)

    second = await registered_source(
        harness, admin_id, version="0.0.1-development-only"
    )

    assert second.id != first.id
    stored = await harness.repositories.evidence_sources.get(first.id)
    # The earlier release keeps its own identity, so evidence naming it stays
    # reproducible.
    assert stored.version == SOURCE_VERSION
    assert stored.released_at == RELEASED_AT


async def test_only_platform_administration_may_register_or_transition_a_source():
    harness = build_harness()
    admin_id = await platform_admin(harness)
    source = await registered_source(harness, admin_id, activate=False)
    ordinary_id = await create_account(harness, "member@example.org")
    ordinary = await actor_for(harness, ordinary_id)

    with pytest.raises(AuthorizationError):
        await RegisterEvidenceSource(harness.evidence).execute(
            RegisterSourceCommand(
                actor=ordinary,
                request=harness.request,
                source_key="fixture-sneaky",
                version="1",
                display_name="Not allowed",
                category=EvidenceSourceCategory.LITERATURE,
                supplies=(EvidenceCategory.LITERATURE,),
            )
        )
    with pytest.raises(AuthorizationError):
        await TransitionEvidenceSource(harness.evidence).execute(
            TransitionSourceCommand(
                actor=ordinary,
                request=harness.request,
                source_id=source.id,
                state=ScientificResourceState.ACTIVE,
            )
        )


async def test_lifecycle_moves_usability_and_a_retired_version_stays_retired():
    harness = build_harness()
    admin_id = await platform_admin(harness)
    source = await registered_source(harness, admin_id, activate=False)

    active = await activate_source(harness, admin_id, source.id)
    assert active.is_usable is True

    deprecated = await activate_source(
        harness, admin_id, source.id, state=ScientificResourceState.DEPRECATED
    )
    # Deprecated still reads and still supplies existing evidence; it is a signal,
    # not a removal.
    assert deprecated.is_usable is True

    retired = await activate_source(
        harness, admin_id, source.id, state=ScientificResourceState.RETIRED
    )
    assert retired.is_usable is False
    with pytest.raises(ConflictError):
        await activate_source(
            harness, admin_id, source.id, state=ScientificResourceState.ACTIVE
        )


async def test_reading_the_registry_requires_platform_evidence_read():
    harness = build_harness()
    admin_id = await platform_admin(harness)
    await registered_source(harness, admin_id)
    catalogue = EvidenceSourceCatalogue(harness.evidence)
    ordinary_id = await create_account(harness, "reader@example.org")

    listed = await catalogue.list(
        ListSourcesQuery(
            actor=await actor_for(harness, admin_id),
            request=harness.request,
            page=PAGE,
            usable_only=True,
        )
    )
    assert [item.source_key for item in listed.items] == [SOURCE_KEY]

    with pytest.raises(AuthorizationError):
        await catalogue.list(
            ListSourcesQuery(
                actor=await actor_for(harness, ordinary_id),
                request=harness.request,
                page=PAGE,
            )
        )
