"""The clock, behind a port.

Time is an injected dependency so lifetimes, lockouts and expiries are testable
without sleeping and without monkeypatching module globals.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def in_seconds(self, seconds: float) -> datetime:
        return self.now() + timedelta(seconds=seconds)


class FixedClock:
    """Test double. Not used by production wiring."""

    def __init__(self, moment: datetime) -> None:
        self._moment = moment

    def now(self) -> datetime:
        return self._moment

    def in_seconds(self, seconds: float) -> datetime:
        return self._moment + timedelta(seconds=seconds)

    def advance(self, seconds: float) -> None:
        self._moment += timedelta(seconds=seconds)


__all__ = ["FixedClock", "SystemClock"]
