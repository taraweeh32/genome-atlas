"""The durable job runtime: claim, lease, heartbeat, timeout, retry, cancel.

This is the execution half of the job subsystem, and it is deliberately the only
place in the codebase that owns it. Everything here is about *work custody*, not
about what the work means:

* **Claiming** is a single atomic statement in the repository. Two workers can
  race for the same queue and exactly one of them gets the row.
* **Leases** bound how long a claim is honoured. The runtime heartbeats while the
  handler runs; a worker that dies stops heartbeating and recovery re-queues the
  job instead of leaving it "running" forever.
* **Losing the lease is fatal to the attempt.** If a heartbeat reports that this
  worker no longer holds the claim, the runtime abandons the attempt rather than
  writing a result another worker may already be producing.
* **Cancellation is cooperative.** A cancel request observed by a heartbeat
  cancels the in-flight handler task and records the job as cancelled — it never
  synthesises a success or a failure.
* **Retry is policy-driven.** The error is classified, and only a retryable class
  with attempts remaining is rescheduled with backoff. Everything else fails or
  dead-letters, because retrying a permanent error is how one bug becomes a storm.
* **Every attempt is recorded** append-only — one row per attempt number, written
  when the attempt reaches its outcome — so an operator can see each try, its
  worker, its node and how it ended.

Application workers and scientific-execution workers are the same runtime with a
different ``node_class`` and queue set: the fleets stay architecturally distinct
without duplicating custody logic.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.application.services.context import RequestContext
from app.application.services.recorder import ActivityRecorder
from app.core.logging import get_logger
from app.domain.analysis.entities import JobAttemptRecord, JobRecord
from app.domain.analysis.policies import LeasePolicy, RetryPolicy, TimeoutPolicy, classify_exception
from app.domain.events import EventType
from app.domain.value_objects.enums import JobErrorClass, JobKind, JobQueue, JobState, NodeClass
from app.infrastructure.persistence.repositories.base import new_id

logger = get_logger(__name__)

#: How long an idle worker waits before asking for work again.
IDLE_POLL_SECONDS = 2.0
#: How often abandoned work is recovered, independent of queue traffic.
RECOVERY_INTERVAL_SECONDS = 30.0

JobDispatch = Callable[[JobRecord], Awaitable[Any]]


class LeaseLostError(RuntimeError):
    """This worker no longer holds the claim; the attempt must be abandoned."""


@dataclass(frozen=True, slots=True)
class WorkerIdentity:
    """Which fleet this process belongs to and what it may claim."""

    worker_id: str
    node_class: NodeClass = NodeClass.APPLICATION_WORKER
    queues: tuple[str, ...] = (JobQueue.DEFAULT.value,)
    kinds: tuple[JobKind, ...] = ()
    node_id: str | None = None


@dataclass
class RuntimeCounters:
    claimed: int = 0
    succeeded: int = 0
    failed: int = 0
    retried: int = 0
    cancelled: int = 0
    dead_lettered: int = 0
    lease_lost: int = 0

    def as_mapping(self) -> dict[str, int]:
        return {
            "claimed": self.claimed,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "retried": self.retried,
            "cancelled": self.cancelled,
            "dead_lettered": self.dead_lettered,
            "lease_lost": self.lease_lost,
        }


@dataclass
class _AttemptOutcome:
    state: JobState
    error_class: JobErrorClass | None = None
    code: str | None = None
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class JobRuntime:
    """Runs durable jobs for one worker identity."""

    def __init__(
        self,
        *,
        unit_of_work: Any,
        clock: Any,
        dispatch: JobDispatch,
        identity: WorkerIdentity,
        retry: RetryPolicy | None = None,
        lease: LeasePolicy | None = None,
        timeouts: TimeoutPolicy | None = None,
        recover: Callable[[], Awaitable[Any]] | None = None,
        idle_poll_seconds: float = IDLE_POLL_SECONDS,
        recovery_interval_seconds: float = RECOVERY_INTERVAL_SECONDS,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._clock = clock
        self._dispatch = dispatch
        self._identity = identity
        self._retry = retry or RetryPolicy()
        self._lease = lease or LeasePolicy()
        self._timeouts = timeouts or TimeoutPolicy()
        self._recover = recover
        self._idle_poll_seconds = idle_poll_seconds
        self._recovery_interval_seconds = recovery_interval_seconds
        self.counters = RuntimeCounters()

    @property
    def identity(self) -> WorkerIdentity:
        return self._identity

    # -- loop -------------------------------------------------------------- #

    async def run_until(self, stop: asyncio.Event) -> RuntimeCounters:
        """Claim and run jobs until asked to stop.

        A stop request never abandons the job in flight: the loop finishes the
        current attempt (its result is already durable) before returning.
        """
        recovery_at = 0.0
        loop = asyncio.get_running_loop()
        while not stop.is_set():
            if self._recover is not None and loop.time() >= recovery_at:
                recovery_at = loop.time() + self._recovery_interval_seconds
                try:
                    await self._recover()
                except Exception:
                    logger.exception("stale job recovery failed")
            try:
                worked = await self.run_once()
            except Exception:
                logger.exception("job runtime iteration failed")
                worked = False
            if worked:
                continue
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._idle_poll_seconds)
            except TimeoutError:
                continue
        return self.counters

    async def run_once(self) -> bool:
        """Claim at most one job and run it to a durable outcome."""
        job = await self._claim()
        if job is None:
            return False
        self.counters.claimed += 1
        attempt_number = job.attempt_number
        started_at = self._clock.now()
        cancelled = asyncio.Event()

        await self._mark_running(job)

        heartbeat = asyncio.create_task(self._heartbeat(job, cancelled))
        work = asyncio.create_task(self._dispatch(job))
        timeout = self._timeouts.for_kind(job.kind)
        outcome: _AttemptOutcome
        try:
            done, _ = await asyncio.wait(
                {work, heartbeat}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if work in done:
                work.result()
                outcome = _AttemptOutcome(state=JobState.SUCCEEDED)
            elif heartbeat in done:
                # The heartbeat only finishes early on cancellation or lease loss.
                work.cancel()
                await asyncio.gather(work, return_exceptions=True)
                heartbeat.result()
                outcome = (
                    _AttemptOutcome(
                        state=JobState.CANCELLED,
                        error_class=JobErrorClass.CANCELLATION,
                        code="job.cancelled",
                        message="cancellation was requested while the job was running",
                    )
                    if cancelled.is_set()
                    else _AttemptOutcome(
                        state=JobState.FAILED,
                        error_class=JobErrorClass.TRANSIENT_INFRASTRUCTURE_ERROR,
                        code="job.lease_lost",
                        message="this worker no longer holds the lease for the job",
                    )
                )
            else:
                work.cancel()
                await asyncio.gather(work, return_exceptions=True)
                outcome = _AttemptOutcome(
                    state=JobState.FAILED,
                    error_class=JobErrorClass.TIMEOUT,
                    code="job.timeout",
                    message="the job exceeded its wall-clock budget for one attempt",
                    details={"timeout_seconds": timeout},
                )
        except asyncio.CancelledError:
            work.cancel()
            raise
        except Exception as error:  # noqa: BLE001 - classified, then recorded
            error_class = classify_exception(error)
            outcome = _AttemptOutcome(
                state=JobState.FAILED,
                error_class=error_class,
                code=getattr(error, "code", None) or type(error).__name__,
                message=str(error) or "the job handler raised an error",
                details=dict(getattr(error, "details", {}) or {}),
            )
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

        if outcome.state is JobState.SUCCEEDED and work.done() and work.exception() is not None:
            error = work.exception()
            assert error is not None
            error_class = classify_exception(error)
            outcome = _AttemptOutcome(
                state=JobState.FAILED,
                error_class=error_class,
                code=getattr(error, "code", None) or type(error).__name__,
                message=str(error) or "the job handler raised an error",
                details=dict(getattr(error, "details", {}) or {}),
            )

        await self._finish(
            job, attempt_number=attempt_number, started_at=started_at, outcome=outcome
        )
        return True

    # -- custody ----------------------------------------------------------- #

    async def _claim(self) -> JobRecord | None:
        now = self._clock.now()
        async with self._unit_of_work.begin() as repositories:
            return await repositories.jobs.claim_next(
                worker_id=self._identity.worker_id,
                queues=self._identity.queues,
                node_class=self._identity.node_class,
                kinds=self._identity.kinds,
                now=now,
                lease_expires_at=self._lease.expires_at(now),
                node_id=self._identity.node_id,
            )

    async def _mark_running(self, job: JobRecord) -> None:
        async with self._unit_of_work.begin() as repositories:
            await repositories.jobs.mark_running(
                job_id=job.id, worker_id=self._identity.worker_id, now=self._clock.now()
            )

    async def _heartbeat(self, job: JobRecord, cancelled: asyncio.Event) -> None:
        """Extend the lease until the claim is lost or cancellation is requested."""
        while True:
            await asyncio.sleep(self._lease.heartbeat_interval_seconds)
            now = self._clock.now()
            async with self._unit_of_work.begin() as repositories:
                current = await repositories.jobs.heartbeat(
                    job_id=job.id,
                    worker_id=self._identity.worker_id,
                    now=now,
                    lease_expires_at=self._lease.expires_at(now),
                )
            if current is None:
                self.counters.lease_lost += 1
                return
            if current.cancellation_requested or current.state is JobState.CANCEL_REQUESTED:
                cancelled.set()
                return

    async def _record_attempt(
        self,
        job: JobRecord,
        *,
        attempt_number: int,
        state: JobState,
        started_at: datetime,
        finished_at: datetime | None = None,
        outcome: _AttemptOutcome | None = None,
    ) -> None:
        async with self._unit_of_work.begin() as repositories:
            await repositories.jobs.add_attempt(
                JobAttemptRecord(
                    id=new_id("jatt"),
                    job_id=job.id,
                    attempt_number=attempt_number,
                    state=state,
                    worker_id=self._identity.worker_id,
                    node_id=self._identity.node_id,
                    started_at=started_at,
                    finished_at=finished_at,
                    failure_code=outcome.code if outcome else None,
                    failure_message=outcome.message if outcome else None,
                    error_class=outcome.error_class if outcome else None,
                    diagnostics=dict(outcome.details) if outcome else {},
                )
            )

    async def _finish(
        self,
        job: JobRecord,
        *,
        attempt_number: int,
        started_at: datetime,
        outcome: _AttemptOutcome,
    ) -> None:
        now = self._clock.now()
        if outcome.state is JobState.SUCCEEDED:
            async with self._unit_of_work.begin() as repositories:
                await repositories.jobs.complete(
                    job_id=job.id, worker_id=self._identity.worker_id, now=now
                )
            self.counters.succeeded += 1
            await self._record_attempt(
                job,
                attempt_number=attempt_number,
                state=JobState.SUCCEEDED,
                started_at=started_at,
                finished_at=now,
            )
            return

        if outcome.state is JobState.CANCELLED:
            async with self._unit_of_work.begin() as repositories:
                await repositories.jobs.mark_cancelled(job_id=job.id, now=now)
            self.counters.cancelled += 1
            await self._record_attempt(
                job,
                attempt_number=attempt_number,
                state=JobState.CANCELLED,
                started_at=started_at,
                finished_at=now,
                outcome=outcome,
            )
            return

        error_class = outcome.error_class or JobErrorClass.INTERNAL_ERROR
        retry = self._retry.should_retry(
            attempt_number=attempt_number, error_class=error_class
        )
        retry_at = (
            self._retry.next_attempt_at(attempt_number=attempt_number, now=now) if retry else None
        )
        dead_letter = not retry and attempt_number >= self._retry.max_attempts
        async with self._unit_of_work.begin() as repositories:
            await repositories.jobs.fail(
                job_id=job.id,
                worker_id=self._identity.worker_id,
                now=now,
                error_class=error_class,
                code=outcome.code or "job.failed",
                message=outcome.message or "the job failed",
                details=outcome.details,
                retry_at=retry_at,
                dead_letter=dead_letter,
            )
            if dead_letter:
                await ActivityRecorder(repositories, RequestContext.system()).event(
                    event_type=EventType.JOB_DEAD_LETTERED,
                    aggregate_type="job",
                    aggregate_id=job.id,
                    occurred_at=now,
                    workspace_id=job.workspace_id,
                    payload={"attempt_number": attempt_number, "failure_code": outcome.code},
                )
        if retry:
            self.counters.retried += 1
        elif dead_letter:
            self.counters.dead_lettered += 1
        else:
            self.counters.failed += 1
        await self._record_attempt(
            job,
            attempt_number=attempt_number,
            state=JobState.RETRY_WAITING if retry else JobState.FAILED,
            started_at=started_at,
            finished_at=now,
            outcome=outcome,
        )
        logger.warning(
            "job attempt failed",
            extra={
                "job_id": job.id,
                "job_kind": job.kind.value,
                "attempt_number": attempt_number,
                "error_class": error_class.value,
                "failure_code": outcome.code,
                "retry_scheduled": retry,
                "dead_letter": dead_letter,
            },
        )


__all__ = [
    "IDLE_POLL_SECONDS",
    "RECOVERY_INTERVAL_SECONDS",
    "JobRuntime",
    "LeaseLostError",
    "RuntimeCounters",
    "WorkerIdentity",
]
