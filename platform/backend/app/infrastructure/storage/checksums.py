"""Checksum computation over stored bytes.

Used for one purpose: checking that what arrived in storage matches what the
submitter declared. A checksum here is a *transfer integrity* fact, not a
scientific identity — variant identity is defined by genome build, coordinates
and alleles, not by a file digest.

Objects are streamed in bounded chunks, so a multi-gigabyte upload is never
loaded into memory.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from typing import Protocol

from app.domain.errors import ValidationError

#: Algorithms the platform will compute. ``crc32c`` is a storage-provider
#: checksum rather than a hash and is deliberately not offered here.
SUPPORTED_ALGORITHMS = frozenset({"sha256", "sha512", "md5"})


class _ObjectStreamer(Protocol):
    def stream_object(self, key: str, *, chunk_size: int = ...) -> AsyncIterator[bytes]: ...


class StreamingChecksumService:
    def __init__(self, storage: _ObjectStreamer) -> None:
        self._storage = storage

    async def checksum(self, key: str, *, algorithm: str) -> str:
        name = algorithm.lower()
        if name not in SUPPORTED_ALGORITHMS:
            raise ValidationError(
                "unsupported checksum algorithm",
                details={
                    "field": "checksum_algorithm",
                    "supported": sorted(SUPPORTED_ALGORITHMS),
                },
            )
        digest = hashlib.new(name)
        async for chunk in self._storage.stream_object(key):
            digest.update(chunk)
        return digest.hexdigest()


__all__ = ["SUPPORTED_ALGORITHMS", "StreamingChecksumService"]
