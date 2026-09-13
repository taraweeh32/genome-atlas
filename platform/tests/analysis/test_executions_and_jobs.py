"""Executions, the durable job, the worker runtime and the scientific boundary.

These tests exercise the real path: request → queued execution + job → claim →
lease → dispatch → development scientific adapter → provenance → completion.
The adapter performs no analysis; what is asserted here is orchestration,
authorization and recorded provenance, never scientific validity.
"""

from __future__ import annotations

import asyncio

import pytest

from app.application.use_cases.analysis.execution_runner import (
    RunAnalysisExecution,
    RunExecutionCommand,
)
from app.application.use_cases.analysis.executions import (
    CancelExecution,
    CancelExecutionCommand,
    GetExecution,
    GetExecutionProvenance,
    GetExecutionProvenanceQuery,
    GetExecutionQuery,
    ListExecutions,
    ListExecutionsQuery,
    RequestExecution,
    RequestExecutionCommand,
)
from app.application.use_cases.analysis.jobs import (
    CancelJob,
    CancelJobCommand,
    GetJob,
    GetJobQuery,
    GetQueueStatistics,
    GetQueueStatisticsQuery,
    ListJobs,
    ListJobsQuery,
    ListPlatformJobs,
    ListPlatformJobsQuery,
)
from app.application.use_cases.analysis.nodes import (
    ChangeNodeLifecycle,
    ChangeNodeLifecycleCommand,
    ListNodes,
    ListNodesQuery,
)
from app.domain.analysis.policies import LeasePolicy, RetryPolicy
from app.domain.errors import AuthorizationError, NotFoundError, ValidationError
from app.domain.value_objects.enums import (
    ExecutionState,
    JobKind,
    JobState,
    NodeLifecycleState,
    PlatformRole,
    ScientificExecutionState,
)
from app.workers.runtime import JobRuntime, WorkerIdentity
from tests.analysis.support import (
    PAGE,
    configured_analysis,
    project_analysis,
    queued_execution,
    register_scientific_node,
)
from tests.support.actors import actor_for, create_account, grant_platform_role
from tests.support.services import build_harness

pytestmark = pytest.mark.anyio


async def _runtime(harness, dispatch, *, kinds=(), lease=None) -> JobRuntime:
    return JobRuntime(
        unit_of_work=harness.unit_of_work,
        clock=harness.clock,
        dispatch=dispatch,
        identity=WorkerIdentity(worker_id="worker-1", kinds=tuple(kinds)),
        retry=RetryPolicy(),
        lease=lease or LeasePolicy(),
    )


async def test_requesting_an_execution_queues_a_job_in_the_same_transaction() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    _, configuration, execution = await queued_execution(harness, user_id)

    assert execution.execution.state is ExecutionState.QUEUED
    assert execution.execution.analysis_configuration_id == configuration.configuration.id
    # The frozen snapshot, not a live pointer.
    assert execution.execution.configuration_snapshot
    job = await harness.repositories.jobs.find(execution.execution.scheduled_job_id)
    assert job is not None
    assert job.kind is JobKind.ANALYSIS_EXECUTION
    assert job.state is JobState.QUEUED
    # The execution's inputs are the exact dataset versions the configuration declared.
    inputs = await harness.repositories.analysis_executions.list_inputs(execution.execution.id)
    assert [item.role for item in inputs] == ["primary"]


async def test_execution_requires_a_ready_analysis() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    analysis = await project_analysis(harness, user_id)

    with pytest.raises(ValidationError):
        await RequestExecution(harness.analysis).execute(
            RequestExecutionCommand(
                actor=await actor_for(harness, user_id),
                analysis_id=analysis.analysis.id,
                request=harness.request,
            )
        )


async def test_repeated_request_with_the_same_idempotency_key_returns_one_execution() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    analysis, _ = await configured_analysis(harness, user_id)

    command = RequestExecutionCommand(
        actor=await actor_for(harness, user_id),
        analysis_id=analysis.analysis.id,
        request=harness.request,
        idempotency_key="operator-retry-1",
    )
    first = await RequestExecution(harness.analysis).execute(command)
    second = await RequestExecution(harness.analysis).execute(command)

    assert first.execution.id == second.execution.id
    listing = await ListExecutions(harness.analysis).execute(
        ListExecutionsQuery(
            actor=await actor_for(harness, user_id), page=PAGE, request=harness.request
        )
    )
    assert listing.total == 1


async def test_worker_runs_the_execution_through_the_scientific_boundary() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    await register_scientific_node(harness)
    _, _, execution = await queued_execution(harness, user_id)

    runner = RunAnalysisExecution(harness.analysis)
    result = await runner.execute(
        RunExecutionCommand(
            analysis_execution_id=execution.execution.id,
            request=harness.request,
            job_id=execution.execution.scheduled_job_id,
            worker_id="worker-1",
        )
    )

    assert result.execution.state is ExecutionState.SUCCEEDED
    assert result.artifact_count == 1
    stored = await harness.repositories.scientific_executions.get(result.scientific_execution_id)
    assert stored.state is ScientificExecutionState.SUCCEEDED
    # Provenance is what the subsystem reported, not what the application assumed.
    assert stored.engine_version == "0.0.0-development-only"
    assert stored.node_identity is not None


