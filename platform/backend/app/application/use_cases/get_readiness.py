"""Use case: determine whether this instance can actually serve requests.

"The process is running" is liveness, not readiness. Readiness aggregates
dependency probes and is what orchestration systems must consult.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime

from app.application.ports import DependencyProbe, DependencyStatus, HealthProbe
from app.domain.entities.base import utc_now


@dataclass(frozen=True, slots=True)
class ReadinessReport:
    ready: bool
    checked_at: datetime
    dependencies: tuple[DependencyProbe, ...]


class GetReadiness:
    def __init__(self, probes: tuple[HealthProbe, ...]) -> None:
        self._probes = probes

    async def execute(self) -> ReadinessReport:
        results = await asyncio.gather(
            *(self._safe_probe(probe) for probe in self._probes),
        )
        ready = not any(result.blocks_readiness for result in results)
        return ReadinessReport(ready=ready, checked_at=utc_now(), dependencies=tuple(results))

    @staticmethod
    async def _safe_probe(probe: HealthProbe) -> DependencyProbe:
        try:
            return await probe.probe()
        except Exception:  # noqa: BLE001 - a probe must never break readiness reporting
            return DependencyProbe(
                name=probe.name,
                status=DependencyStatus.DOWN,
                required=probe.required,
                detail="probe raised an unexpected error",
            )
