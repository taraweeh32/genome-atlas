"""Registry, versioning, authorization, profile immutability, field projection.

These tests drive the real use cases against in-memory repositories, so the
platform rules — not a simplified restatement of them — decide every outcome.
"""

from __future__ import annotations

import pytest

from app.application.use_cases.annotation.profiles import (
    AnnotationProfileService,
    ProfileVersionInput,
)
from app.application.use_cases.annotation.resources import (
    AnnotationResourceCatalogue,
    ListResourcesQuery,
    TransitionAnnotationResource,
    TransitionResourceCommand,
)
from app.domain.errors import AuthorizationError, ConflictError
from app.domain.value_objects.enums import ScientificResourceState
from tests.annotation.support import (
    PAGE,
    RESOURCE_KEY,
    platform_admin,
    published_profile,
    registered_resource,
)
from tests.support.actors import actor_for, create_account
from tests.support.services import build_harness


async def test_registration_records_identity_version_and_declared_fields():
    harness = build_harness()
    admin_id = await platform_admin(harness)

    record = await registered_resource(harness, admin_id)

    assert (record.resource_key, record.version) == (RESOURCE_KEY, record.version)
    assert record.state is ScientificResourceState.REGISTERED
    assert {field.field_key for field in record.fields} == {
        "fixture_consequence",
        "fixture_score",
    }


async def test_re_registering_the_same_key_and_version_conflicts():
    harness = build_harness()
    admin_id = await platform_admin(harness)
    await registered_resource(harness, admin_id)

    with pytest.raises(ConflictError):
        await registered_resource(harness, admin_id)


async def test_a_new_version_of_the_same_resource_is_a_separate_record():
    harness = build_harness()
    admin_id = await platform_admin(harness)
    first = await registered_resource(harness, admin_id, version="1")
    second = await registered_resource(harness, admin_id, version="2")

    assert first.id != second.id
    assert first.resource_key == second.resource_key


async def test_ordinary_users_cannot_register_or_transition_resources():
    harness = build_harness()
    admin_id = await platform_admin(harness)
    member_id = await create_account(harness, "member@example.org")
    record = await registered_resource(harness, admin_id)

    with pytest.raises(AuthorizationError):
        await registered_resource(harness, member_id, version="9")
    with pytest.raises(AuthorizationError):
        await TransitionAnnotationResource(harness.annotation).execute(
            TransitionResourceCommand(
                actor=await actor_for(harness, member_id),
                request=harness.request,
                resource_id=record.id,
                state=ScientificResourceState.ACTIVE,
            )
        )


async def test_activation_and_retirement_move_usability():
    harness = build_harness()
    admin_id = await platform_admin(harness)
    record = await registered_resource(harness, admin_id)
    transition = TransitionAnnotationResource(harness.annotation)
    actor = await actor_for(harness, admin_id)

    active = await transition.execute(
        TransitionResourceCommand(
            actor=actor,
            request=harness.request,
            resource_id=record.id,
            state=ScientificResourceState.ACTIVE,
        )
    )
    assert active.is_usable

    retired = await transition.execute(
        TransitionResourceCommand(
            actor=actor,
            request=harness.request,
            resource_id=record.id,
            state=ScientificResourceState.RETIRED,
            reason="fixture retirement",
        )
    )
    assert not retired.is_usable


async def test_declared_fields_become_filterable_fields_for_package_seven():
    harness = build_harness()
    admin_id = await platform_admin(harness)
    record = await registered_resource(harness, admin_id)
    await TransitionAnnotationResource(harness.annotation).execute(
        TransitionResourceCommand(
            actor=await actor_for(harness, admin_id),
            request=harness.request,
            resource_id=record.id,
            state=ScientificResourceState.ACTIVE,
        )
    )

    fields = await AnnotationResourceCatalogue(harness.annotation).fields(
        await actor_for(harness, admin_id), harness.request
    )
    keys = {definition.id for definition in fields}
    assert any("fixture_consequence" in key for key in keys)

    # The dictionary the query subsystem reads is versioned, so an execution can
    # never claim a dictionary version it was not validated against.
    snapshot = await harness.field_dictionary.refresh(harness.unit_of_work)
    assert snapshot.version != harness.field_dictionary.base.version
    assert any("fixture_consequence" in key for key in (d.id for d in snapshot.definitions))


async def test_profile_pins_resource_versions_and_refuses_unusable_ones():
    harness = build_harness()
    admin_id = await platform_admin(harness)
    record = await registered_resource(harness, admin_id)

    # A registered-but-not-active version cannot be pinned: a run would otherwise
    # claim provenance the platform has not published.
    with pytest.raises(ConflictError):
        await published_profile(
            harness, admin_id, resource_ids=(record.id,), name="Unusable pin"
        )

    await TransitionAnnotationResource(harness.annotation).execute(
        TransitionResourceCommand(
            actor=await actor_for(harness, admin_id),
            request=harness.request,
            resource_id=record.id,
            state=ScientificResourceState.ACTIVE,
        )
    )
    _profile, view = await published_profile(
        harness, admin_id, resource_ids=(record.id,)
    )
    version = view.versions[0]
    assert version.resources[0].resource_version == record.version
    assert version.configuration_digest


async def test_a_referenced_profile_version_is_immutable_and_new_work_versions():
    harness = build_harness()
    admin_id = await platform_admin(harness)
    record = await registered_resource(harness, admin_id)
    await TransitionAnnotationResource(harness.annotation).execute(
        TransitionResourceCommand(
            actor=await actor_for(harness, admin_id),
            request=harness.request,
            resource_id=record.id,
            state=ScientificResourceState.ACTIVE,
        )
    )
    profile, view = await published_profile(
        harness, admin_id, resource_ids=(record.id,)
    )
    service = AnnotationProfileService(harness.annotation)
    actor = await actor_for(harness, admin_id)

    second = await service.add_version(
        actor,
        harness.request,
        profile.id,
        ProfileVersionInput(
            capability_id="integration.echo", resource_ids=(record.id,)
        ),
    )
    assert second.version_number == view.versions[0].version_number + 1

    stored = await harness.repositories.annotation_profiles.get_version(
        view.versions[0].id
    )
    assert stored.configuration_digest == view.versions[0].configuration_digest


async def test_catalogue_listing_requires_platform_read():
    harness = build_harness()
    admin_id = await platform_admin(harness)
    await registered_resource(harness, admin_id)

    listing = await AnnotationResourceCatalogue(harness.annotation).list(
        ListResourcesQuery(
            actor=await actor_for(harness, admin_id),
            request=harness.request,
            page=PAGE,
        )
    )
    assert listing.total >= 1
