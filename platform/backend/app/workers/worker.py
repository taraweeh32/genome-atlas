"""Background worker entry point.

Package 1 establishes only the process shape: configuration validation, logging,
infrastructure lifecycle, correlation propagation and graceful shutdown on
SIGINT/SIGTERM. Queue consumption and job handlers belong to a later package —
this loop deliberately claims no work.
"""

from __future__ import annotations

import asyncio
import signal

from app.application.container import Container
from app.core.environment import get_environment_settings
from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)

IDLE_INTERVAL_SECONDS = 5.0


async def run_worker() -> None:
    environment = get_environment_settings()
    configure_logging(environment.log_level)

    container = Container.build()
    await container.startup()
    stop = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    logger.info("worker started", extra={"environment": environment.environment.value})
    try:
        while not stop.is_set():
            # Job dispatch is introduced in a later package. Until then the
            # worker stays idle rather than pretending to process work.
            try:
                await asyncio.wait_for(stop.wait(), timeout=IDLE_INTERVAL_SECONDS)
            except TimeoutError:
                continue
    finally:
        logger.info("worker stopping")
        await container.shutdown()
        logger.info("worker stopped")


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
