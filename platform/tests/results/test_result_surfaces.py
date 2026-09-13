"""Result-surface behaviour: delivery, verification, readability and withdrawal.

The distinctions under test are the ones the platform must not blur:

* a *delivered* surface is not a *readable* one — verification stands between them;
* content immutability and presentability are different properties;
* possessing a result-set identifier grants nothing.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.application.use_cases.results.ingestion import (
    FAILURE_CHECKSUM,
    FAILURE_MISSING,
    FAILURE_UNREADABLE,
    INGESTION_JOB_KIND,
    MaterializeResultSet,
    MaterializeResultSetCommand,
    SubmitResultPayload,
    SubmitResultPayloadCommand,
)
from app.application.use_cases.results.reads import (
    AuthorizeArtifactDownload,
    AuthorizeArtifactDownloadCommand,
    GetResultSet,
    GetResultSetQuery,
    InvalidateResultSet,
    InvalidateResultSetCommand,
    ListResultSets,
    ListResultSetsQuery,
    ReadResultPage,
    ReadResultPageQuery,
    SupersedeResultSet,
    SupersedeResultSetCommand,
)
from app.domain.errors import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.domain.value_objects.enums import (
    PlatformRole,
    ResultArtifactState,
    ResultCompleteness,
    ResultIngestionState,
    ResultSetState,
)
from app.scientific.results import ClaimAttribution, ResultArtifactClaim
from tests.results.support import (
    PAGE,
    TABLE,
    available_result,
    execution_for,
    result_payload,
    submitted_result,
)
from tests.support.actors import actor_for, create_account, grant_platform_role
from tests.support.services import build_harness


@pytest.fixture
def harness():
    return build_harness()


async def _owner(harness) -> str:
    return await create_account(harness, "owner@example.test", "Owner")


async def test_delivery_registers_a_validated_surface_and_queues_materialization(harness):
    owner = await _owner(harness)
    _, execution, _ = await execution_for(harness, owner)

    view = await submitted_result(harness, owner, execution.id)

    # Validated, not available: nothing has been verified yet.
    assert view.result_set.state is ResultSetState.VALIDATED
    assert view.result_set.is_readable is False
    assert view.ingestion.state is ResultIngestionState.MATERIALIZING
    assert view.result_set.completeness is ResultCompleteness.COMPLETE
    # Scope came from the execution row, never from the payload.
    assert view.result_set.workspace_id == execution.workspace_id
    assert view.result_set.project_id == execution.project_id
    assert view.artifacts[0].state is ResultArtifactState.REGISTERED

    jobs = await harness.repositories.jobs.list_all(page=PAGE)
    ingestion_jobs = [job for job in jobs.items if job.kind is INGESTION_JOB_KIND]
    assert len(ingestion_jobs) == 1
    assert ingestion_jobs[0].payload["result_set_id"] == view.result_set.id


async def test_a_redelivered_payload_does_not_register_a_second_surface(harness):
    owner = await _owner(harness)
    _, execution, _ = await execution_for(harness, owner)

    first = await submitted_result(harness, owner, execution.id)
    second = await submitted_result(harness, owner, execution.id)

    assert second.result_set.id == first.result_set.id
    assert second.ingestion.id == first.ingestion.id
    sets = await harness.repositories.result_sets.list_all(page=PAGE)
    assert len(sets.items) == 1


async def test_verification_makes_the_surface_readable_and_prefers_stored_facts(harness):
    owner = await _owner(harness)
    _, execution, _ = await execution_for(harness, owner)
    # The engine declared 1 row; the stored surface actually holds 1. The stored
    # fact is what the platform records.
    view = await available_result(harness, owner, execution.id)

    assert view.result_set.state is ResultSetState.AVAILABLE
    assert view.result_set.is_readable is True
    assert view.result_set.available_at == harness.clock.now()
    assert view.result_set.row_count == 1
    assert view.result_set.column_schema == {"variant_id": "VARCHAR", "score": "VARCHAR"}
    assert view.artifacts[0].state is ResultArtifactState.ACCEPTED
    assert view.artifacts[0].verified_at == harness.clock.now()
    assert view.ingestion.state is ResultIngestionState.ACCEPTED


async def test_a_checksum_mismatch_fails_the_surface_instead_of_publishing_it(harness):
    owner = await _owner(harness)
    _, execution, _ = await execution_for(harness, owner)
    # Storage holds different bytes than the producer declared a checksum for.
    view = await submitted_result(
        harness, owner, execution.id, stored_table=b"variant_id,score\nv1,999\n"
    )

    materialized = await MaterializeResultSet(harness.results).execute(
        MaterializeResultSetCommand(
            result_ingestion_id=view.ingestion.id, request=harness.request
        )
    )

    assert materialized.result_set.state is ResultSetState.FAILED
    assert materialized.result_set.failure_code == FAILURE_CHECKSUM
    assert materialized.result_set.is_readable is False
    assert materialized.artifacts[0].state is ResultArtifactState.REJECTED
    assert materialized.ingestion.state is ResultIngestionState.FAILED


async def test_absent_artifact_bytes_are_recorded_as_missing_not_ignored(harness):
    owner = await _owner(harness)
    _, execution, _ = await execution_for(harness, owner)
    view = await submitted_result(harness, owner, execution.id, stored_table=None)

    materialized = await MaterializeResultSet(harness.results).execute(
        MaterializeResultSetCommand(
            result_ingestion_id=view.ingestion.id, request=harness.request
        )
    )

    assert materialized.result_set.failure_code == FAILURE_MISSING
    assert materialized.artifacts[0].state is ResultArtifactState.MISSING


async def test_an_unreadable_analytical_surface_fails_the_result(harness):
    owner = await _owner(harness)
    _, execution, _ = await execution_for(harness, owner)
    view = await submitted_result(
        harness, owner, execution.id, register_surface=False
    )

    materialized = await MaterializeResultSet(harness.results).execute(
        MaterializeResultSetCommand(
            result_ingestion_id=view.ingestion.id, request=harness.request
        )
    )

    assert materialized.result_set.state is ResultSetState.FAILED
    assert materialized.result_set.failure_code == FAILURE_UNREADABLE


async def test_materialization_is_idempotent_when_the_job_is_redelivered(harness):
    owner = await _owner(harness)
    _, execution, _ = await execution_for(harness, owner)
    first = await available_result(harness, owner, execution.id)

    again = await MaterializeResultSet(harness.results).execute(
        MaterializeResultSetCommand(
            result_ingestion_id=first.ingestion.id, request=harness.request
        )
    )

    assert again.result_set.state is ResultSetState.AVAILABLE
    assert again.result_set.available_at == first.result_set.available_at


async def test_an_unattributed_payload_is_refused_and_the_refusal_is_recorded(harness):
    owner = await _owner(harness)
    _, execution, _ = await execution_for(harness, owner)
    payload = result_payload(analysis_execution_id=execution.id)
    anonymous = ClaimAttribution(origin="generated")
    payload = replace(payload, attribution=anonymous)

    with pytest.raises(ValidationError):
        await SubmitResultPayload(harness.results).execute(
            SubmitResultPayloadCommand(
                payload=payload,
                request=harness.request,
                idempotency_key="anonymous-1",
                payload_digest="digest",
                actor=await actor_for(harness, owner),
            )
        )

    ingestions = tuple(harness.repositories.result_ingestions.rows.values())
    assert [item.state for item in ingestions] == [ResultIngestionState.REJECTED]
    assert ingestions[0].rejection_code is not None
    # A refused delivery never produced a surface.
    sets = await harness.repositories.result_sets.list_all(page=PAGE)
    assert sets.items == []


async def test_an_unsupported_contract_version_is_refused(harness):
    owner = await _owner(harness)
    _, execution, _ = await execution_for(harness, owner)
    payload = result_payload(analysis_execution_id=execution.id)
    payload = replace(payload, contract_version="999")

    with pytest.raises(ValidationError):
        await SubmitResultPayload(harness.results).execute(
            SubmitResultPayloadCommand(
                payload=payload,
                request=harness.request,
                idempotency_key="future-contract",
                payload_digest="digest",
                actor=await actor_for(harness, owner),
            )
        )


async def test_content_is_readable_only_once_the_surface_is(harness):
    owner = await _owner(harness)
    _, execution, _ = await execution_for(harness, owner)
    submitted = await submitted_result(harness, owner, execution.id)
    actor = await actor_for(harness, owner)

    with pytest.raises(ConflictError):
        await ReadResultPage(harness.results).execute(
            ReadResultPageQuery(
                actor=actor,
                result_set_id=submitted.result_set.id,
                request=harness.request,
            )
        )

    await MaterializeResultSet(harness.results).execute(
        MaterializeResultSetCommand(
            result_ingestion_id=submitted.ingestion.id, request=harness.request
        )
    )
    content = await ReadResultPage(harness.results).execute(
        ReadResultPageQuery(
            actor=actor, result_set_id=submitted.result_set.id, request=harness.request
        )
    )

    assert content.page.columns == ("variant_id", "score")
    assert content.page.rows == (("v1", 1),)
    assert content.is_development_payload is True


async def test_reading_is_bounded_regardless_of_the_requested_window(harness):
    owner = await _owner(harness)
    _, execution, _ = await execution_for(harness, owner)
    view = await available_result(harness, owner, execution.id)

    await ReadResultPage(harness.results).execute(
        ReadResultPageQuery(
            actor=await actor_for(harness, owner),
            result_set_id=view.result_set.id,
            request=harness.request,
            offset=0,
            limit=10_000,
        )
    )

    _, _, limit = harness.analytics.reads[-1]
    assert limit <= 500


async def test_another_tenant_cannot_reach_a_surface_by_knowing_its_identifier(harness):
    owner = await _owner(harness)
    _, execution, _ = await execution_for(harness, owner)
    view = await available_result(harness, owner, execution.id)
    stranger = await create_account(harness, "stranger@example.test", "Stranger")
    stranger_actor = await actor_for(harness, stranger)

    for call in (
        GetResultSet(harness.results).execute(
            GetResultSetQuery(
                actor=stranger_actor,
                result_set_id=view.result_set.id,
                request=harness.request,
            )
        ),
        ReadResultPage(harness.results).execute(
            ReadResultPageQuery(
                actor=stranger_actor,
                result_set_id=view.result_set.id,
                request=harness.request,
            )
        ),
        AuthorizeArtifactDownload(harness.results).execute(
            AuthorizeArtifactDownloadCommand(
                actor=stranger_actor,
                artifact_id=view.artifacts[0].id,
                request=harness.request,
            )
        ),
    ):
        with pytest.raises((AuthorizationError, NotFoundError)):
            await call


async def test_listing_a_workspace_never_returns_another_tenants_surfaces(harness):
    owner = await _owner(harness)
    _, execution, _ = await execution_for(harness, owner)
    await available_result(harness, owner, execution.id)
    stranger = await create_account(harness, "other@example.test", "Other")

    with pytest.raises((AuthorizationError, NotFoundError)):
        await ListResultSets(harness.results).execute(
            ListResultSetsQuery(
                actor=await actor_for(harness, stranger),
                request=harness.request,
                page=PAGE,
                workspace_id=execution.workspace_id,
            )
        )


async def test_a_download_grant_is_issued_only_for_a_verified_artifact(harness):
    owner = await _owner(harness)
    _, execution, _ = await execution_for(harness, owner)
    submitted = await submitted_result(harness, owner, execution.id)
    actor = await actor_for(harness, owner)

    with pytest.raises(ConflictError):
        await AuthorizeArtifactDownload(harness.results).execute(
            AuthorizeArtifactDownloadCommand(
                actor=actor,
                artifact_id=submitted.artifacts[0].id,
                request=harness.request,
            )
        )

    await MaterializeResultSet(harness.results).execute(
        MaterializeResultSetCommand(
            result_ingestion_id=submitted.ingestion.id, request=harness.request
        )
    )
    grant = await AuthorizeArtifactDownload(harness.results).execute(
        AuthorizeArtifactDownloadCommand(
            actor=actor, artifact_id=submitted.artifacts[0].id, request=harness.request
        )
    )

    assert grant.url.startswith("https://storage.invalid/")
    assert grant.expires_in_seconds > 0
    assert any(
        entry.action == "result_artifact.download_authorized"
        for entry in harness.repositories.audit.records
    )


async def test_invalidation_withdraws_a_surface_without_touching_its_content(harness):
    owner = await _owner(harness)
    _, execution, _ = await execution_for(harness, owner)
    view = await available_result(harness, owner, execution.id)
    admin = await create_account(harness, "admin@example.test", "Admin")
    await grant_platform_role(harness, admin, PlatformRole.PLATFORM_ADMINISTRATOR)

    invalidated = await InvalidateResultSet(harness.results).execute(
        InvalidateResultSetCommand(
            actor=await actor_for(harness, admin),
            result_set_id=view.result_set.id,
            reason="the input dataset version was withdrawn",
            request=harness.request,
        )
    )

    assert invalidated.result_set.state is ResultSetState.INVALIDATED
    assert invalidated.result_set.is_readable is False
    assert invalidated.result_set.invalidation_reason
    # The produced facts are untouched: only presentability changed.
    assert invalidated.result_set.analytical_location == (
        view.result_set.analytical_location
    )
    assert invalidated.result_set.row_count == view.result_set.row_count
    assert (
        invalidated.result_set.provenance.engine_version
        == view.result_set.provenance.engine_version
    )
    assert harness.storage.deleted == []


async def test_invalidation_is_not_a_tenant_capability(harness):
    owner = await _owner(harness)
    _, execution, _ = await execution_for(harness, owner)
    view = await available_result(harness, owner, execution.id)

    with pytest.raises(AuthorizationError):
        await InvalidateResultSet(harness.results).execute(
            InvalidateResultSetCommand(
                actor=await actor_for(harness, owner),
                result_set_id=view.result_set.id,
                reason="I would rather it were gone",
                request=harness.request,
            )
        )


async def test_invalidation_requires_a_recorded_reason(harness):
    owner = await _owner(harness)
    _, execution, _ = await execution_for(harness, owner)
    view = await available_result(harness, owner, execution.id)
    admin = await create_account(harness, "admin2@example.test", "Admin")
    await grant_platform_role(harness, admin, PlatformRole.PLATFORM_ADMINISTRATOR)

    with pytest.raises(ValidationError):
        await InvalidateResultSet(harness.results).execute(
            InvalidateResultSetCommand(
                actor=await actor_for(harness, admin),
                result_set_id=view.result_set.id,
                reason="   ",
                request=harness.request,
            )
        )


async def test_supersession_records_the_replacement_and_keeps_history_readable(harness):
    owner = await _owner(harness)
    _, execution, _ = await execution_for(harness, owner)
    first = await available_result(harness, owner, execution.id)
    second = await available_result(
        harness,
        owner,
        execution.id,
        payload=result_payload(
            analysis_execution_id=execution.id,
            result_key="primary",
            analytical_location="s3://test-bucket/results/primary-v2.parquet",
            artifacts=(
                ResultArtifactClaim(
                    artifact_key="variants.csv",
                    kind="variant_table",
                    artifact_format="csv",
                    storage_uri="results/primary-v2/variants.csv",
                    size_bytes=len(TABLE),
                ),
            ),
        ),
        idempotency_key="delivery-2",
    )

    superseded = await SupersedeResultSet(harness.results).execute(
        SupersedeResultSetCommand(
            actor=await actor_for(harness, owner),
            result_set_id=first.result_set.id,
            superseded_by_result_set_id=second.result_set.id,
            request=harness.request,
        )
    )

    assert superseded.result_set.state is ResultSetState.SUPERSEDED
    assert superseded.result_set.superseded_by_result_set_id == second.result_set.id
    # A superseded surface is history, not garbage: it stays readable.
    assert superseded.result_set.is_readable is True
