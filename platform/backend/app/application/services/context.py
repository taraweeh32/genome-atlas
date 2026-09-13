"""Request context carried from transport into the application layer.

It holds *observational* facts about the caller (correlation id, hashed address,
agent summary, channel) — never a security decision and never an identity the
client asserted. The authenticated identity arrives separately as an
``ActorContext`` resolved from the session.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.value_objects.enums import AuditChannel


@dataclass(frozen=True, slots=True)
class RequestContext:
    correlation_id: str | None = None
    #: Keyed hash of the client address; the raw address is never persisted.
    ip_hash: str | None = None
    user_agent_summary: str | None = None
    channel: AuditChannel = AuditChannel.API
    #: Stable, non-secret key for rate limiting by origin.
    rate_limit_key: str | None = None

    @classmethod
    def system(
        cls,
        *,
        correlation_id: str | None = None,
        channel: AuditChannel = AuditChannel.SYSTEM,
    ) -> RequestContext:
        """Context for work with no HTTP caller: workers, scheduler, maintenance.

        There is no address and no agent to observe, and deliberately no identity:
        a background process is never an authenticated user.
        """
        return cls(correlation_id=correlation_id, channel=channel)


__all__ = ["RequestContext"]
