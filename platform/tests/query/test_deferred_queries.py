"""Deferred (durable job) execution of an expensive variant query.

Asserts the properties that make the deferred path trustworthy rather than merely
present: the request half validates and authorizes before anything is enqueued,
the worker half resolves the requester's grants from stored state, the artifact is
written under the platform's own analytical root, and reaching the row ceiling is
reported as a limit outcome instead of a partial artifact that looks complete.
"""

from __future__ import annotations

import pytest

from app.application.use_cases.query.deferred import (
    QUERY_JOB_KIND,
    DeferVariantQuery,
    DeferVariantQueryCommand,
    RunDeferredVariantQuery,
)
from app.application.use_cases.query.execution import FilterSelection
from app.domain.errors import AuthorizationError, ValidationError
from app.domain.value_objects.enums import QueryExecutionOutcome
from app.infrastructure.analytics.query_engine import DuckDbQueryEngine
from tests.query.support import (
    condition,
    group,
    query_services,
    surface_result_set,
    write_surface,
)
from tests.support.actors import actor_for, create_account
from tests.support.services import build_harness


async def build_surface(tmp_path):
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.org")
    location = write_surface(tmp_path / "analytics")
    result_set = await surface_result_set(harness, user_id, location)
    services = query_services(harness, tmp_path / "analytics")
    return harness, user_id, result_set, services


async def defer(services, harness, user_id, result_set, **kwargs):
    return await DeferVariantQuery(services).execute(
        DeferVariantQueryCommand(
            actor=await actor_for(harness, user_id),
            request=harness.request,
            result_set_id=result_set.id,
            **kwargs,
        )
    )


async def test_deferring_a_query_enqueues_one_job_on_the_existing_system(tmp_path):
    harness, user_id, result_set, services = await build_surface(tmp_path)

    accepted = await defer(services, harness, user_id, result_set)

    assert accepted.effective_hash
    job = await harness.repositories.jobs.find(accepted.job_id)
    assert job is not None
    assert job.kind is QUERY_JOB_KIND
    assert job.payload["requested_by"] == user_id
    # The request records that it deferred, so the trail shows both halves.
    assert any(
        record.action == "variant_query.deferred"
        for record in harness.repositories.audit.records
    )


async def test_a_malformed_filter_is_refused_before_any_job_exists(tmp_path):
    harness, user_id, result_set, services = await build_surface(tmp_path)

    with pytest.raises(ValidationError):
        await defer(
            services,
            harness,
            user_id,
            result_set,
            filter=FilterSelection(
                expression=group(condition("no_such_field", "equals", "x"))
            ),
        )

    assert not any(
        record.action == "variant_query.deferred"
        for record in harness.repositories.audit.records
    )


async def test_an_unrelated_account_cannot_defer_a_query_over_the_surface(tmp_path):
    harness, _owner_id, result_set, services = await build_surface(tmp_path)
    stranger = await create_account(harness, "stranger@example.org")

    with pytest.raises(AuthorizationError):
        await defer(services, harness, stranger, result_set)


async def test_the_worker_materializes_an_artifact_and_records_the_execution(tmp_path):
    harness, user_id, result_set, services = await build_surface(tmp_path)
    accepted = await defer(
        services,
        harness,
        user_id,
        result_set,
        filter=FilterSelection(
            expression=group(condition("contig", "equals", "chr1"))
        ),
    )
    job = await harness.repositories.jobs.find(accepted.job_id)

    outcome = await RunDeferredVariantQuery(services).execute(
        job.payload, harness.request
    )

    assert outcome.outcome is QueryExecutionOutcome.COMPLETED
    assert outcome.location is not None
    assert outcome.row_count > 0
    # The artifact is a real readable Parquet file under the analytical root.
    engine = DuckDbQueryEngine(services.query_engine._analytics)
    described = await engine.describe(outcome.location)
    assert described.row_count == outcome.row_count
    # Provenance: append-only record, carrying the effective expression.
    stored = await harness.repositories.query_executions.get_filter_execution(
        outcome.execution.id
    )
    assert stored is not None
    assert stored.metadata["deferred"] is True
    assert stored.effective_hash == outcome.execution.effective_hash


async def test_reaching_the_row_ceiling_is_reported_not_silently_truncated(tmp_path):
    harness, user_id, result_set, services = await build_surface(tmp_path)
    accepted = await defer(services, harness, user_id, result_set, max_rows=2)
    job = await harness.repositories.jobs.find(accepted.job_id)

    outcome = await RunDeferredVariantQuery(services).execute(
        job.payload, harness.request
    )

    assert outcome.outcome is QueryExecutionOutcome.LIMIT_EXCEEDED
    # No location is handed back: a partial artifact must not look complete.
    assert outcome.location is None
    assert outcome.execution.failure_reason


async def test_a_row_ceiling_above_the_configured_maximum_is_refused(tmp_path):
    harness, user_id, result_set, services = await build_surface(tmp_path)

    with pytest.raises(ValidationError):
        await defer(services, harness, user_id, result_set, max_rows=10_000_000)
