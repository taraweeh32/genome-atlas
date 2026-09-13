"""Background worker entry point.

The process hosts three cooperating loops, all shut down together:

* an **application worker** runtime, claiming ordinary queues (imports,
  validation, exports, maintenance, analysis orchestration);
* a **scientific worker** runtime, claiming only the scientific queue, so
  scientific execution custody stays on its own fleet even when both run in one
  development container; and
* a **schedule tick**, which fires due schedules in bounded batches.

Nothing here decides *what* work means. Custody lives in
:mod:`app.workers.runtime`, the work itself in use cases, and scientific compute
in the independent subsystem behind the integration contract.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import uuid

from app.application.container import Container
from app.application.use_cases.analysis.maintenance import RecoverAbandonedWork
from app.application.use_cases.analysis.scheduler import TriggerDueSchedules
from app.core.environment import get_environment_settings
from app.core.logging import configure_logging, get_logger
from app.domain.value_objects.enums import JobKind, NodeClass
from app.workers.dispatch import JobDispatcher
from app.workers.runtime import JobRuntime, WorkerIdentity

logger = get_logger(__name__)

SCIENTIFIC_KINDS: tuple[JobKind, ...] = (JobKind.SCIENTIFIC_EXECUTION,)


def worker_identity_prefix() -> str:
    """A stable, human-recognisable worker id: host, pid and a short nonce."""
    return f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"


async def _schedule_tick(container: Container, stop: asyncio.Event, interval: float) -> None:
    """Fire due schedules until asked to stop.

    Each pass is bounded by the scheduler's batch size, and a failure is logged
    without killing the loop: a broken schedule must not stop every other one.
    """
    while not stop.is_set():
        try:
            summary = await TriggerDueSchedules(container.analysis_services()).execute()
            if summary.considered:
                logger.info(
                    "schedule tick completed",
                    extra={
                        "considered": summary.considered,
                        "triggered": summary.triggered,
                        "skipped": summary.skipped,
                        "failed": summary.failed,
                    },
                )
        except Exception:
            logger.exception("schedule tick failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except TimeoutError:
            continue


def build_runtimes(container: Container, prefix: str) -> tuple[JobRuntime, ...]:
    settings = container.application
    dispatcher = JobDispatcher(container)
    services = container.analysis_services()

    async def recover() -> None:
        await RecoverAbandonedWork(services).execute()

    def runtime(identity: WorkerIdentity, *, with_recovery: bool) -> JobRuntime:
        return JobRuntime(
            unit_of_work=container.unit_of_work,
            clock=container.clock,
            dispatch=lambda job: dispatcher.dispatch(job, worker_id=identity.worker_id),
            identity=identity,
            retry=services.retry,
            lease=services.lease,
            timeouts=services.timeouts,
            recover=recover if with_recovery else None,
            recovery_interval_seconds=settings.worker_recovery_interval_seconds,
        )

    runtimes = [
        runtime(
            WorkerIdentity(
                worker_id=f"app-{prefix}",
                node_class=NodeClass.APPLICATION_WORKER,
                queues=settings.application_queue_names,
            ),
            with_recovery=True,
        )
    ]
    if settings.worker_scientific_enabled:
        runtimes.append(
            runtime(
                WorkerIdentity(
                    worker_id=f"sci-{prefix}",
                    node_class=NodeClass.SCIENTIFIC_WORKER,
                    queues=settings.scientific_queue_names,
                    kinds=SCIENTIFIC_KINDS,
                ),
                with_recovery=False,
            )
        )
    return tuple(runtimes)


async def run_worker() -> None:
    environment = get_environment_settings()
    configure_logging(environment.log_level)

    container = Container.build()
    await container.startup()
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    prefix = worker_identity_prefix()
    runtimes = build_runtimes(container, prefix)
    logger.info(
        "worker started",
        extra={
            "environment": environment.environment.value,
            "worker_prefix": prefix,
            "fleets": [runtime_.identity.worker_id for runtime_ in runtimes],
        },
    )
    tasks = [asyncio.create_task(runtime_.run_until(stop)) for runtime_ in runtimes]
    tasks.append(
        asyncio.create_task(
            _schedule_tick(
                container, stop, float(container.application.worker_schedule_interval_seconds)
            )
        )
    )
    try:
        await asyncio.gather(*tasks)
    finally:
        logger.info("worker stopping")
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await container.shutdown()
        logger.info(
            "worker stopped",
            extra={
                "counters": {
                    runtime_.identity.worker_id: runtime_.counters.as_mapping()
                    for runtime_ in runtimes
                }
            },
        )


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