async def test_execution_provenance_exposes_engine_and_artifacts() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    await register_scientific_node(harness)
    _, _, execution = await queued_execution(harness, user_id)
    await RunAnalysisExecution(harness.analysis).execute(
        RunExecutionCommand(
            analysis_execution_id=execution.execution.id, request=harness.request
        )
    )

    provenance = await GetExecutionProvenance(harness.analysis).execute(
        GetExecutionProvenanceQuery(
            actor=await actor_for(harness, user_id),
            execution_id=execution.execution.id,
            request=harness.request,
        )
    )

    assert provenance.configuration_snapshot
    assert len(provenance.scientific_executions) == 1
    record, artifacts = provenance.scientific_executions[0]
    assert record.capability_key == "integration.echo"
    assert len(artifacts) == 1


async def test_execution_without_an_eligible_node_stays_retryable() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    _, _, execution = await queued_execution(harness, user_id)

    # No node registered at all: the run must not fail the analysis.
    with pytest.raises(Exception) as failure:
        await RunAnalysisExecution(harness.analysis).execute(
            RunExecutionCommand(
                analysis_execution_id=execution.execution.id, request=harness.request
            )
        )
    assert "node" in str(failure.value).lower()

    stored = await harness.repositories.analysis_executions.get(execution.execution.id)
    assert stored.state is not ExecutionState.FAILED


async def test_draining_a_node_removes_it_from_selection() -> None:
    harness = build_harness()
    admin_id = await create_account(harness, "admin@example.test")
    await grant_platform_role(harness, admin_id, PlatformRole.PLATFORM_ADMINISTRATOR)
    node = await register_scientific_node(harness)

    drained = await ChangeNodeLifecycle(harness.analysis).execute(
        ChangeNodeLifecycleCommand(
            actor=await actor_for(harness, admin_id),
            node_id=node.id,
            target=NodeLifecycleState.DRAINING,
            reason="maintenance window",
            request=harness.request,
        )
    )
    assert drained.lifecycle_state is NodeLifecycleState.DRAINING

    user_id = await create_account(harness, "owner@example.test")
    _, _, execution = await queued_execution(harness, user_id)
    with pytest.raises(Exception):
        await RunAnalysisExecution(harness.analysis).execute(
            RunExecutionCommand(
                analysis_execution_id=execution.execution.id, request=harness.request
            )
        )


async def test_node_listing_requires_platform_compute_permission() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    await register_scientific_node(harness)

    with pytest.raises(AuthorizationError):
        await ListNodes(harness.analysis).execute(
            ListNodesQuery(actor=await actor_for(harness, user_id), request=harness.request)
        )

    admin_id = await create_account(harness, "admin@example.test")
    await grant_platform_role(harness, admin_id, PlatformRole.PLATFORM_ADMINISTRATOR)
    nodes = await ListNodes(harness.analysis).execute(
        ListNodesQuery(actor=await actor_for(harness, admin_id), request=harness.request)
    )
    assert len(nodes) == 1


async def test_cancelling_a_queued_execution_marks_the_job_for_cancellation() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    _, _, execution = await queued_execution(harness, user_id)

    cancelled = await CancelExecution(harness.analysis).execute(
        CancelExecutionCommand(
            actor=await actor_for(harness, user_id),
            execution_id=execution.execution.id,
            reason="operator stopped it",
            request=harness.request,
        )
    )

    assert cancelled.execution.state in (
        ExecutionState.CANCELLED,
        ExecutionState.CANCEL_REQUESTED,
    )
    job = await harness.repositories.jobs.find(execution.execution.scheduled_job_id)
    assert job.cancellation_requested is True


async def test_a_cancel_request_stops_the_run_instead_of_fabricating_a_result() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    await register_scientific_node(harness)
    _, _, execution = await queued_execution(harness, user_id)
    await CancelExecution(harness.analysis).execute(
        CancelExecutionCommand(
            actor=await actor_for(harness, user_id),
            execution_id=execution.execution.id,
            reason=None,
            request=harness.request,
        )
    )

    result = await RunAnalysisExecution(harness.analysis).execute(
        RunExecutionCommand(
            analysis_execution_id=execution.execution.id, request=harness.request
        )
    )

    assert result.execution.state is ExecutionState.CANCELLED
    assert result.scientific_execution_id is None


