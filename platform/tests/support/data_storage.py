"""In-memory object storage, scanner, inspector and checksum doubles.

These stand in for S3-compatible storage and the scanning/inspection boundary so
the upload, verification and import use cases can be exercised end to end
without external services. They are honest about the distinctions the platform
refuses to blur:

* a presigned URL is just an opaque string here — possessing one still grants
  nothing, because authorization is re-evaluated on every operation;
* a scanner that cannot answer returns ``UNAVAILABLE``, never ``CLEAN``;
* the inspector reports structural facts only, and never judges scientific
  validity.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from app.application.ports import (
    FileInspection,
    InspectedColumn,
    ScanResult,
    ScanVerdict,
    StoredObject,
)
from app.domain.data.formats import detect_format
from app.domain.value_objects.enums import InputFormat


@dataclass
class MemoryObjectStorage:
    """Keyed bytes, plus a record of every presign and mutation."""

    objects: dict[str, bytes] = field(default_factory=dict)
    presigned_uploads: list[str] = field(default_factory=list)
    presigned_downloads: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    moved: list[tuple[str, str]] = field(default_factory=list)

    def put(self, key: str, payload: bytes) -> None:
        """Simulates the client transferring bytes with the presigned URL."""
        self.objects[key] = payload

    async def presign_upload(self, key: str, *, expires_seconds: int) -> str:
        self.presigned_uploads.append(key)
        return f"https://storage.invalid/{key}?upload&expires={expires_seconds}"

    async def presign_download(
        self, key: str, *, expires_seconds: int, filename: str | None = None
    ) -> str:
        self.presigned_downloads.append(key)
        return f"https://storage.invalid/{key}?download&expires={expires_seconds}"

    async def object_exists(self, key: str) -> bool:
        return key in self.objects

    async def stat_object(self, key: str) -> StoredObject | None:
        payload = self.objects.get(key)
        if payload is None:
            return None
        return StoredObject(key=key, size_bytes=len(payload), etag=None, content_type=None)

    async def read_head(self, key: str, *, max_bytes: int) -> bytes:
        return self.objects.get(key, b"")[:max_bytes]

    async def delete_object(self, key: str) -> None:
        self.deleted.append(key)
        self.objects.pop(key, None)

    async def move_object(self, source_key: str, destination_key: str) -> None:
        self.moved.append((source_key, destination_key))
        payload = self.objects.pop(source_key, None)
        if payload is not None:
            self.objects[destination_key] = payload


@dataclass
class StubScanner:
    """Returns a configured verdict, so every branch is testable."""

    verdict: ScanVerdict = ScanVerdict.CLEAN
    name: str = "stub-scanner"
    scanner_version: str = "test"
    detail: str | None = None
    scanned: list[str] = field(default_factory=list)

    async def scan(self, key: str) -> ScanResult:
        self.scanned.append(key)
        return ScanResult(
            verdict=self.verdict,
            scanner_name=self.name,
            scanner_version=self.scanner_version,
            detail=self.detail,
        )


@dataclass
class StubInspector:
    """Derives columns from the stored prefix; never interprets the values."""

    storage: MemoryObjectStorage
    version: str = "test"
    max_bytes: int = 65536

    async def inspect(self, key: str, *, declared_filename: str) -> FileInspection:
        head = await self.storage.read_head(key, max_bytes=self.max_bytes)
        payload = head.decode("utf-8", errors="replace")
        detection = detect_format(head, filename=declared_filename)
        detected = detection.format
        compression = detection.compression
        lines = [line for line in payload.splitlines() if line.strip()]
        columns: tuple[InspectedColumn, ...] = ()
        if lines and detected in (InputFormat.CSV, InputFormat.TSV):
            delimiter = "," if detected is InputFormat.CSV else "\t"
            names = lines[0].split(delimiter)
            rows = [line.split(delimiter) for line in lines[1:]]
            columns = tuple(
                InspectedColumn(
                    name=name.strip(),
                    index=index,
                    non_empty_sample_count=sum(
                        1
                        for row in rows
                        if index < len(row) and row[index].strip() != ""
                    ),
                    sampled_values=tuple(
                        row[index] for row in rows[:5] if index < len(row)
                    ),
                )
                for index, name in enumerate(names)
            )
        return FileInspection(
            detected_format=detected,
            compression=compression,
            columns=columns,
            header_line_count=1 if columns else 0,
            sampled_record_count=max(len(lines) - 1, 0),
            truncated=False,
        )


@dataclass
class StubChecksums:
    """Real hashing over the stored bytes: a mismatch must be a real mismatch."""

    storage: MemoryObjectStorage

    async def checksum(self, key: str, *, algorithm: str) -> str:
        payload = self.storage.objects.get(key, b"")
        digest = hashlib.new(algorithm.replace("-", ""))
        digest.update(payload)
        return digest.hexdigest()


def checksum_of(payload: bytes, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm.replace("-", ""))
    digest.update(payload)
    return digest.hexdigest()


__all__ = [
    "MemoryObjectStorage",
    "StubChecksums",
    "StubInspector",
    "StubScanner",
    "checksum_of",
]
