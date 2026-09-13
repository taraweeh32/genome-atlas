"""Composition-root tests: wiring, probe set and shutdown behaviour.

The container is the only place that constructs infrastructure. These tests
assert that it wires every dependency the readiness contract promises, and that
teardown is best-effort (one failing component must not skip the rest).
"""

from __future__ import annotations

import pytest

from app.application.container import Container
from app.application.use_cases.describe_scientific_capabilities import (
    DescribeScientificCapabilities,
)
from app.application.use_cases.get_readiness import GetReadiness
from app.scientific.contracts import ScientificEngineGateway


@pytest.fixture
def container() -> Container:
    return Container.build()


def test_container_builds_all_three_configuration_concerns(container: Container) -> None:
    assert container.environment is not None
    assert container.application is not None
    assert container.scientific_settings is not None


def test_container_wires_every_infrastructure_boundary(container: Container) -> None:
    assert container.database is not None
    assert container.cache is not None
    assert container.object_storage is not None
    assert container.analytics is not None
    assert isinstance(container.scientific, ScientificEngineGateway)


def test_health_probes_cover_the_declared_dependencies(container: Container) -> None:
    names = {probe.name for probe in container.health_probes()}
    assert names == {"postgresql", "redis", "object_storage", "scientific_subsystem"}


def test_use_cases_are_resolvable(container: Container) -> None:
    assert isinstance(container.get_readiness(), GetReadiness)
    assert isinstance(container.describe_scientific_capabilities(), DescribeScientificCapabilities)


@pytest.mark.asyncio
async def test_shutdown_continues_after_a_failing_component(container: Container) -> None:
    calls: list[str] = []

    async def failing() -> None:
        calls.append("failing")
        raise RuntimeError("close failed")

    async def ok(name: str):
        async def _close() -> None:
            calls.append(name)

        return _close

    container.object_storage.close = failing  # type: ignore[method-assign]
    container.cache.close = await ok("cache")  # type: ignore[method-assign]
    container.database.close = await ok("database")  # type: ignore[method-assign]
    container.scientific.close = await ok("scientific")  # type: ignore[method-assign]

    await container.shutdown()

    assert calls == ["failing", "cache", "database", "scientific"]
