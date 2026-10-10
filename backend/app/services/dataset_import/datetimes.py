"""Timestamp and time-of-day parsing for roster/reference files.

Events must always carry a UTC offset (enforced in the event normalizer). Roster files
are more varied (the brief displays shifts as "08:00-20:00" and roster times as
"03-17 07:00"), so values without an offset are interpreted in a zone chosen by an
explicit, reported policy:

1. a zone label in the column header (``shift_et``) mapped via ``timezone_labels``
2. ``datetimes.naive_timezone`` from the mapping config
3. the single UTC offset shared by *every* event timestamp, if there is exactly one

If none applies, the value is an error with instructions. Every interpretation is
counted and listed in the import report.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo

from app.core.time import to_utc
from app.schemas.dataset import IssueSeverity
from app.services.dataset_import.issues import IssueLog
from app.services.dataset_import.mapping import DatasetMapping

_MONTH_DAY = re.compile(
    r"^(?P<m>\d{1,2})[-/](?P<d>\d{1,2})[ T](?P<H>\d{1,2}):(?P<M>\d{2})(?::(?P<S>\d{2}))?$"
)
_TIME = re.compile(r"^(?P<H>\d{1,2}):(?P<M>\d{2})(?::(?P<S>\d{2}))?$")
_BLOCK_SPLIT = re.compile(r"\s*(?:-|–|—|\bto\b)\s*")


def parse_time_of_day(value: str) -> time | None:
    text = value.strip()
    match = _TIME.match(text)
    if match:
        hour, minute = int(match["H"]), int(match["M"])
        second = int(match["S"] or 0)
        if hour == 24 and minute == 0 and second == 0:
            return time(0, 0)
        if hour < 24 and minute < 60 and second < 60:
            return time(hour, minute, second)
        return None
    if text.isdigit() and 0 <= int(text) <= 24:
        return time(int(text) % 24, 0)
    return None


def split_block(value: str) -> tuple[str, str] | None:
    parts = _BLOCK_SPLIT.split(value.strip())
    return (parts[0], parts[1]) if len(parts) == 2 and all(parts) else None


@dataclass(frozen=True)
class _Zone:
    tz: tzinfo
    description: str
    severity: IssueSeverity


class RosterDatetimeParser:
    def __init__(
        self,
        mapping: DatasetMapping,
        log: IssueLog,
        *,
        event_offset: tzinfo | None,
        reference_time: datetime | None,
    ) -> None:
        self.mapping = mapping
        self.log = log
        self.event_offset = event_offset
        self.reference_time = reference_time
        self._usage: Counter[tuple[str, str, str, IssueSeverity]] = Counter()

    def _zone(self, zone_hint: str | None) -> _Zone | None:
        if zone_hint:
            name = self.mapping.timezone_labels[zone_hint]
            return _Zone(
                ZoneInfo(name), f"{name} (column header label '{zone_hint}')", IssueSeverity.INFO
            )
        if self.mapping.datetimes.naive_timezone:
            name = self.mapping.datetimes.naive_timezone
            return _Zone(ZoneInfo(name), f"{name} (datetimes.naive_timezone)", IssueSeverity.INFO)
        if self.mapping.datetimes.infer_from_event_stream_offset and self.event_offset:
            offset = datetime(2000, 1, 1, tzinfo=self.event_offset).strftime("%z")
            return _Zone(
                self.event_offset,
                f"UTC{offset[:3]}:{offset[3:]} (the single offset used by every event timestamp)",
                IssueSeverity.WARNING,
            )
        return None

    def _reference_date(self, tz: tzinfo) -> date | None:
        return self.reference_time.astimezone(tz).date() if self.reference_time else None

    def _fail(self, value: str, file: str, row: int, column: str, why: str) -> None:
        self.log.add(
            IssueSeverity.ERROR,
            "invalid_datetime",
            f"{column} '{value}' {why}",
            file=file,
            row=row,
            column=column,
            value=value,
            hint=(
                "Use ISO-8601 with an offset (2030-05-14T08:00:00-04:00), or set "
                "datetimes.naive_timezone in a DATASET_MAPPING_FILE override."
            ),
        )

    def parse(
        self, value: str, *, file: str, row: int, column: str, zone_hint: str | None = None
    ) -> datetime | None:
        """A full timestamp. Partial forms (MM-DD HH:MM, HH:MM) borrow the reference date."""
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
        except ValueError:
            parsed = None
        if parsed is not None and parsed.tzinfo is not None:
            return to_utc(parsed)

        zone = self._zone(zone_hint)
        if zone is None:
            self._fail(value, file, row, column, "has no UTC offset and no zone policy applies")
            return None

        local: datetime | None = None
        if parsed is not None:
            local = parsed.replace(tzinfo=zone.tz)
        else:
            ref_date = self._reference_date(zone.tz)
            month_day = _MONTH_DAY.match(text)
            time_only = _TIME.match(text)
            if (month_day or time_only) and ref_date is None:
                self._fail(value, file, row, column, "has no date and no reference date is known")
                return None
            if month_day and ref_date:
                try:
                    local = datetime(
                        ref_date.year,
                        int(month_day["m"]),
                        int(month_day["d"]),
                        int(month_day["H"]),
                        int(month_day["M"]),
                        int(month_day["S"] or 0),
                        tzinfo=zone.tz,
                    )
                except ValueError:
                    local = None
            elif time_only and ref_date:
                tod = parse_time_of_day(text)
                local = datetime.combine(ref_date, tod, tzinfo=zone.tz) if tod else None
        if local is None:
            self._fail(value, file, row, column, "is not a recognised date/time")
            return None
        self._usage[(file, column, zone.description, zone.severity)] += 1
        return to_utc(local)

    def parse_shift(
        self,
        start: str,
        end: str,
        *,
        file: str,
        row: int,
        column: str,
        zone_hint: str | None = None,
    ) -> tuple[datetime, datetime] | None:
        """A shift window. Time-only pairs may cross midnight and are placed on the date
        whose window contains the reference time (else the reference date)."""
        start_tod, end_tod = parse_time_of_day(start), parse_time_of_day(end)
        if start_tod is None or end_tod is None or ":" not in start + end:
            begin = self.parse(start, file=file, row=row, column=column, zone_hint=zone_hint)
            finish = self.parse(end, file=file, row=row, column=column, zone_hint=zone_hint)
            if begin is None or finish is None:
                return None
            if finish <= begin:
                self._fail(f"{start} - {end}", file, row, column, "ends before it starts")
                return None
            return begin, finish

        zone = self._zone(zone_hint)
        if zone is None or self.reference_time is None:
            why = "has no date or UTC offset and no zone policy applies"
            self._fail(f"{start} - {end}", file, row, column, why)
            return None
        ref_local = self.reference_time.astimezone(zone.tz)
        windows = []
        for day in (ref_local.date() - timedelta(days=1), ref_local.date()):
            begin = datetime.combine(day, start_tod, tzinfo=zone.tz)
            finish = datetime.combine(day, end_tod, tzinfo=zone.tz)
            if finish <= begin:
                finish += timedelta(days=1)
            windows.append((to_utc(begin), to_utc(finish)))
        chosen = next((w for w in windows if w[0] <= self.reference_time < w[1]), windows[-1])
        self._usage[(file, column, zone.description, zone.severity)] += 1
        return chosen

    def report(self) -> None:
        for (file, column, description, severity), count in sorted(
            self._usage.items(), key=lambda item: (item[0][0], item[0][1])
        ):
            self.log.add(
                severity,
                "datetime_interpreted",
                f"{count} value(s) in '{column}' had no UTC offset and were interpreted in "
                f"{description}",
                file=file,
                column=column,
                hint="Provide offsets in the data or set datetimes.naive_timezone to be explicit.",
            )
