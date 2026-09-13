"""S3-compatible object storage boundary.

Large genomic files, derived artifacts, exports and reports live here — never in
PostgreSQL. Package 1 establishes configuration, the client boundary, presigning
and a connectivity probe. The upload/quarantine/validation lifecycle is a later
package.
"""

from __future__ import annotations

import aioboto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.environment import ObjectStorageSettings
from app.core.logging import get_logger
from app.domain.errors import InfrastructureError

logger = get_logger(__name__)


class S3ObjectStorage:
    def __init__(self, settings: ObjectStorageSettings) -> None:
        self._settings = settings
        self._session: aioboto3.Session | None = None

    async def connect(self) -> None:
        if self._session is None:
            self._session = aioboto3.Session()
            logger.info("object storage session created", extra={"bucket": self._settings.bucket})

    async def close(self) -> None:
        self._session = None

    def _client(self):  # type: ignore[no-untyped-def] - aioboto3 returns a context manager
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
        return self._session.client("s3", **kwargs)  # type: ignore[union-attr]

    async def presign_upload(self, key: str, *, expires_seconds: int) -> str:
        return await self._presign("put_object", key, expires_seconds)

    async def presign_download(self, key: str, *, expires_seconds: int) -> str:
        return await self._presign("get_object", key, expires_seconds)

    async def _presign(self, operation: str, key: str, expires_seconds: int) -> str:
        try:
            async with self._client() as client:
                url: str = await client.generate_presigned_url(
                    operation,
                    Params={"Bucket": self._settings.bucket, "Key": key},
                    ExpiresIn=expires_seconds,
                )
                return url
        except (BotoCoreError, ClientError) as exc:
            raise InfrastructureError("object storage presign failed") from exc

    async def object_exists(self, key: str) -> bool:
        try:
            async with self._client() as client:
                await client.head_object(Bucket=self._settings.bucket, Key=key)
                return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise InfrastructureError("object storage head failed") from exc
        except BotoCoreError as exc:
            raise InfrastructureError("object storage head failed") from exc

    async def ping(self) -> None:
        """Bucket-level connectivity probe."""
        try:
            async with self._client() as client:
                await client.head_bucket(Bucket=self._settings.bucket)
        except (BotoCoreError, ClientError) as exc:
            raise InfrastructureError("object storage bucket unavailable") from exc
