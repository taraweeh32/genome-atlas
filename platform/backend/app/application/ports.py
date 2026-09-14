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


@dataclass(frozen=True, slots=True)
class AnalyticalColumn:
    """A column of a materialized result surface, as the file itself declares it."""

    name: str
    data_type: str


@dataclass(frozen=True, slots=True)
class AnalyticalDescription:
    """Structural facts read back from a materialized result surface.

    These are *checks*, not interpretations: how many rows are there, and which
    columns exist with which physical types. What the columns mean scientifically
    is the engine's statement, carried in the result payload.
    """

    location: str
    row_count: int
    columns: tuple[AnalyticalColumn, ...]

    def column_schema(self) -> dict[str, str]:
        return {column.name: column.data_type for column in self.columns}


@dataclass(frozen=True, slots=True)
class AnalyticalPage:
    """A bounded window of result rows, for presentation."""

    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    total_rows: int


@runtime_checkable
class AnalyticalReadService(Protocol):
    """Reads materialized result surfaces (Parquet) through the query engine.

    Deliberately narrow. It can describe a surface and return a bounded window of
    it; it cannot filter, rank, join or aggregate. Those are separate concerns
    with their own packages, own configuration and own provenance — folding them
    in here would make every result read an unversioned scientific decision.
    """

    async def describe(self, location: str) -> AnalyticalDescription: ...

    async def read_page(
        self, location: str, *, offset: int, limit: int
    ) -> AnalyticalPage: ...


@dataclass(frozen=True, slots=True)
class AnalyticalPredicate:
    """A parameterized SQL fragment the *platform itself* generated.

    ``sql`` contains ``?`` placeholders only; every value the caller supplied
    travels in ``parameters`` and is bound by the engine. No request content ever
    becomes SQL text, so there is nothing to escape and nothing to inject.
    """

    sql: str
    parameters: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class AnalyticalQuerySpec:
    """A bounded, fully-specified analytical read.

    Every column and ordering identifier here comes from the platform's own field
    dictionary, never from a request: a caller names a *field*, and the dictionary
    decides which stored column that is. ``limit`` is always set, so there is no
    way to express an unbounded scan.
    """

    location: str
    columns: tuple[str, ...]
    limit: int
    predicate: AnalyticalPredicate | None = None
    #: ``(column, descending)`` pairs. Always non-empty in practice, because a
    #: page without a total ordering is not reproducible.
    order_by: tuple[tuple[str, bool], ...] = ()
    #: Keyset continuation from a previous page's last row. Also parameterized.
    keyset: AnalyticalPredicate | None = None
    #: Totals are opt-in: counting a very large surface is itself expensive, and a
    #: fabricated total is worse than an absent one.
    count_total: bool = False


@dataclass(frozen=True, slots=True)
class AnalyticalQueryResult:
    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    #: ``None`` means "not counted". Never conflated with zero.
    total_rows: int | None
    #: True when the engine stopped at ``limit`` and more rows match.
    truncated: bool
    duration_ms: int


@dataclass(frozen=True, slots=True)
class AnalyticalDistinctValue:
    value: object
    #: ``None`` when counts were not requested, never zero as a stand-in.
    occurrence_count: int | None = None


@dataclass(frozen=True, slots=True)
class AnalyticalDistinctValues:
    column: str
    values: tuple[AnalyticalDistinctValue, ...]
    truncated: bool


@runtime_checkable
class AnalyticalQueryService(Protocol):
    """Filtered, ordered, bounded reads over materialized result surfaces.

    Separate from ``AnalyticalReadService`` on purpose: that port reads a surface
    as stored, while this one runs a *validated, versioned* filter against it. It
    still interprets nothing — it evaluates predicates the platform compiled from
    a canonical expression and returns the rows as stored.
    """

    async def execute(self, spec: AnalyticalQuerySpec) -> AnalyticalQueryResult: ...

    async def distinct_values(
        self,
        location: str,
        *,
        column: str,
        search: str | None,
        limit: int,
        predicate: AnalyticalPredicate | None = None,
        with_counts: bool = False,
    ) -> AnalyticalDistinctValues: ...
