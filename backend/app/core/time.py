"""Timezone helpers.

Rules for the whole codebase:
- Every datetime that crosses a module boundary is timezone-aware.
- Storage and comparisons use UTC; presentation converts to a hospital's IANA zone.
- Never assume a default operations time zone; hospitals span several zones.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class NaiveDatetimeError(ValueError):
    """Raised when a datetime without tzinfo reaches code that requires an aware one."""


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_aware(value: datetime, *, field: str = "datetime") -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise NaiveDatetimeError(f"{field} must be timezone-aware (include a UTC offset)")
    return value


def to_utc(value: datetime) -> datetime:
    return ensure_aware(value).astimezone(UTC)


def parse_iso_aware(raw: str, *, field: str = "timestamp") -> datetime:
    """Parse an ISO-8601 string that must carry an explicit UTC offset or 'Z'."""
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field}: '{raw}' is not a valid ISO-8601 timestamp") from exc
    return ensure_aware(parsed, field=field)


def validate_timezone(name: str) -> str:
    """Validate an IANA time zone name (e.g. 'America/Chicago') and return it unchanged."""
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError(f"'{name}' is not a recognised IANA time zone") from exc
    return name


def to_zone(value: datetime, tz_name: str) -> datetime:
    return ensure_aware(value).astimezone(ZoneInfo(tz_name))
