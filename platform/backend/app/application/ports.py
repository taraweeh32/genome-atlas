"""Ports the application layer depends on.

These are protocols: the application never imports a concrete infrastructure
module, so the domain and use cases stay free of SQLAlchemy, redis-py, boto3 and
httpx types.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Protocol, Self, runtime_checkable


class DependencyStatus(str, enum.Enum):
    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"
    NOT_CONFIGURED = "not_configured"


@dataclass(frozen=True, slots=True)
class DependencyProbe:
    """Result of checking one dependency for readiness reporting."""

    name: str
    status: DependencyStatus
    required: bool
    latency_ms: float | None = None
    detail: str | None = None

    @property
    def blocks_readiness(self) -> bool:
        return self.required and self.status is DependencyStatus.DOWN


@runtime_checkable
class HealthProbe(Protocol):
    """Anything that can report its own availability."""

    name: str
    required: bool

    async def probe(self) -> DependencyProbe: ...


@runtime_checkable
class UnitOfWork(Protocol):
    """Transaction boundary owned by the application layer."""

    async def __aenter__(self) -> Self: ...
    async def __aexit__(self, *exc: object) -> None: ...
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


@runtime_checkable
class CacheService(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None: ...
    async def delete(self, key: str) -> None: ...


@runtime_checkable
class ObjectStorageService(Protocol):
    async def presign_upload(self, key: str, *, expires_seconds: int) -> str: ...
    async def presign_download(self, key: str, *, expires_seconds: int) -> str: ...
    async def object_exists(self, key: str) -> bool: ...
