"""S3-compatible object storage boundary.

Large genomic files, derived artifacts, exports and reports live here — never in
PostgreSQL. PostgreSQL owns the *reference* (key, checksum, lifecycle); this
module owns the transfer.

Two rules are visible in the method set:

* A presigned URL is a short-lived transfer grant, never a capability to make an
  artifact usable. Usability is decided by the upload/validation lifecycle in the
  application layer, against rows in the database.
* The storage system is the authority on what actually arrived. ``stat_object``
  exists so a submitter's declared size can be *checked* rather than trusted.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager
from typing import Any
from urllib.parse import quote

import aioboto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.application.ports import StoredObject
from app.core.environment import ObjectStorageSettings
from app.core.logging import get_logger
from app.domain.errors import InfrastructureError

logger = get_logger(__name__)

#: Codes every S3-compatible implementation uses for "there is no such object".
_MISSING_CODES = frozenset({"404", "NoSuchKey", "NotFound"})

#: Streaming chunk size for checksum computation. Bounded so a multi-gigabyte
#: object is never materialised in memory.
STREAM_CHUNK_BYTES = 1024 * 1024


class S3ObjectStorage:
    def __init__(self, settings: ObjectStorageSettings) -> None:
        self._settings = settings
        self._session: aioboto3.Session | None = None

    @property
    def bucket(self) -> str:
        return self._settings.bucket

    async def connect(self) -> None:
        if self._session is None:
            self._session = aioboto3.Session()
            logger.info("object storage session created", extra={"bucket": self._settings.bucket})

    async def close(self) -> None:
        self._session = None

    def _client(self) -> AbstractAsyncContextManager[Any]:
        """aioboto3 ships no type information, so the client is opaque here.

        The looseness stops at this method: every caller below is fully typed.
        """
        if self._session is None:
            raise InfrastructureError("object storage is not connected")
        kwargs: dict[str, object] = {
            "region_name": self._settings.region,
            "config": Config(
                s3={"addressing_style": "path" if self._settings.force_path_style else "auto"},
                signature_version="s3v4",
            ),
        }
        if self._settings.endpoint_url:
            kwargs["endpoint_url"] = self._settings.endpoint_url
        if self._settings.access_key_id and self._settings.secret_access_key:
            kwargs["aws_access_key_id"] = self._settings.access_key_id
            kwargs["aws_secret_access_key"] = self._settings.secret_access_key
        client: AbstractAsyncContextManager[Any] = self._session.client("s3", **kwargs)
        return client

    # -- transfer grants --------------------------------------------------- #

    async def presign_upload(self, key: str, *, expires_seconds: int) -> str:
        return await self._presign("put_object", key, expires_seconds)

    async def presign_download(
        self, key: str, *, expires_seconds: int, filename: str | None = None
    ) -> str:
        params: dict[str, Any] = {"Bucket": self._settings.bucket, "Key": key}
        if filename:
            # The stored key is opaque, so the original display name is attached
            # to the response rather than encoded into the key.
            params["ResponseContentDisposition"] = (
                f"attachment; filename*=UTF-8''{quote(filename)}"
            )
        return await self._presign("get_object", key, expires_seconds, params=params)

    async def _presign(
        self,
        operation: str,
        key: str,
        expires_seconds: int,
        *,
        params: dict[str, Any] | None = None,
    ) -> str:
        try:
            async with self._client() as client:
                url: str = await client.generate_presigned_url(
                    operation,
                    Params=params or {"Bucket": self._settings.bucket, "Key": key},
                    ExpiresIn=expires_seconds,
                )
                return url
        except (BotoCoreError, ClientError) as exc:
            raise InfrastructureError("object storage presign failed") from exc

    # -- reads ------------------------------------------------------------- #

    async def object_exists(self, key: str) -> bool:
        return await self.stat_object(key) is not None

    async def stat_object(self, key: str) -> StoredObject | None:
        """What actually arrived, or ``None`` when nothing did."""
        try:
            async with self._client() as client:
                head = await client.head_object(Bucket=self._settings.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _MISSING_CODES:
                return None
            raise InfrastructureError("object storage head failed") from exc
        except BotoCoreError as exc:
            raise InfrastructureError("object storage head failed") from exc
        etag = head.get("ETag")
        return StoredObject(
            key=key,
            size_bytes=int(head.get("ContentLength") or 0),
            etag=etag.strip('"') if isinstance(etag, str) else None,
            content_type=head.get("ContentType"),
        )

    async def read_head(self, key: str, *, max_bytes: int) -> bytes:
        """Read a bounded prefix. Inspection never loads a whole genomic file."""
        if max_bytes <= 0:
            return b""
        try:
            async with self._client() as client:
                response = await client.get_object(
                    Bucket=self._settings.bucket,
                    Key=key,
                    Range=f"bytes=0-{max_bytes - 1}",
                )
                body = response["Body"]
                try:
                    data: bytes = await body.read()
                finally:
                    close = getattr(body, "close", None)
                    if close is not None:
                        result = close()
                        if hasattr(result, "__await__"):
                            await result
                return data
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in _MISSING_CODES:
                raise InfrastructureError("stored object is missing") from exc
            raise InfrastructureError("object storage read failed") from exc
        except BotoCoreError as exc:
            raise InfrastructureError("object storage read failed") from exc

    async def stream_object(
        self, key: str, *, chunk_size: int = STREAM_CHUNK_BYTES
    ) -> AsyncIterator[bytes]:
        """Yield the object in bounded chunks, for checksum computation."""
        try:
            async with self._client() as client:
                response = await client.get_object(Bucket=self._settings.bucket, Key=key)
                body = response["Body"]
                while True:
                    chunk: bytes = await body.read(chunk_size)
                    if not chunk:
                        break
                    yield chunk
        except (BotoCoreError, ClientError) as exc:
            raise InfrastructureError("object storage stream failed") from exc

    # -- mutations --------------------------------------------------------- #

    async def delete_object(self, key: str) -> None:
        try:
            async with self._client() as client:
                await client.delete_object(Bucket=self._settings.bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise InfrastructureError("object storage delete failed") from exc

    async def move_object(self, source_key: str, destination_key: str) -> None:
        """Copy-then-delete, used to move a refused object into quarantine.

        The copy is confirmed before the source is removed, so a failure leaves
        the object where it was instead of losing it.
        """
        try:
            async with self._client() as client:
                await client.copy_object(
                    Bucket=self._settings.bucket,
                    Key=destination_key,
                    CopySource={"Bucket": self._settings.bucket, "Key": source_key},
                )
                await client.delete_object(Bucket=self._settings.bucket, Key=source_key)
        except (BotoCoreError, ClientError) as exc:
            raise InfrastructureError("object storage move failed") from exc

    async def ping(self) -> None:
        """Bucket-level connectivity probe."""
        try:
            async with self._client() as client:
                await client.head_bucket(Bucket=self._settings.bucket)
        except (BotoCoreError, ClientError) as exc:
            raise InfrastructureError("object storage bucket unavailable") from exc


__all__ = ["STREAM_CHUNK_BYTES", "S3ObjectStorage"]
