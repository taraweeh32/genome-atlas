"""Readiness aggregation: liveness is not readiness."""

from __future__ import annotations

from app.application.ports import DependencyProbe, DependencyStatus
from app.application.use_cases.get_readiness import GetReadiness


class StubProbe:
    def __init__(self, name: str, status: DependencyStatus, *, required: bool) -> None:
        self.name = name
        self.required = required
        self._status = status

    async def probe(self) -> DependencyProbe:
        return DependencyProbe(name=self.name, status=self._status, required=self.required)


class ExplodingProbe:
    name = "exploding"

    def __init__(self, *, required: bool) -> None:
        self.required = required

    async def probe(self) -> DependencyProbe:
        raise RuntimeError("probe blew up")


async def test_all_required_dependencies_up_is_ready() -> None:
    use_case = GetReadiness(
        (
            StubProbe("postgresql", DependencyStatus.UP, required=True),
            StubProbe("redis", DependencyStatus.UP, required=True),
        )
    )
    report = await use_case.execute()
    assert report.ready is True
    assert {probe.name for probe in report.dependencies} == {"postgresql", "redis"}


async def test_required_dependency_down_blocks_readiness() -> None:
    use_case = GetReadiness(
        (
            StubProbe("postgresql", DependencyStatus.DOWN, required=True),
            StubProbe("redis", DependencyStatus.UP, required=True),
        )
    )
    report = await use_case.execute()
    assert report.ready is False


async def test_optional_dependency_down_does_not_block_readiness() -> None:
    use_case = GetReadiness(
        (
            StubProbe("postgresql", DependencyStatus.UP, required=True),
            StubProbe("scientific_subsystem", DependencyStatus.DOWN, required=False),
        )
    )
    report = await use_case.execute()
    assert report.ready is True


async def test_raising_probe_is_reported_as_down_not_propagated() -> None:
    use_case = GetReadiness((ExplodingProbe(required=True),))
    report = await use_case.execute()
    assert report.ready is False
    assert report.dependencies[0].status is DependencyStatus.DOWN
    # The raised message must not be echoed into the report.
    assert report.dependencies[0].detail == "probe raised an unexpected error"


async def test_raising_optional_probe_does_not_block_readiness() -> None:
    use_case = GetReadiness((ExplodingProbe(required=False),))
    report = await use_case.execute()
    assert report.ready is True


async def test_report_is_timestamped() -> None:
    report = await GetReadiness(()).execute()
    assert report.checked_at.tzinfo is not None
    assert report.ready is True
