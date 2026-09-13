"""Ports the application layer depends on.

These are protocols: the application never imports a concrete infrastructure
module, so the domain and use cases stay free of SQLAlchemy, redis-py, boto3 and
httpx types.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Protocol, Self, runtime_checkable

from app.domain.value_objects.enums import CompressionKind, InputFormat


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


@dataclass(frozen=True, slots=True)
class StoredObject:
    """What object storage reports about a stored object.

    Used to check a transfer against what the submitter *declared*. The storage
    system is the authority on what actually arrived; the client's claims are
    only ever an expectation to be verified.
    """

    key: str
    size_bytes: int
    etag: str | None = None
    content_type: str | None = None


@runtime_checkable
class ObjectStorageService(Protocol):
    async def presign_upload(self, key: str, *, expires_seconds: int) -> str: ...
    async def presign_download(
        self, key: str, *, expires_seconds: int, filename: str | None = None
    ) -> str: ...
    async def object_exists(self, key: str) -> bool: ...
    async def stat_object(self, key: str) -> StoredObject | None: ...
    async def read_head(self, key: str, *, max_bytes: int) -> bytes: ...
    async def delete_object(self, key: str) -> None: ...
    async def move_object(self, source_key: str, destination_key: str) -> None: ...


class ScanVerdict(str, enum.Enum):
    """Outcome of a malware scan. ``UNAVAILABLE`` is never treated as clean."""

    CLEAN = "clean"
    INFECTED = "infected"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ScanResult:
    verdict: ScanVerdict
    scanner_name: str
    scanner_version: str
    detail: str | None = None


@runtime_checkable
class FileScannerService(Protocol):
    """Malware scanning boundary.

    Deliberately a port: the platform must be able to run a real scanner in
    production without any domain code knowing which one. A missing scanner
    surfaces as ``UNAVAILABLE`` and blocks acceptance rather than passing.
    """

    name: str

    async def scan(self, key: str) -> ScanResult: ...


@dataclass(frozen=True, slots=True)
class InspectedColumn:
    """A source column as it appears in the file, with no interpretation."""

    name: str
    index: int
    non_empty_sample_count: int = 0
    sampled_values: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FileInspection:
    """Structural facts about an uploaded artifact.

    Structural only. Detecting that a file is a tab-separated table with a
    ``CHROM`` column is file handling; deciding whether its coordinates are
    biologically valid is scientific work performed outside the platform's
    ordinary code, behind the scientific integration contract.
    """

    detected_format: InputFormat
    compression: CompressionKind
    columns: tuple[InspectedColumn, ...] = ()
    header_line_count: int = 0
    sampled_record_count: int = 0
    truncated: bool = True
    problems: tuple[str, ...] = ()


@runtime_checkable
class FileInspectionService(Protocol):
    """Reads a bounded prefix of an artifact to report structural facts."""

    version: str

    async def inspect(self, key: str, *, declared_filename: str) -> FileInspection: ...


@runtime_checkable
class ChecksumService(Protocol):
    """Computes a checksum over stored bytes, for transfer-integrity checks."""

    async def checksum(self, key: str, *, algorithm: str) -> str: ...
