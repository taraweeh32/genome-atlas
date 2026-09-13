"""Redis: cache, ephemeral state and coordination.

Redis is never the authoritative transactional store. Failures are explicit —
this adapter does not silently swallow them into a false cache miss.
"""

from __future__ import annotations

import redis.asyncio as redis
from redis.exceptions import RedisError

from app.core.environment import RedisSettings
from app.core.logging import get_logger
from app.domain.errors import InfrastructureError

logger = get_logger(__name__)


class RedisCache:
    def __init__(self, settings: RedisSettings) -> None:
        self._settings = settings
        self._client: redis.Redis | None = None

    async def connect(self) -> None:
        if self._client is not None:
            return
        self._client = redis.from_url(
            self._settings.url,
            decode_responses=True,
            socket_timeout=self._settings.socket_timeout_seconds,
        )
        logger.info("redis client created")

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("redis client closed")

    def _require(self) -> redis.Redis:
        if self._client is None:
            raise InfrastructureError("redis is not connected")
        return self._client

    async def get(self, key: str) -> str | None:
        try:
            raw = await self._require().get(key)
        except RedisError as exc:
            raise InfrastructureError("redis read failed") from exc
        if raw is None:
            return None
        # decode_responses may be off depending on client construction; normalise.
        return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

    async def set(self, key: str, value: str, *, ttl_seconds: int | None = None) -> None:
        try:
            await self._require().set(key, value, ex=ttl_seconds)
        except RedisError as exc:
            raise InfrastructureError("redis write failed") from exc

    async def delete(self, key: str) -> None:
        try:
            await self._require().delete(key)
        except RedisError as exc:
            raise InfrastructureError("redis delete failed") from exc

    def raw_client(self) -> redis.Redis:
        """Direct client access for coordination primitives (rate limiting).

        Exposed deliberately and narrowly: counters and locks need pipelines and
        TTL semantics that a generic get/set cache interface cannot express.
        """
        return self._require()

    async def ping(self) -> None:
        try:
            await self._require().ping()
        except RedisError as exc:
            raise InfrastructureError("redis ping failed") from exc
