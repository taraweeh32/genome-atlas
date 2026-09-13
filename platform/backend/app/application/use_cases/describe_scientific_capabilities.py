"""Use case: report the scientific subsystem's identity and capabilities.

The application only relays what the subsystem declares. It never computes,
infers or validates scientific behaviour.
"""

from __future__ import annotations

from app.scientific.contracts import ScientificCapabilities, ScientificEngineGateway


class DescribeScientificCapabilities:
    def __init__(self, gateway: ScientificEngineGateway) -> None:
        self._gateway = gateway

    async def execute(self) -> ScientificCapabilities:
        return await self._gateway.describe_capabilities()
