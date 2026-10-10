"""Exact time-boundary helpers for hospital-local rules (pure, DST-safe).

Coverage blocks and baseline hours are defined in hospital-local wall time, but all
computation runs on UTC instants. These helpers find every instant in a UTC interval at
which a local wall-clock rule could change value:

- each occurrence of a local time-of-day (both occurrences in a repeated fall-back hour;
  none in a skipped spring-forward hour), and
- every UTC-offset transition (where local time jumps).

Callers evaluate the rule at segment starts, so a superset of change points is harmless,
and nothing depends on sampling a grid.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, time, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo

_SCAN_STEP = timedelta(minutes=15)


@lru_cache(maxsize=64)
def zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def local(moment: datetime, tz_name: str) -> datetime:
    return moment.astimezone(zone(tz_name))


def zone_transitions(tz_name: str, start: datetime, end: datetime) -> list[datetime]:
    """UTC instants in (start, end] where the zone's UTC offset changes, to the second."""
    tz = zone(tz_name)
    found: list[datetime] = []
    cursor = start
    offset = cursor.astimezone(tz).utcoffset()
    while cursor < end:
        nxt = min(cursor + _SCAN_STEP, end)
        nxt_offset = nxt.astimezone(tz).utcoffset()
        if nxt_offset != offset:
            lo, hi = cursor, nxt  # offset(lo) == offset, offset(hi) != offset
            while (hi - lo) > timedelta(seconds=1):
                mid = lo + (hi - lo) / 2
                if mid.astimezone(tz).utcoffset() == offset:
                    lo = mid
                else:
                    hi = mid
            found.append(hi.replace(microsecond=0) if hi.microsecond else hi)
            offset = nxt_offset
        cursor = nxt
    return found


def local_time_crossings(
    tz_name: str, start: datetime, end: datetime, times: Iterable[time]
) -> list[datetime]:
    """UTC instants in (start, end) where local wall time equals one of ``times``.

    Uses both folds so a repeated local time (DST fall-back) yields two instants, and
    drops non-existent local times (DST spring-forward); the transition instant itself is
    returned by ``zone_transitions``.
    """
    tz = zone(tz_name)
    wanted = sorted(set(times))
    first = start.astimezone(tz).date() - timedelta(days=1)
    last = end.astimezone(tz).date() + timedelta(days=1)
    found: set[datetime] = set()
    day = first
    while day <= last:
        for tod in wanted:
            for fold in (0, 1):
                wall = datetime.combine(day, tod, tzinfo=tz).replace(fold=fold)
                instant = wall.astimezone(UTC)
                back = instant.astimezone(tz)
                if back.replace(tzinfo=None) != wall.replace(tzinfo=None):
                    continue  # this wall time does not exist (spring-forward gap)
                if start < instant < end:
                    found.add(instant)
        day += timedelta(days=1)
    return sorted(found)


def local_hour_boundaries(tz_name: str, start: datetime, end: datetime) -> list[datetime]:
    return local_time_crossings(tz_name, start, end, (time(h) for h in range(24)))


def time_in_block(tod: time, start: time, end: time) -> bool:
    """Half-open [start, end) on a 24h clock; start > end wraps midnight; start == end = all day."""
    if start == end:
        return True
    if start < end:
        return start <= tod < end
    return tod >= start or tod < end


def is_weekend(moment_local: datetime) -> bool:
    return moment_local.weekday() >= 5


def fmt_local(moment: datetime, tz_name: str, seconds: bool = False) -> str:
    """'19:00 EDT' — for explanations. Structured timestamps are always returned alongside."""
    loc = local(moment, tz_name)
    return loc.strftime("%H:%M:%S %Z" if seconds or loc.second else "%H:%M %Z")


def fmt_local_datetime(moment: datetime, tz_name: str) -> str:
    """'Sep 12 07:00 CDT' — for explanations about other days."""
    return local(moment, tz_name).strftime("%b %d %H:%M %Z")
