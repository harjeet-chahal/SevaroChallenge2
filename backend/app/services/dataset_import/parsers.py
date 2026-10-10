"""Per-file parsers: CSV rows -> typed records, with every problem reported."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from app.core.time import parse_iso_aware, validate_timezone
from app.engines.event_processing import (
    EventValidationError,
    normalize_event,
    normalize_label,
)
from app.schemas.coverage import BaselineVolume, CoverageRequirement
from app.schemas.dataset import ColumnMappingReport, IssueSeverity, TableImportSummary
from app.schemas.event import KNOWN_EVENT_TYPES, EventSource, FieldIssue, NormalizedEvent
from app.schemas.hospital import Hospital
from app.schemas.physician import Physician, PhysicianSchedule, ShiftWindow
from app.services.dataset_import.csv_table import ColumnResolution, CsvTable, resolve_columns
from app.services.dataset_import.datetimes import (
    RosterDatetimeParser,
    parse_time_of_day,
    split_block,
)
from app.services.dataset_import.issues import IssueLog
from app.services.dataset_import.manifest import LogicalTable
from app.services.dataset_import.mapping import DatasetMapping


@dataclass
class ParseContext:
    mapping: DatasetMapping
    log: IssueLog
    column_reports: list[ColumnMappingReport] = field(default_factory=list)
    tables: list[TableImportSummary] = field(default_factory=list)

    def resolve(self, table: CsvTable, logical: str) -> ColumnResolution | None:
        resolution, report, ok = resolve_columns(
            table,
            self.mapping.columns(logical),
            table_name=str(logical),
            zone_labels=self.mapping.timezone_labels,
            log=self.log,
        )
        self.column_reports.append(report)
        return resolution if ok else None

    def summary(self, logical: str, files: list[str], read: int, imported: int) -> None:
        self.tables.append(
            TableImportSummary(
                table=str(logical),
                files=files,
                rows_read=read,
                rows_imported=imported,
                rows_rejected=read - imported,
            )
        )

    def warn_missing_documented(self, table: CsvTable, res: ColumnResolution, names: list[str]):
        missing = [n for n in names if n not in res.columns]
        if missing:
            self.log.add(
                IssueSeverity.WARNING,
                "documented_column_missing",
                f"documented content not found: {', '.join(missing)} (not needed until later "
                "phases; values left empty)",
                file=table.file,
            )


def _bool(ctx: ParseContext, value: str | None, *, file: str, row: int, column: str) -> bool | None:
    if value is None:
        return None
    norm = normalize_label(value)
    if norm in ctx.mapping.true_values:
        return True
    if norm in ctx.mapping.false_values:
        return False
    ctx.log.add(
        IssueSeverity.ERROR,
        "invalid_boolean",
        f"'{value}' is not a recognised yes/no value",
        file=file,
        row=row,
        column=column,
        value=value,
        hint="Accepted values are listed under true_values / false_values in the mapping.",
    )
    return None


def _number(
    ctx: ParseContext, value: str | None, *, file: str, row: int, column: str, integer: bool
) -> float | int | None:
    if value is None:
        return None
    try:
        number = float(value)
    except ValueError:
        number = None
    if number is None or number < 0 or (integer and not number.is_integer()):
        kind = "a non-negative integer" if integer else "a non-negative number"
        ctx.log.add(
            IssueSeverity.ERROR,
            "invalid_number",
            f"'{value}' is not {kind}",
            file=file,
            row=row,
            column=column,
            value=value,
        )
        return None
    return int(number) if integer else number


def resolve_timezone(ctx: ParseContext, value: str, *, file: str, row: int) -> str | None:
    text = value.strip()
    if "/" in text or text.upper() == "UTC":
        try:
            return validate_timezone(text)
        except ValueError:
            pass
    label = normalize_label(text)
    if label in ctx.mapping.timezone_labels:
        mapped = ctx.mapping.timezone_labels[label]
        ctx.log.add(
            IssueSeverity.INFO,
            "timezone_label_mapped",
            f"time zone '{text}' interpreted as {mapped}",
            file=file,
            row=row,
            column="timezone",
            value=text,
        )
        return mapped
    ctx.log.add(
        IssueSeverity.ERROR,
        "invalid_timezone",
        f"'{text}' is not a recognised IANA time zone",
        file=file,
        row=row,
        column="timezone",
        value=text,
        hint="Use an IANA name such as America/Chicago, or add the label to timezone_labels.",
    )
    return None


# --- hospitals --------------------------------------------------------------------


def parse_hospitals(ctx: ParseContext, table: CsvTable) -> dict[str, Hospital]:
    res = ctx.resolve(table, LogicalTable.HOSPITALS)
    hospitals: dict[str, Hospital] = {}
    if res is None:
        return hospitals
    ctx.warn_missing_documented(table, res, ["coverage_tier"])
    unnamed = 0
    for row in table.rows:
        hid = res.get(row, "hospital_id")
        if hid is None:
            ctx.log.add(
                IssueSeverity.ERROR,
                "missing_id",
                "hospital_id is empty",
                file=table.file,
                row=row.number,
            )
            continue
        if hid in hospitals:
            ctx.log.add(
                IssueSeverity.ERROR,
                "duplicate_id",
                f"hospital '{hid}' appears more than once",
                file=table.file,
                row=row.number,
                value=hid,
            )
            continue
        tz_raw = res.get(row, "timezone")
        if tz_raw is None:
            ctx.log.add(
                IssueSeverity.ERROR,
                "missing_timezone",
                f"hospital '{hid}' has no time zone",
                file=table.file,
                row=row.number,
            )
            continue
        tz = resolve_timezone(ctx, tz_raw, file=table.file, row=row.number)
        if tz is None:
            continue
        name = res.get(row, "name")
        if name is None:
            unnamed += 1
        hospitals[hid] = Hospital(
            id=hid,
            name=name or hid,
            timezone=tz,
            coverage_tier=res.get(row, "coverage_tier"),
            attributes=res.extras(row),
        )
    if unnamed:
        ctx.log.add(
            IssueSeverity.WARNING,
            "hospital_name_missing",
            f"{unnamed} hospital(s) have no name; their ID is shown instead",
            file=table.file,
        )
    ctx.summary(LogicalTable.HOSPITALS, [table.file], len(table.rows), len(hospitals))
    return hospitals


# --- events -----------------------------------------------------------------------


@dataclass
class RejectedEvent:
    source_file: str
    source_row: int
    event_id: str | None
    event_type: str | None
    errors: list[FieldIssue]
    raw: dict[str, Any]


@dataclass
class ParsedEvents:
    events: list[NormalizedEvent] = field(default_factory=list)
    rejected: list[RejectedEvent] = field(default_factory=list)
    single_offset: tzinfo | None = None
    rows_read: int = 0


def parse_event_rows(
    ctx: ParseContext, table: CsvTable, *, source: EventSource, report_summary: bool = True
) -> ParsedEvents:
    res = ctx.resolve(table, LogicalTable.EVENT_STREAM)
    parsed = ParsedEvents(rows_read=len(table.rows))
    if res is None:
        return parsed
    fallbacks: Counter[str] = Counter()
    warnings: Counter[str] = Counter()
    unknown_types: Counter[str] = Counter()
    offsets: set[Any] = set()
    spec = ctx.mapping.columns(LogicalTable.EVENT_STREAM)

    for row in table.rows:
        fields = {name: res.get(row, name) for name in spec}
        try:
            result = normalize_event(
                fields,
                source=source,
                rules=ctx.mapping.events,
                extra=res.extras(row),
                raw=row.values,
                source_file=table.file,
                source_row=row.number,
            )
        except EventValidationError as exc:
            parsed.rejected.append(
                RejectedEvent(
                    source_file=table.file,
                    source_row=row.number,
                    event_id=exc.event_id,
                    event_type=exc.event_type,
                    errors=exc.issues,
                    raw=dict(row.values),
                )
            )
            ctx.log.add(
                IssueSeverity.WARNING,
                "event_rejected",
                f"event {exc.event_id or '(no id)'} rejected: {exc}",
                file=table.file,
                row=row.number,
            )
            continue
        event = result.event
        parsed.events.append(event)
        fallbacks.update(result.used_fallbacks)
        for warning in result.warnings:
            if warning.startswith("unknown event_type"):
                continue  # reported per type below
            if "clock skew" in warning:
                warning = "event_time is after ingested_at (clock skew)"
            warnings[warning] += 1
        if event.event_type not in KNOWN_EVENT_TYPES:
            unknown_types[event.event_type] += 1
        for raw_ts in (event.event_time_raw, event.ingested_at_raw):
            offsets.add(parse_iso_aware(raw_ts).utcoffset())

    if len(offsets) == 1:
        parsed.single_offset = timezone(next(iter(offsets)))

    for kind, count in sorted(fallbacks.items()):
        ctx.log.add(
            IssueSeverity.INFO,
            "description_fallback",
            f"{count} event(s): {kind.replace('_', ' ')} (no dedicated column)",
            file=table.file,
            hint="Patterns are configurable under events.* in the mapping.",
        )
    for message, count in sorted(warnings.items()):
        ctx.log.add(
            IssueSeverity.WARNING, "event_warning", f"{count} event(s): {message}", file=table.file
        )
    for event_type, count in sorted(unknown_types.items()):
        ctx.log.add(
            IssueSeverity.WARNING,
            "unknown_event_type",
            f"{count} event(s) of undocumented type '{event_type}' stored and reported; "
            "they do not change state",
            file=table.file,
            value=event_type,
        )

    by_id: dict[str, list[NormalizedEvent]] = defaultdict(list)
    for event in parsed.events:
        by_id[event.event_id].append(event)
    repeated = {eid: copies for eid, copies in by_id.items() if len(copies) > 1}
    if repeated:
        conflicting = sorted(
            eid for eid, copies in repeated.items() if len({c.content_hash for c in copies}) > 1
        )
        ctx.log.add(
            IssueSeverity.INFO,
            "duplicate_events",
            f"{len(repeated)} event id(s) appear more than once; the first-ingested copy is "
            f"applied: {', '.join(sorted(repeated)[:10])}",
            file=table.file,
        )
        if conflicting:
            ctx.log.add(
                IssueSeverity.WARNING,
                "conflicting_duplicate_events",
                f"same event id with different content: {', '.join(conflicting[:10])}",
                file=table.file,
            )

    total = len(table.rows)
    if total and not parsed.events:
        ctx.log.add(
            IssueSeverity.ERROR,
            "no_valid_events",
            "no event row passed validation",
            file=table.file,
        )
    elif total and len(parsed.rejected) / total > ctx.mapping.max_event_rejection_ratio:
        ctx.log.add(
            IssueSeverity.ERROR,
            "too_many_invalid_events",
            f"{len(parsed.rejected)} of {total} event rows are invalid (limit "
            f"{ctx.mapping.max_event_rejection_ratio:.0%}); the format probably differs",
            file=table.file,
            hint="Check the event_rejected issues above, then adjust the mapping or the data.",
        )
    if report_summary:
        ctx.summary(LogicalTable.EVENT_STREAM, [table.file], total, len(parsed.events))
    return parsed


# --- physicians -------------------------------------------------------------------


def parse_physicians_on_shift(
    ctx: ParseContext, table: CsvTable, dates: RosterDatetimeParser
) -> dict[str, Physician]:
    res = ctx.resolve(table, LogicalTable.PHYSICIANS_ON_SHIFT)
    physicians: dict[str, Physician] = {}
    if res is None:
        return physicians
    split = "shift_start" in res.columns and "shift_end" in res.columns
    combined = "shift" in res.columns
    if not split and not combined:
        ctx.log.add(
            IssueSeverity.ERROR,
            "missing_column",
            "shift times not found: need shift_start + shift_end columns, or one shift column "
            f"like '08:00-20:00'. Found: {', '.join(table.headers)}",
            file=table.file,
            hint="Add the headers to tables.physicians_on_shift.* aliases in the mapping.",
        )
        return physicians

    for row in table.rows:
        pid = res.get(row, "physician_id")
        if pid is None:
            ctx.log.add(
                IssueSeverity.ERROR,
                "missing_id",
                "physician_id is empty",
                file=table.file,
                row=row.number,
            )
            continue
        if pid in physicians:
            ctx.log.add(
                IssueSeverity.ERROR,
                "duplicate_id",
                f"physician '{pid}' appears more than once",
                file=table.file,
                row=row.number,
                value=pid,
            )
            continue
        if split:
            start, end = res.get(row, "shift_start"), res.get(row, "shift_end")
            column, hint = res.columns["shift_start"], res.zone_hints.get("shift_start")
        else:
            pair = split_block(res.get(row, "shift") or "")
            start, end = pair if pair else (None, None)
            column, hint = res.columns["shift"], res.zone_hints.get("shift")
        if start is None or end is None:
            ctx.log.add(
                IssueSeverity.ERROR,
                "missing_shift",
                f"physician '{pid}' has no usable shift times",
                file=table.file,
                row=row.number,
            )
            continue
        window = dates.parse_shift(
            start, end, file=table.file, row=row.number, column=column, zone_hint=hint
        )
        if window is None:
            continue
        physicians[pid] = Physician(
            id=pid,
            display_name=res.get(row, "display_name") or pid,
            roster="on_shift",
            roster_role=res.get(row, "roster_role"),
            schedule=PhysicianSchedule(current_shift=ShiftWindow(start=window[0], end=window[1])),
            attributes=res.extras(row),
        )
    ctx.summary(LogicalTable.PHYSICIANS_ON_SHIFT, [table.file], len(table.rows), len(physicians))
    return physicians


def parse_physicians_off_shift(
    ctx: ParseContext, table: CsvTable, dates: RosterDatetimeParser, on_shift: dict[str, Physician]
) -> dict[str, Physician]:
    res = ctx.resolve(table, LogicalTable.PHYSICIANS_OFF_SHIFT)
    physicians: dict[str, Physician] = {}
    if res is None:
        return physicians
    ctx.warn_missing_documented(
        table,
        res,
        [
            "split_shift_opt_in",
            "last_shift_ended_at",
            "next_shift_starts_at",
            "hours_worked_trailing_7d",
            "minutes_to_come_online",
        ],
    )
    for row in table.rows:
        n, f = row.number, table.file
        pid = res.get(row, "physician_id")
        if pid is None:
            ctx.log.add(IssueSeverity.ERROR, "missing_id", "physician_id is empty", file=f, row=n)
            continue
        if pid in physicians or pid in on_shift:
            ctx.log.add(
                IssueSeverity.ERROR,
                "duplicate_id",
                f"physician '{pid}' appears more than once across rosters",
                file=f,
                row=n,
                value=pid,
            )
            continue

        def when(name: str, row=row, n=n, f=f):
            value = res.get(row, name)
            if value is None:
                return None
            return dates.parse(
                value, file=f, row=n, column=res.columns[name], zone_hint=res.zone_hints.get(name)
            )

        def num(name: str, integer: bool, row=row, n=n, f=f):
            column = res.columns.get(name, name)
            return _number(ctx, res.get(row, name), file=f, row=n, column=column, integer=integer)

        physicians[pid] = Physician(
            id=pid,
            display_name=res.get(row, "display_name") or pid,
            roster="off_shift",
            roster_role=res.get(row, "roster_role"),
            split_shift_opt_in=_bool(
                ctx,
                res.get(row, "split_shift_opt_in"),
                file=f,
                row=n,
                column=res.columns.get("split_shift_opt_in", "opt_in"),
            ),
            notification_channel=res.get(row, "notification_channel"),
            schedule=PhysicianSchedule(
                last_shift_ended_at=when("last_shift_ended_at"),
                next_shift_starts_at=when("next_shift_starts_at"),
                hours_worked_trailing_7d=num("hours_worked_trailing_7d", False),
                minutes_to_come_online=num("minutes_to_come_online", True),
                offers_declined_30d=num("offers_declined_30d", True),
            ),
            attributes=res.extras(row),
        )
    ctx.summary(LogicalTable.PHYSICIANS_OFF_SHIFT, [table.file], len(table.rows), len(physicians))
    return physicians


# --- credentialing ----------------------------------------------------------------


def _match_hospital_header(
    ctx: ParseContext, header: str, hospitals: dict[str, Hospital]
) -> tuple[str | None, str]:
    lookup = {hid.lower(): hid for hid in hospitals}
    key = header.strip().lower()
    if key in lookup:
        return lookup[key], "exact"
    prefix = ctx.mapping.credentialing.hospital_header_prefix
    if prefix and (prefix + header.strip()).lower() in lookup:
        return lookup[(prefix + header.strip()).lower()], "prefix"
    if ctx.mapping.credentialing.allow_unique_suffix_match and key:
        candidates = [
            hid
            for low, hid in lookup.items()
            if low.endswith(key) and len(low) > len(key) and not low[-len(key) - 1].isalnum()
        ]
        if len(candidates) == 1:
            return candidates[0], "suffix"
    return None, "none"


def parse_credentials(
    ctx: ParseContext,
    table: CsvTable,
    physicians: dict[str, Physician],
    hospitals: dict[str, Hospital],
) -> dict[str, set[str]]:
    res = ctx.resolve(table, LogicalTable.CREDENTIALING)
    creds: dict[str, set[str]] = defaultdict(set)
    if res is None:
        return creds
    f = table.file
    pairs = 0

    if "hospital_id" in res.columns:  # long format
        for row in table.rows:
            pid, hid = res.get(row, "physician_id"), res.get(row, "hospital_id")
            ok = True
            if pid not in physicians:
                ctx.log.add(
                    IssueSeverity.ERROR,
                    "unknown_physician",
                    f"unknown physician '{pid}'",
                    file=f,
                    row=row.number,
                    value=pid,
                )
                ok = False
            if hid not in hospitals:
                ctx.log.add(
                    IssueSeverity.ERROR,
                    "unknown_hospital",
                    f"unknown hospital '{hid}'",
                    file=f,
                    row=row.number,
                    value=hid,
                )
                ok = False
            flag = _bool(
                ctx, res.get(row, "credentialed"), file=f, row=row.number, column="credentialed"
            )
            if ok and pid and hid and flag is not False:
                creds[pid].add(hid)
                pairs += 1
    else:  # wide matrix: one column per hospital
        columns: dict[str, str] = {}
        unmatched: list[str] = []
        for header in res.unmapped:
            hid, how = _match_hospital_header(ctx, header, hospitals)
            if hid is None:
                unmatched.append(header)
                continue
            columns[header] = hid
            if how != "exact":
                ctx.log.add(
                    IssueSeverity.INFO,
                    "credential_header_matched",
                    f"matrix column '{header}' matched hospital {hid} by {how}",
                    file=f,
                    column=header,
                )
        if unmatched:
            ctx.log.add(
                IssueSeverity.ERROR,
                "unmatched_matrix_columns",
                f"matrix columns not matching any hospital: {', '.join(unmatched)}. "
                f"Known hospitals: {', '.join(sorted(hospitals))}",
                file=f,
                hint="Set credentialing.hospital_header_prefix in the mapping, or rename columns.",
            )
        seen: set[str] = set()
        for row in table.rows:
            pid = res.get(row, "physician_id")
            if pid not in physicians:
                ctx.log.add(
                    IssueSeverity.ERROR,
                    "unknown_physician",
                    f"unknown physician '{pid}' (not in either roster)",
                    file=f,
                    row=row.number,
                    value=pid,
                )
                continue
            if pid in seen:
                ctx.log.add(
                    IssueSeverity.ERROR,
                    "duplicate_id",
                    f"physician '{pid}' has two matrix rows",
                    file=f,
                    row=row.number,
                )
                continue
            seen.add(pid)
            for header, hid in columns.items():
                if _bool(ctx, row.values.get(header, ""), file=f, row=row.number, column=header):
                    creds[pid].add(hid)
                    pairs += 1

    missing = sorted(pid for pid in physicians if pid not in creds)
    if missing:
        ctx.log.add(
            IssueSeverity.WARNING,
            "no_credentials",
            f"physicians with no credentialed hospitals: {', '.join(missing)}",
            file=f,
        )
    ctx.summary(LogicalTable.CREDENTIALING, [f], len(table.rows), len(table.rows))
    ctx.log.add(
        IssueSeverity.INFO, "credentials_loaded", f"{pairs} physician-hospital credentials", file=f
    )
    return creds


# --- baseline & coverage (retained for later phases) -------------------------------


def _hospital_ref(
    ctx: ParseContext, value: str | None, hospitals: dict[str, Hospital], f: str, n: int
) -> str | None:
    if value in hospitals:
        return value
    ctx.log.add(
        IssueSeverity.ERROR,
        "unknown_hospital",
        f"unknown hospital '{value}'",
        file=f,
        row=n,
        value=value,
    )
    return None


class _ZoneShift:
    """Converts a time of day labelled with a header zone (e.g. 'hour_start_et') into each
    hospital's local time, using the UTC offsets on the dataset's reference date.

    The engines read baseline hours and coverage blocks in hospital-local time, so an
    Eastern-labelled value for a Chicago hospital must move by one hour. Whole-day
    tables keep their shape: every row moves by the same offset difference.
    """

    def __init__(
        self,
        ctx: ParseContext,
        hint: str | None,
        reference_time: datetime | None,
        file: str,
        column: str | None,
    ) -> None:
        self.ctx = ctx
        self.source = ZoneInfo(ctx.mapping.timezone_labels[hint]) if hint else None
        self.day = (
            reference_time.astimezone(self.source).date()
            if (self.source and reference_time)
            else None
        )
        self.file = file
        self.converted: set[str] = set()
        if self.source is not None and self.day is None:
            ctx.log.add(
                IssueSeverity.WARNING,
                "zone_hint_unconverted",
                f"column '{column}' is labelled {hint.upper() if hint else ''} but there is no "
                "reference date to convert it; values are read as hospital-local time",
                file=file,
            )

    def to_local(self, tod: time, hospital: Hospital) -> time:
        if self.source is None or self.day is None:
            return tod
        target = ZoneInfo(hospital.timezone)
        moment = datetime.combine(self.day, tod, tzinfo=self.source).astimezone(target)
        if moment.utcoffset() != datetime.combine(self.day, tod, tzinfo=self.source).utcoffset():
            self.converted.add(hospital.id)
        return moment.time().replace(tzinfo=None)

    def report(self) -> None:
        if self.source is not None and self.day is not None:
            self.ctx.log.add(
                IssueSeverity.INFO,
                "zone_hint_converted",
                f"times labelled {self.source.key} converted to hospital-local time using UTC "
                f"offsets on {self.day.isoformat()}"
                + (
                    f" (shifted for {', '.join(sorted(self.converted))})"
                    if self.converted
                    else " (no hospital needed a shift)"
                ),
                file=self.file,
            )


def parse_baseline(
    ctx: ParseContext,
    table: CsvTable,
    hospitals: dict[str, Hospital],
    reference_time: datetime | None = None,
) -> list[BaselineVolume]:
    res = ctx.resolve(table, LogicalTable.BASELINE_VOLUME)
    rows: list[BaselineVolume] = []
    if res is None:
        return rows
    seen: set[tuple[str, int, str | None]] = set()
    f = table.file
    shift = _ZoneShift(
        ctx, res.zone_hints.get("hour_local"), reference_time, f, res.columns.get("hour_local")
    )
    for row in table.rows:
        hid = _hospital_ref(ctx, res.get(row, "hospital_id"), hospitals, f, row.number)
        raw_hour = res.get(row, "hour_local") or ""
        tod = parse_time_of_day(raw_hour)
        if tod is not None and hid is not None:
            tod = shift.to_local(tod, hospitals[hid])
        hour = tod.hour if tod and tod.minute == 0 and tod.second == 0 else None
        if hour is None:
            ctx.log.add(
                IssueSeverity.ERROR,
                "invalid_hour",
                f"'{raw_hour}' is not an hour 0-23",
                file=f,
                row=row.number,
                value=raw_hour,
            )
        mean = _number(
            ctx, res.get(row, "mean_consults"), file=f, row=row.number, column="mean", integer=False
        )
        p90 = _number(
            ctx, res.get(row, "p90_consults"), file=f, row=row.number, column="p90", integer=False
        )
        day_type = res.get(row, "day_type")
        if hid is None or hour is None or mean is None or p90 is None:
            continue
        key = (hid, hour, day_type)
        if key in seen:
            ctx.log.add(
                IssueSeverity.ERROR,
                "duplicate_row",
                f"duplicate baseline for {hid} hour {hour}",
                file=f,
                row=row.number,
            )
            continue
        seen.add(key)
        rows.append(
            BaselineVolume(
                hospital_id=hid,
                hour_local=hour,
                mean_consults=mean,
                p90_consults=p90,
                day_type=day_type,
            )
        )
    shift.report()
    ctx.summary(LogicalTable.BASELINE_VOLUME, [f], len(table.rows), len(rows))
    return rows


def parse_coverage(
    ctx: ParseContext,
    table: CsvTable,
    hospitals: dict[str, Hospital],
    reference_time: datetime | None = None,
) -> list[CoverageRequirement]:
    res = ctx.resolve(table, LogicalTable.COVERAGE_REQUIREMENTS)
    rows: list[CoverageRequirement] = []
    if res is None:
        return rows
    f = table.file
    split = "block_start" in res.columns and "block_end" in res.columns
    if not split and "block" not in res.columns:
        ctx.log.add(
            IssueSeverity.ERROR,
            "missing_column",
            "time block not found: need block_start + block_end, or one block column like "
            f"'07:00-19:00'. Found: {', '.join(table.headers)}",
            file=f,
        )
        return rows
    hint_field = "block_start" if split else "block"
    shift = _ZoneShift(
        ctx, res.zone_hints.get(hint_field), reference_time, f, res.columns.get(hint_field)
    )
    for row in table.rows:
        hid = _hospital_ref(ctx, res.get(row, "hospital_id"), hospitals, f, row.number)
        if split:
            raw_start, raw_end = res.get(row, "block_start") or "", res.get(row, "block_end") or ""
        else:
            pair = split_block(res.get(row, "block") or "")
            raw_start, raw_end = pair if pair else ("", "")
        start, end = _block_time(raw_start), _block_time(raw_end)
        if start is None or end is None:
            ctx.log.add(
                IssueSeverity.ERROR,
                "invalid_time_block",
                f"'{raw_start}'-'{raw_end}' is not a valid time block",
                file=f,
                row=row.number,
            )
        minimum = _number(
            ctx,
            res.get(row, "min_available_physicians"),
            file=f,
            row=row.number,
            column="min_available_physicians",
            integer=True,
        )
        if hid is None or start is None or end is None or minimum is None:
            continue
        start, end = shift.to_local(start, hospitals[hid]), shift.to_local(end, hospitals[hid])
        rows.append(
            CoverageRequirement(
                hospital_id=hid,
                block_start_local=start,
                block_end_local=end,
                min_available_physicians=int(minimum),
                day_type=res.get(row, "day_type"),
            )
        )
    shift.report()
    ctx.summary(LogicalTable.COVERAGE_REQUIREMENTS, [f], len(table.rows), len(rows))
    return rows


def _block_time(value: str) -> time | None:
    tod = parse_time_of_day(value)
    if tod is not None:
        return tod
    try:  # a full timestamp: keep only its local time of day
        return parse_iso_aware(value).timetz().replace(tzinfo=None)
    except ValueError:
        return None


# --- reference snapshots (verification only) --------------------------------------


@dataclass
class SnapshotRowDraft:
    file: str
    kind: str
    row_number: int
    data: dict[str, Any]


def parse_snapshots(ctx: ParseContext, tables: list[CsvTable]) -> list[SnapshotRowDraft]:
    drafts: list[SnapshotRowDraft] = []
    for table in tables:
        norm = {normalize_label(h) for h in table.headers}
        consult_cols = ctx.mapping.columns("snapshot_consults")["consult_id"].aliases
        phys_cols = ctx.mapping.columns("snapshot_physicians")["physician_id"].aliases
        if norm & set(consult_cols):
            kind = "consults"
        elif norm & set(phys_cols):
            kind = "physicians"
        else:
            kind = "unknown"
            ctx.log.add(
                IssueSeverity.WARNING,
                "snapshot_unrecognized",
                "snapshot layout not recognised (no consult or physician id column); "
                "stored but not used for verification",
                file=table.file,
            )
        drafts.extend(
            SnapshotRowDraft(
                file=table.file, kind=kind, row_number=row.number, data=dict(row.values)
            )
            for row in table.rows
        )
        ctx.summary(LogicalTable.REFERENCE_SNAPSHOT, [table.file], len(table.rows), len(table.rows))
    return drafts
