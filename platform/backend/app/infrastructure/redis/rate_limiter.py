"""Redis-backed fixed-window rate limiting.

Used for authentication, registration, verification-resend and password-reset
requests: the operations an attacker can drive without being authenticated.

Two deliberate properties:

* The counter is incremented atomically and given a TTL on first use, so a stale
  key cannot lock an identity out forever.
* When Redis is unavailable the limiter *fails closed* by default
  (``SECURITY_RATE_LIMIT_FAIL_OPEN=false``). Losing the coordination layer must
  not silently remove a security control; a deployment may opt into fail-open,
  but that is an explicit decision.

Redis is coordination state here, never the authoritative record: nothing about
an account depends on it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int | None = None
    degraded: bool = False


class RedisRateLimiter:
    def __init__(self, client, *, fail_open: bool = False) -> None:
        self._client = client
        self._fail_open = fail_open

    async def check(self, key: str, *, limit: int, window_seconds: int) -> RateLimitDecision:
        namespaced = f"ratelimit:{key}"
        try:
            pipeline = self._client.pipeline()
            pipeline.incr(namespaced, 1)
            pipeline.ttl(namespaced)
            count, ttl = await pipeline.execute()
            if ttl is None or ttl < 0:
                await self._client.expire(namespaced, window_seconds)
                ttl = window_seconds
        except Exception as exc:  # noqa: BLE001 - infrastructure failure
            logger.warning(
                "rate_limit_backend_unavailable",
                extra={"error_type": type(exc).__name__, "fail_open": self._fail_open},
            )
            return RateLimitDecision(
                allowed=self._fail_open,
                remaining=0,
                retry_after_seconds=None if self._fail_open else window_seconds,
                degraded=True,
            )
        remaining = max(limit - int(count), 0)
        if int(count) > limit:
            return RateLimitDecision(False, 0, int(ttl))
        return RateLimitDecision(True, remaining, None)

    async def reset(self, key: str) -> None:
        """Clear a counter after a legitimate success."""
        try:
            await self._client.delete(f"ratelimit:{key}")
        except Exception:  # noqa: BLE001 - best effort only
            return


__all__ = ["RateLimitDecision", "RedisRateLimiter"]