async def test_execution_and_job_are_invisible_to_another_workspace() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.test")
    stranger_id = await create_account(harness, "stranger@example.test")
    _, _, execution = await queued_execution(harness, owner_id)

    with pytest.raises((NotFoundError, AuthorizationError)):
        await GetExecution(harness.analysis).execute(
            GetExecutionQuery(
                actor=await actor_for(harness, stranger_id),
                execution_id=execution.execution.id,
                request=harness.request,
            )
        )
    with pytest.raises((NotFoundError, AuthorizationError)):
        await GetJob(harness.analysis).execute(
            GetJobQuery(
                actor=await actor_for(harness, stranger_id),
                job_id=execution.execution.scheduled_job_id,
                request=harness.request,
            )
        )
    listing = await ListJobs(harness.analysis).execute(
        ListJobsQuery(
            actor=await actor_for(harness, stranger_id), page=PAGE, request=harness.request
        )
    )
    assert listing.items == ()


async def test_platform_job_console_requires_platform_permission() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.test")
    await queued_execution(harness, owner_id)

    with pytest.raises(AuthorizationError):
        await ListPlatformJobs(harness.analysis).execute(
            ListPlatformJobsQuery(
                actor=await actor_for(harness, owner_id), page=PAGE, request=harness.request
            )
        )

    admin_id = await create_account(harness, "admin@example.test")
    await grant_platform_role(harness, admin_id, PlatformRole.PLATFORM_ADMINISTRATOR)
    listing = await ListPlatformJobs(harness.analysis).execute(
        ListPlatformJobsQuery(
            actor=await actor_for(harness, admin_id), page=PAGE, request=harness.request
        )
    )
    statistics = await GetQueueStatistics(harness.analysis).execute(
        GetQueueStatisticsQuery(
            actor=await actor_for(harness, admin_id), request=harness.request
        )
    )
    assert listing.total >= 1
    assert statistics


async def test_platform_administrator_can_cancel_a_job() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.test")
    admin_id = await create_account(harness, "admin@example.test")
    await grant_platform_role(harness, admin_id, PlatformRole.PLATFORM_ADMINISTRATOR)
    _, _, execution = await queued_execution(harness, owner_id)

    await CancelJob(harness.analysis).execute(
        CancelJobCommand(
            actor=await actor_for(harness, admin_id),
            job_id=execution.execution.scheduled_job_id,
            reason="queue drained",
            request=harness.request,
        )
    )

    job = await harness.repositories.jobs.find(execution.execution.scheduled_job_id)
    assert job.cancellation_requested is True


async def test_worker_runtime_claims_only_its_own_kinds() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    await register_scientific_node(harness)
    _, _, execution = await queued_execution(harness, user_id)
    seen: list[str] = []

    async def dispatch(job, worker_id=None):
        seen.append(job.id)

    # A runtime restricted to another kind must not claim this job.
    other = await _runtime(harness, dispatch, kinds=(JobKind.DATASET_IMPORT,))
    assert await other.run_once() is False
    assert seen == []

    mine = await _runtime(harness, dispatch, kinds=(JobKind.ANALYSIS_EXECUTION,))
    assert await mine.run_once() is True
    assert seen == [execution.execution.scheduled_job_id]
    job = await harness.repositories.jobs.find(execution.execution.scheduled_job_id)
    assert job.state is JobState.SUCCEEDED
    assert job.attempt_number == 1


async def test_a_failed_attempt_is_retried_then_dead_lettered() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    _, _, execution = await queued_execution(harness, user_id)
    job_id = execution.execution.scheduled_job_id
    calls = {"n": 0}

    async def dispatch(job, worker_id=None):
        calls["n"] += 1
        raise RuntimeError("engine unreachable")

    runtime = await _runtime(harness, dispatch, kinds=(JobKind.ANALYSIS_EXECUTION,))
    for _ in range(6):
        job = await harness.repositories.jobs.find(job_id)
        if job.state in (JobState.DEAD_LETTER, JobState.FAILED):
            break
        # Retries are scheduled in the future; move the clock to the next slot.
        if job.state is JobState.QUEUED and job.available_at is not None:
            harness.clock.advance(seconds=600)
        await runtime.run_once()

    job = await harness.repositories.jobs.find(job_id)
    assert calls["n"] >= 1
    assert job.state in (JobState.DEAD_LETTER, JobState.FAILED)
    attempts = await harness.repositories.jobs.list_attempts(job_id)
    assert len(attempts) >= 1
    assert all(attempt.failure_message for attempt in attempts)


async def test_two_workers_never_claim_the_same_job() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    _, _, execution = await queued_execution(harness, user_id)
    claimed: list[str] = []

    async def dispatch(job, worker_id=None):
        claimed.append(job.id)
        await asyncio.sleep(0)

    first = JobRuntime(
        unit_of_work=harness.unit_of_work,
        clock=harness.clock,
        dispatch=dispatch,
        identity=WorkerIdentity(worker_id="worker-a", kinds=(JobKind.ANALYSIS_EXECUTION,)),
    )
    second = JobRuntime(
        unit_of_work=harness.unit_of_work,
        clock=harness.clock,
        dispatch=dispatch,
        identity=WorkerIdentity(worker_id="worker-b", kinds=(JobKind.ANALYSIS_EXECUTION,)),
    )

    results = await asyncio.gather(first.run_once(), second.run_once())

    assert sorted(results) == [False, True]
    assert claimed == [execution.execution.scheduled_job_id]
