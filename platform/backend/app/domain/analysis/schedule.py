"""Schedule expressions, time-zone aware next-run computation, missed firings.

Deliberately a small, total, explicitly documented expression language rather
than a full cron implementation: every supported form is validated up front and
computed with the standard library's IANA time-zone database, so daylight-saving
transitions are handled by ``zoneinfo`` and not by hand-rolled arithmetic.

Supported expressions
---------------------
* ``every:<n><unit>`` — fixed interval, units ``m`` (minutes), ``h`` (hours),
  ``d`` (days). Example ``every:30m``.
* ``daily:<HH:MM>`` — once per local day at that wall-clock time.
* ``weekly:<dow>:<HH:MM>`` — ``dow`` is ``mon``..``sun``, local wall clock.
* ``monthly:<day>:<HH:MM>`` — ``day`` 1..28 (higher days are rejected rather
  than silently shifted, because "the 31st" has no meaning in February).

All stored timestamps remain UTC; the time zone only decides which UTC instant a
local wall-clock rule refers to.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.errors import ValidationError
from app.domain.value_objects.enums import MissedSchedulePolicy

_INTERVAL = re.compile(r"^every:(\d{1,4})([mhd])$")
_DAILY = re.compile(r"^daily:(\d{2}):(\d{2})$")
_WEEKLY = re.compile(r"^weekly:(mon|tue|wed|thu|fri|sat|sun):(\d{2}):(\d{2})$")
_MONTHLY = re.compile(r"^monthly:(\d{1,2}):(\d{2}):(\d{2})$")

_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}

#: A floor on interval schedules. Without it a single schedule could saturate
#: every queue on the platform.
MIN_INTERVAL_MINUTES = 5

SCHEDULE_KINDS = ("interval", "daily", "weekly", "monthly")


def resolve_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValidationError(
            "unknown time zone", details={"field": "timezone", "value": name}
        ) from exc


@dataclass(frozen=True, slots=True)
class ScheduleExpression:
    """A parsed, validated recurrence rule."""

    kind: str
    raw: str
    interval: timedelta | None = None
    hour: int = 0
    minute: int = 0
    weekday: int | None = None
    day_of_month: int | None = None

    @classmethod
    def parse(cls, raw: str) -> ScheduleExpression:
        value = (raw or "").strip().lower()
        if match := _INTERVAL.match(value):
            amount, unit = int(match.group(1)), match.group(2)
            minutes = {"m": 1, "h": 60, "d": 1440}[unit] * amount
            if minutes < MIN_INTERVAL_MINUTES:
                raise ValidationError(
                    f"interval must be at least {MIN_INTERVAL_MINUTES} minutes",
                    details={"field": "schedule_expression", "value": raw},
                )
            return cls(kind="interval", raw=value, interval=timedelta(minutes=minutes))
        if match := _DAILY.match(value):
            hour, minute = _time_of_day(match.group(1), match.group(2), raw)
            return cls(kind="daily", raw=value, hour=hour, minute=minute)
        if match := _WEEKLY.match(value):
            hour, minute = _time_of_day(match.group(2), match.group(3), raw)
            return cls(
                kind="weekly",
                raw=value,
                hour=hour,
                minute=minute,
                weekday=_WEEKDAYS[match.group(1)],
            )
        if match := _MONTHLY.match(value):
            day = int(match.group(1))
            if not 1 <= day <= 28:
                raise ValidationError(
                    "monthly schedules accept day 1-28 so every month has that day",
                    details={"field": "schedule_expression", "value": raw},
                )
            hour, minute = _time_of_day(match.group(2), match.group(3), raw)
            return cls(
                kind="monthly", raw=value, hour=hour, minute=minute, day_of_month=day
            )
        raise ValidationError(
            "unsupported schedule expression",
            details={
                "field": "schedule_expression",
                "value": raw,
                "supported": [
                    "every:<n>m|h|d",
                    "daily:HH:MM",
                    "weekly:mon..sun:HH:MM",
                    "monthly:1-28:HH:MM",
                ],
            },
        )

    def next_after(self, moment: datetime, *, timezone_name: str) -> datetime:
        """The first firing strictly after ``moment``, returned in UTC."""
        zone = resolve_timezone(timezone_name)
        reference = _as_utc(moment)
        if self.kind == "interval":
            assert self.interval is not None
            return reference + self.interval
        local = reference.astimezone(zone)
        candidate = local.replace(
            hour=self.hour, minute=self.minute, second=0, microsecond=0
        )
        if self.kind == "daily":
            if candidate <= local:
                candidate = candidate + timedelta(days=1)
        elif self.kind == "weekly":
            assert self.weekday is not None
            delta = (self.weekday - candidate.weekday()) % 7
            candidate = candidate + timedelta(days=delta)
            if candidate <= local:
                candidate = candidate + timedelta(days=7)
        elif self.kind == "monthly":
            assert self.day_of_month is not None
            candidate = candidate.replace(day=self.day_of_month)
            if candidate <= local:
                year = candidate.year + (1 if candidate.month == 12 else 0)
                month = 1 if candidate.month == 12 else candidate.month + 1
                candidate = candidate.replace(year=year, month=month)
        # Re-normalize through the zone: a wall-clock time that does not exist on
        # a DST spring-forward day resolves to the following valid instant.
        return candidate.astimezone(UTC)


def _time_of_day(hour_raw: str, minute_raw: str, raw: str) -> tuple[int, int]:
    hour, minute = int(hour_raw), int(minute_raw)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValidationError(
            "schedule time must be a valid 24-hour local time",
            details={"field": "schedule_expression", "value": raw},
        )
    return hour, minute


def _as_utc(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        raise ValidationError(
            "schedule computation requires an aware timestamp",
            details={"field": "moment"},
        )
    return moment.astimezone(UTC)


#: A slot reached within this many seconds counts as an on-time firing rather
#: than a missed one; scheduler ticks are never perfectly punctual.
ON_TIME_GRACE_SECONDS = 300


@dataclass(frozen=True, slots=True)
class MissedFirings:
    """What to do about firings whose slot has already passed."""

    due: tuple[datetime, ...]
    skipped: tuple[datetime, ...]
    next_execution_at: datetime | None


def resolve_missed(
    *,
    expression: ScheduleExpression,
    timezone_name: str,
    scheduled_for: datetime | None,
    now: datetime,
    policy: MissedSchedulePolicy,
    catch_up_limit: int,
) -> MissedFirings:
    """Decide which past slots still run, bounded by ``catch_up_limit``.

    A schedule that was disabled or a platform that was down must not produce an
    unbounded burst of executions when it comes back: ``skip`` runs nothing,
    ``run_once_after_recovery`` runs exactly the latest missed slot, and
    ``catch_up`` runs at most ``catch_up_limit`` of them.
    """
    now = _as_utc(now)
    if scheduled_for is None:
        return MissedFirings(
            due=(),
            skipped=(),
            next_execution_at=expression.next_after(now, timezone_name=timezone_name),
        )
    slots: list[datetime] = []
    cursor = _as_utc(scheduled_for)
    # Bound the walk so a schedule untouched for years cannot spin here.
    horizon = max(catch_up_limit, 1) + 1000
    while cursor <= now and len(slots) <= horizon:
        slots.append(cursor)
        cursor = expression.next_after(cursor, timezone_name=timezone_name)
    next_execution_at = cursor
    if not slots:
        return MissedFirings(due=(), skipped=(), next_execution_at=next_execution_at)
    # A slot the scheduler reached within the grace window is *punctual*: it is
    # the schedule running normally, so the missed-slot policy does not apply to
    # it. Only genuinely late slots are subject to the policy.
    grace = timedelta(seconds=ON_TIME_GRACE_SECONDS)
    punctual = [slot for slot in slots if now - slot <= grace]
    late = [slot for slot in slots if now - slot > grace]
    due: list[datetime] = []
    skipped: list[datetime] = []
    if punctual:
        # Several punctual slots at once still mean one run: the newest.
        due.append(punctual[-1])
        skipped.extend(punctual[:-1])
    if late:
        if policy is MissedSchedulePolicy.SKIP:
            skipped.extend(late)
        elif policy is MissedSchedulePolicy.RUN_ONCE_AFTER_RECOVERY:
            skipped.extend(late[:-1])
            due.append(late[-1])
        else:
            limit = max(1, catch_up_limit)
            skipped.extend(late[: max(0, len(late) - limit)])
            due.extend(late[-limit:])
    return MissedFirings(
        due=tuple(sorted(due)),
        skipped=tuple(sorted(skipped)),
        next_execution_at=next_execution_at,
    )


__all__ = [
    "MIN_INTERVAL_MINUTES",
    "SCHEDULE_KINDS",
    "ON_TIME_GRACE_SECONDS",
    "MissedFirings",
    "ScheduleExpression",
    "resolve_missed",
    "resolve_timezone",
]
