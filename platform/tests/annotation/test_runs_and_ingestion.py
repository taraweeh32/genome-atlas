"""Runs, the scientific boundary, ingestion, provenance and tenant isolation."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.application.repositories import Page
from app.application.use_cases.annotation.ingestion import AnnotationResultReader
from app.application.use_cases.annotation.resources import (
    TransitionAnnotationResource,
    TransitionResourceCommand,
)
from app.application.use_cases.annotation.runs import AnnotationRunReader
from app.domain.errors import AuthorizationError, ValidationError
from app.domain.value_objects.enums import (
    AnnotationRunState,
    DataOrigin,
    JobKind,
    ScientificResourceState,
    ValueSemantics,
)
from app.scientific.annotation import AnnotationRecordClaim
from app.workers.annotation_handlers import AnnotationJobHandlers
from tests.annotation.support import (
    PAGE,
    annotation_payload,
    ingest,
    platform_admin,
    published_profile,
    registered_resource,
    requested_run,
    value,
)
from tests.results.support import (
    ENGINE,
    ENGINE_VERSION,
    GENOME as GENOME_RESOURCE,
    execution_for,
    ingest_variants,
    normalized_claim,
)
from tests.support.actors import actor_for, create_account
from tests.support.services import build_harness


async def arrange(harness=None):
    """An active resource, a published profile, a readable surface and a variant."""
    harness = harness or build_harness()
    admin_id = await platform_admin(harness)
    resource = await registered_resource(harness, admin_id)
    await TransitionAnnotationResource(harness.annotation).execute(
        TransitionResourceCommand(
            actor=await actor_for(harness, admin_id),
            request=harness.request,
            resource_id=resource.id,
            state=ScientificResourceState.ACTIVE,
        )
    )
    profile, _ = await published_profile(
        harness, admin_id, resource_ids=(resource.id,)
    )

    from tests.results.support import available_result

    _, execution, dataset_version_id = await execution_for(harness, admin_id)
    result_view = await available_result(harness, admin_id, execution.id)
    await ingest_variants(
        harness,
        admin_id,
        analysis_execution_id=execution.id,
        dataset_version_id=dataset_version_id,
        variants=(normalized_claim(),),
    )
    variants = await harness.repositories.variants.list_for_dataset_version(
        dataset_version_id, page=PAGE
    )
    return harness, admin_id, profile, result_view.result_set, variants.items[0]


async def test_requesting_a_run_freezes_the_profile_and_queues_one_durable_job():
    harness, admin_id, profile, result_set, _ = await arrange()

    view = await requested_run(
        harness, admin_id, profile_id=profile.id, result_set_id=result_set.id
    )

    assert view.run.state is AnnotationRunState.REQUESTED
    assert view.run.configuration_digest
    assert view.run.configuration_snapshot["resources"]
    assert view.run.workspace_id == result_set.workspace_id

    queued = [
        job
        for job in harness.repositories.jobs.jobs.values()
        if job.kind is JobKind.ANNOTATION_EXECUTION
    ]
    assert len(queued) == 1


async def test_requesting_twice_with_the_same_key_is_idempotent():
    harness, admin_id, profile, result_set, _ = await arrange()

    first = await requested_run(
        harness,
        admin_id,
        profile_id=profile.id,
        result_set_id=result_set.id,
        idempotency_key="delivery-a",
    )
    second = await requested_run(
        harness,
        admin_id,
        profile_id=profile.id,
        result_set_id=result_set.id,
        idempotency_key="delivery-a",
    )

    assert first.run.id == second.run.id


class RecordingGateway:
    """Records what crossed the boundary; the real adapter still answers."""

    def __init__(self, inner):
        self._inner = inner
        self.requests = []

    async def submit_execution(self, request):
        self.requests.append(request)
        return await self._inner.submit_execution(request)

    def __getattr__(self, name):
        return getattr(self._inner, name)


async def test_a_run_goes_to_the_scientific_subsystem_only_through_the_gateway():
    harness, admin_id, profile, result_set, _ = await arrange()
    view = await requested_run(
        harness, admin_id, profile_id=profile.id, result_set_id=result_set.id
    )
    gateway = RecordingGateway(harness.scientific)
    services = replace(harness.annotation, scientific=gateway)

    submitted = await AnnotationJobHandlers(services).handle(
        JobKind.ANNOTATION_EXECUTION,
        {"annotation_run_id": view.run.id},
        correlation_id="test-correlation",
    )

    assert submitted is not None
    sent = gateway.requests[-1]
    # Identities and parameters only: never a command the node would execute.
    assert sent.capability_id
    assert sent.parameters["annotation_run_id"] == view.run.id
    assert sent.parameters["annotation_resources"]
    assert "command" not in sent.parameters


async def test_ingestion_stores_declared_values_with_their_resource_identity():
    harness, admin_id, profile, result_set, variant = await arrange()
    view = await requested_run(
        harness, admin_id, profile_id=profile.id, result_set_id=result_set.id
    )

    result = await ingest(
        harness,
        annotation_payload(
            annotation_run_id=view.run.id,
            variant_id=variant.id,
            values=(
                value("fixture_consequence", string="fixture_term"),
                value("fixture_score", number=0.5),
            ),
        ),
    )

    # One stored annotation row per declared field value.
    assert result.stored_record_count == 2
    assert result.result.version_number == 1
    rows = await harness.repositories.variant_contexts.list_annotations(
        variant.id, page=PAGE
    )
    stored = {row.field_key: row for row in rows.items}
    assert stored["fixture_consequence"].value.value_string == "fixture_term"
    assert stored["fixture_score"].value.value_number == 0.5
    # Identity always travels with its version.
    assert stored["fixture_score"].resource_version == view.run.configuration_snapshot[
        "resources"
    ][0]["resource_version"]


async def test_absence_is_preserved_rather_than_coerced():
    harness, admin_id, profile, result_set, variant = await arrange()
    view = await requested_run(
        harness, admin_id, profile_id=profile.id, result_set_id=result_set.id
    )

    await ingest(
        harness,
        annotation_payload(
            annotation_run_id=view.run.id,
            variant_id=variant.id,
            values=(
                value(
                    "fixture_score", number=None, semantics=ValueSemantics.NOT_REPORTED
                    if hasattr(ValueSemantics, "NOT_REPORTED")
                    else ValueSemantics.MISSING,
                ),
            ),
        ),
    )

    rows = await harness.repositories.variant_contexts.list_annotations(
        variant.id, page=PAGE
    )
    row = next(row for row in rows.items if row.field_key == "fixture_score")
    assert row.value.value_number is None
    assert row.value.semantics is not ValueSemantics.PRESENT
    assert row.origin is DataOrigin.RETRIEVED


async def test_a_field_the_resource_never_declared_is_rejected_not_repaired():
    harness, admin_id, profile, result_set, variant = await arrange()
    view = await requested_run(
        harness, admin_id, profile_id=profile.id, result_set_id=result_set.id
    )

    result = await ingest(
        harness,
        annotation_payload(
            annotation_run_id=view.run.id,
            variant_id=variant.id,
            values=(value("undeclared_field", string="x"),),
        ),
    )

    assert result.stored_record_count == 0
    assert result.rejected_record_count == 1
    assert result.findings


async def test_an_unlinkable_variant_is_recorded_as_a_finding():
    harness, admin_id, profile, result_set, _ = await arrange()
    view = await requested_run(
        harness, admin_id, profile_id=profile.id, result_set_id=result_set.id
    )

    result = await ingest(
        harness,
        annotation_payload(
            annotation_run_id=view.run.id, variant_id="var_does_not_exist"
        ),
    )

    assert result.stored_record_count == 0
    assert any("variant" in finding["code"] for finding in result.findings)


async def test_a_mismatched_reference_context_blocks_the_whole_payload():
    harness, admin_id, profile, result_set, variant = await arrange()
    view = await requested_run(
        harness, admin_id, profile_id=profile.id, result_set_id=result_set.id
    )

    with pytest.raises(ValidationError):
        await ingest(
            harness,
            annotation_payload(
                annotation_run_id=view.run.id,
                variant_id=variant.id,
                genome_assembly="GRCh37",
            ),
        )


async def test_a_mismatched_resource_version_blocks_the_whole_payload():
    harness, admin_id, profile, result_set, variant = await arrange()
    view = await requested_run(
        harness, admin_id, profile_id=profile.id, result_set_id=result_set.id
    )

    # A second registered version exists, but the run pinned the first one.
    other = await registered_resource(harness, admin_id, version="0.0.1-development-only")
    assert other.version == "0.0.1-development-only"

    with pytest.raises(ValidationError):
        await ingest(
            harness,
            annotation_payload(
                annotation_run_id=view.run.id,
                variant_id=variant.id,
                resource_version=other.version,
            ),
        )


async def test_a_redelivered_payload_returns_the_original_result_version():
    harness, admin_id, profile, result_set, variant = await arrange()
    view = await requested_run(
        harness, admin_id, profile_id=profile.id, result_set_id=result_set.id
    )
    payload = annotation_payload(
        annotation_run_id=view.run.id, variant_id=variant.id
    )

    first = await ingest(harness, payload)
    second = await ingest(harness, payload)

    assert first.result.id == second.result.id
    assert second.result.version_number == 1


async def test_duplicate_claims_within_one_payload_are_not_stored_twice():
    harness, admin_id, profile, result_set, variant = await arrange()
    view = await requested_run(
        harness, admin_id, profile_id=profile.id, result_set_id=result_set.id
    )

    result = await ingest(
        harness,
        annotation_payload(
            annotation_run_id=view.run.id,
            variant_id=variant.id,
            records=(
                AnnotationRecordClaim(
                    variant_id=variant.id,
                    values=(value("fixture_consequence", string="a"),),
                ),
                AnnotationRecordClaim(
                    variant_id=variant.id,
                    values=(value("fixture_consequence", string="a"),),
                ),
            ),
        ),
    )

    rows = await harness.repositories.variant_contexts.list_annotations(
        variant.id, page=PAGE
    )
    assert len([row for row in rows.items if row.field_key == "fixture_consequence"]) == 1
    assert result.stored_record_count == 1


async def test_a_result_version_carries_full_provenance():
    harness, admin_id, profile, result_set, variant = await arrange()
    view = await requested_run(
        harness, admin_id, profile_id=profile.id, result_set_id=result_set.id
    )

    result = await ingest(
        harness,
        annotation_payload(annotation_run_id=view.run.id, variant_id=variant.id),
    )
    stored = result.result

    assert stored.annotation_run_id == view.run.id
    assert stored.result_set_id == result_set.id
    assert stored.profile_version_id == view.run.profile_version_id
    assert stored.parameters_digest == view.run.configuration_digest
    assert stored.resource_version
    assert stored.genome_assembly
    assert stored.payload_digest
    assert stored.created_at is not None


async def test_another_tenant_cannot_read_a_run_or_its_results():
    harness, admin_id, profile, result_set, variant = await arrange()
    view = await requested_run(
        harness, admin_id, profile_id=profile.id, result_set_id=result_set.id
    )
    result = await ingest(
        harness,
        annotation_payload(annotation_run_id=view.run.id, variant_id=variant.id),
    )
    outsider = await create_account(harness, "outsider@example.org")
    actor = await actor_for(harness, outsider)

    with pytest.raises(AuthorizationError):
        await AnnotationRunReader(harness.annotation).get(
            actor, harness.request, view.run.id
        )
    with pytest.raises(AuthorizationError):
        await AnnotationResultReader(harness.annotation).get(
            actor, harness.request, result.result.id
        )


async def test_results_are_listed_per_surface_without_inlining_annotation_rows():
    harness, admin_id, profile, result_set, variant = await arrange()
    view = await requested_run(
        harness, admin_id, profile_id=profile.id, result_set_id=result_set.id
    )
    await ingest(
        harness,
        annotation_payload(annotation_run_id=view.run.id, variant_id=variant.id),
    )

    listing = await AnnotationResultReader(harness.annotation).list_for_surface(
        await actor_for(harness, admin_id),
        harness.request,
        result_set_id=result_set.id,
        page=Page(number=1, size=10),
    )

    assert listing.total == 1
    assert not hasattr(listing.items[0], "records")


async def test_cancelling_a_run_is_terminal():
    harness, admin_id, profile, result_set, _ = await arrange()
    view = await requested_run(
        harness, admin_id, profile_id=profile.id, result_set_id=result_set.id
    )

    cancelled = await AnnotationRunReader(harness.annotation).cancel(
        await actor_for(harness, admin_id), harness.request, view.run.id
    )

    assert cancelled.state is AnnotationRunState.CANCELLED
    assert cancelled.is_terminal
