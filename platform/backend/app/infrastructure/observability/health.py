"""Dependency probes used by the readiness use case."""

from __future__ import annotations

import time
from typing import Awaitable, Callable

from app.application.ports import DependencyProbe, DependencyStatus
from app.infrastructure.analytics.duckdb_gateway import AnalyticsGateway
from app.infrastructure.persistence.database import Database
from app.infrastructure.redis.cache import RedisCache
from app.infrastructure.storage.object_storage import S3ObjectStorage
from app.scientific.contracts import ScientificEngineGateway


async def _timed(name: str, required: bool, action: Callable[[], Awaitable[None]]) -> DependencyProbe:
    started = time.perf_counter()
    try:
        await action()
    except Exception as exc:  # noqa: BLE001 - probe failures are data, not crashes
        return DependencyProbe(
            name=name,
            status=DependencyStatus.DOWN,
            required=required,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
            # Probe detail is a stable short reason, never an infrastructure address
            # or driver stack trace.
            detail=type(exc).__name__,
        )
    return DependencyProbe(
        name=name,
        status=DependencyStatus.UP,
        required=required,
        latency_ms=round((time.perf_counter() - started) * 1000, 2),
    )


class PostgresHealthProbe:
    name = "postgresql"
    required = True

    def __init__(self, database: Database) -> None:
        self._database = database

    async def probe(self) -> DependencyProbe:
        return await _timed(self.name, self.required, self._database.ping)


class RedisHealthProbe:
    name = "redis"
    required = True

    def __init__(self, cache: RedisCache) -> None:
        self._cache = cache

    async def probe(self) -> DependencyProbe:
        return await _timed(self.name, self.required, self._cache.ping)


class ObjectStorageHealthProbe:
    name = "object_storage"
    required = True

    def __init__(self, storage: S3ObjectStorage) -> None:
        self._storage = storage

    async def probe(self) -> DependencyProbe:
        return await _timed(self.name, self.required, self._storage.ping)


class ScientificHealthProbe:
    """Scientific reachability. Required only when configured as such — the
    application shell must start without the production compute environment."""

    name = "scientific_subsystem"

    def __init__(self, gateway: ScientificEngineGateway, *, required: bool) -> None:
        self._gateway = gateway
        self.required = required

    async def probe(self) -> DependencyProbe:
        return await _timed(self.name, self.required, self._gateway.ping)


class AnalyticsHealthProbe:
    """Parquet/DuckDB engine availability. Never required for readiness: the
    analytical layer is complementary, not on the critical request path."""

    name = "analytics_engine"
    required = False

    def __init__(self, analytics: AnalyticsGateway) -> None:
        self._analytics = analytics

    async def probe(self) -> DependencyProbe:
        def open_and_close() -> None:
            with self._analytics.connection() as connection:
                connection.execute("SELECT 1")

        async def action() -> None:
            open_and_close()

        return await _timed(self.name, self.required, action)
