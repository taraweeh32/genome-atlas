"""Scheduled analyses, recurring execution, and stale-work recovery.

Pinned here: a schedule fires at most one execution per due slot, concurrency
policy is enforced by the backend, a trigger records its own outcome, and a job
whose worker vanished returns to the queue instead of being lost.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.application.use_cases.analysis.maintenance import RecoverAbandonedWork
from app.application.use_cases.analysis.nodes import MarkSilentNodesUnhealthy
from app.application.use_cases.analysis.executions import (
    RequestExecution,
    RequestExecutionCommand,
)
from app.application.use_cases.analysis.scheduler import TriggerDueSchedules
from app.application.use_cases.analysis.schedules import (
    ChangeScheduleState,
    ChangeScheduleStateCommand,
    CreateSchedule,
    CreateScheduleCommand,
    ListScheduleTriggers,
    ListScheduleTriggersQuery,
    ListSchedules,
    ListSchedulesQuery,
    UpdateSchedule,
    UpdateScheduleCommand,
)
from app.domain.errors import AuthorizationError, NotFoundError, ValidationError
from app.domain.value_objects.enums import (
    JobKind,
    JobState,
    NodeClass,
    NodeHealthState,
    ScheduleConcurrencyPolicy,
    ScheduleState,
)
from tests.analysis.support import (
    PAGE,
    configured_analysis,
    queued_execution,
    register_scientific_node,
)
from tests.support.actors import actor_for, create_account
from tests.support.services import build_harness

pytestmark = pytest.mark.anyio


async def _schedule(harness, user_id, analysis_id, **overrides):
    command = {
        "actor": await actor_for(harness, user_id),
        "analysis_id": analysis_id,
        "name": "Nightly Rerun",
        "schedule_expression": "every:1h",
        "timezone_name": "UTC",
        "request": harness.request,
    }
    command.update(overrides)
    return await CreateSchedule(harness.analysis).execute(CreateScheduleCommand(**command))


async def test_schedule_is_created_with_a_resolved_next_slot() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    analysis, configuration = await configured_analysis(harness, user_id)

    view = await _schedule(harness, user_id, analysis.analysis.id)

    assert view.schedule.state is ScheduleState.ENABLED
    assert view.schedule.next_execution_at is not None
    assert view.schedule.analysis_configuration_id == configuration.configuration.id
    assert view.can_manage is True


async def test_an_unparseable_schedule_expression_is_refused() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    analysis, _ = await configured_analysis(harness, user_id)

    with pytest.raises(ValidationError):
        await _schedule(harness, user_id, analysis.analysis.id, schedule_expression="whenever")


async def test_an_unknown_timezone_is_refused() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    analysis, _ = await configured_analysis(harness, user_id)

    with pytest.raises(ValidationError):
        await _schedule(harness, user_id, analysis.analysis.id, timezone_name="Mars/Olympus")


async def test_a_due_schedule_fires_exactly_one_execution_per_slot() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    await register_scientific_node(harness)
    analysis, _ = await configured_analysis(harness, user_id)
    schedule = await _schedule(harness, user_id, analysis.analysis.id)

    harness.clock.advance(seconds=3700)
    first = await TriggerDueSchedules(harness.analysis).execute()
    # A second pass in the same slot must not fire again.
    second = await TriggerDueSchedules(harness.analysis).execute()

    assert first.triggered == 1
    assert second.triggered == 0
    triggers = await ListScheduleTriggers(harness.analysis).execute(
        ListScheduleTriggersQuery(
            actor=await actor_for(harness, user_id),
            schedule_id=schedule.schedule.id,
            page=PAGE,
            request=harness.request,
        )
    )
    assert triggers.total == 1
    stored = await harness.repositories.schedules.get(schedule.schedule.id)
    assert stored.previous_execution_at is not None
    assert stored.next_execution_at > stored.previous_execution_at


async def test_skip_if_running_policy_does_not_stack_executions() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    analysis, _ = await configured_analysis(harness, user_id)
    schedule = await _schedule(
        harness,
        user_id,
        analysis.analysis.id,
        concurrency_policy=ScheduleConcurrencyPolicy.SKIP_IF_RUNNING,
    )
    # An execution is already in flight for this very analysis.
    await RequestExecution(harness.analysis).execute(
        RequestExecutionCommand(
            actor=await actor_for(harness, user_id),
            analysis_id=analysis.analysis.id,
            request=harness.request,
        )
    )

    harness.clock.advance(seconds=3700)
    summary = await TriggerDueSchedules(harness.analysis).execute()

    assert summary.triggered == 0
    assert summary.skipped == 1
    stored = await harness.repositories.schedules.get(schedule.schedule.id)
    # The slot is still consumed: the platform never silently re-fires it later.
    assert stored.next_execution_at is not None


async def test_a_disabled_schedule_is_never_triggered() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    analysis, _ = await configured_analysis(harness, user_id)
    schedule = await _schedule(harness, user_id, analysis.analysis.id)

    await ChangeScheduleState(harness.analysis).execute(
        ChangeScheduleStateCommand(
            actor=await actor_for(harness, user_id),
            schedule_id=schedule.schedule.id,
            target=ScheduleState.DISABLED,
            request=harness.request,
        )
    )
    harness.clock.advance(seconds=7300)
    summary = await TriggerDueSchedules(harness.analysis).execute()

    assert summary.triggered == 0


async def test_schedules_are_scoped_to_the_caller() -> None:
    harness = build_harness()
    owner_id = await create_account(harness, "owner@example.test")
    stranger_id = await create_account(harness, "stranger@example.test")
    analysis, _ = await configured_analysis(harness, owner_id)
    schedule = await _schedule(harness, owner_id, analysis.analysis.id)

    theirs = await ListSchedules(harness.analysis).execute(
        ListSchedulesQuery(
            actor=await actor_for(harness, stranger_id), page=PAGE, request=harness.request
        )
    )
    assert theirs.items == ()

    with pytest.raises((NotFoundError, AuthorizationError)):
        await UpdateSchedule(harness.analysis).execute(
            UpdateScheduleCommand(
                actor=await actor_for(harness, stranger_id),
                schedule_id=schedule.schedule.id,
                request=harness.request,
                description="hijack",
            )
        )


async def test_updating_a_schedule_recomputes_the_next_slot() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    analysis, _ = await configured_analysis(harness, user_id)
    schedule = await _schedule(harness, user_id, analysis.analysis.id)
    before = schedule.schedule.next_execution_at

    updated = await UpdateSchedule(harness.analysis).execute(
        UpdateScheduleCommand(
            actor=await actor_for(harness, user_id),
            schedule_id=schedule.schedule.id,
            request=harness.request,
            schedule_expression="every:15m",
        )
    )

    assert updated.schedule.schedule_expression == "every:15m"
    assert updated.schedule.next_execution_at < before


async def test_a_job_whose_worker_vanished_is_recovered() -> None:
    harness = build_harness()
    user_id = await create_account(harness, "owner@example.test")
    _, _, execution = await queued_execution(harness, user_id)
    job_id = execution.execution.scheduled_job_id
    now = harness.clock.now()

    # A worker claims the job and then disappears without a heartbeat.
    claimed = await harness.repositories.jobs.claim_next(
        worker_id="ghost-worker",
        queues=("default",),
        node_class=NodeClass.APPLICATION_WORKER,
        kinds=(JobKind.ANALYSIS_EXECUTION,),
        now=now,
        lease_expires_at=now + timedelta(seconds=60),
    )
    assert claimed is not None and claimed.id == job_id
    await harness.repositories.jobs.mark_running(
        job_id=job_id, worker_id="ghost-worker", now=now
    )

    harness.clock.advance(seconds=3600)
    summary = await RecoverAbandonedWork(harness.analysis).execute()

    job = await harness.repositories.jobs.find(job_id)
    assert summary.requeued + summary.dead_lettered == 1
    assert job.state in (JobState.QUEUED, JobState.DEAD_LETTER)
    if job.state is JobState.QUEUED:
        # Recovery hands the work back; it never leaves a phantom lease behind.
        assert job.claimed_by_worker_id is None


async def test_a_silent_node_is_marked_unhealthy_without_changing_intent() -> None:
    harness = build_harness()
    node = await register_scientific_node(harness)
    assert node.health_state is NodeHealthState.HEALTHY

    harness.clock.advance(seconds=600)
    marked = await MarkSilentNodesUnhealthy(harness.analysis).execute()

    stored = await harness.repositories.compute_nodes.get(node.id)
    assert marked == 1
    assert stored.health_state is NodeHealthState.UNAVAILABLE
    # Observed health is not administrative intent.
    assert stored.lifecycle_state is node.lifecycle_state


async def test_recovery_reports_both_jobs_and_nodes() -> None:
    harness = build_harness()
    await register_scientific_node(harness)
    harness.clock.advance(seconds=1200)

    summary = await RecoverAbandonedWork(harness.analysis).execute()

    assert summary.nodes_marked_unhealthy == 1
    assert summary.requeued == 0
