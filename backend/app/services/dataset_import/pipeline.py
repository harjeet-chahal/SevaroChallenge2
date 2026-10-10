"""Validate a full dataset in memory. Nothing touches the database here.

The result either has errors (and is never persisted) or is a complete, consistent set
of records ready for atomic replacement by ``persistence.replace_active_dataset``.
"""

from __future__ import annotations

import fnmatch
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.core.time import NaiveDatetimeError, parse_iso_aware, to_utc
from app.schemas.coverage import BaselineVolume, CoverageRequirement
from app.schemas.dataset import DatasetImportReport, DatasetImportStatus, IssueSeverity
from app.schemas.event import EventSource, NormalizedEvent
from app.schemas.hospital import Hospital
from app.schemas.physician import Physician
from app.schemas.simulation import ReferenceTimeSource
from app.services.dataset_import.csv_table import CsvTable, read_csv
from app.services.dataset_import.datetimes import RosterDatetimeParser
from app.services.dataset_import.issues import IssueLog
from app.services.dataset_import.manifest import (
    DATASET_MANIFEST_FILENAME,
    MULTI_FILE_TABLES,
    LogicalTable,
)
from app.services.dataset_import.mapping import DatasetMapping
from app.services.dataset_import.parsers import (
    ParseContext,
    RejectedEvent,
    SnapshotRowDraft,
    parse_baseline,
    parse_coverage,
    parse_credentials,
    parse_event_rows,
    parse_hospitals,
    parse_physicians_off_shift,
    parse_physicians_on_shift,
    parse_snapshots,
)
from app.services.dataset_import.sources import DatasetFile

_SNAPSHOT_TIME = re.compile(r"_(?P<H>[01]\d|2[0-3])(?P<M>[0-5]\d)$")


@dataclass
class ManifestInfo:
    label: str | None = None
    synthetic: bool = False
    reference_time: datetime | None = None


@dataclass
class ValidatedDataset:
    report: DatasetImportReport
    hospitals: list[Hospital] = field(default_factory=list)
    physicians: list[Physician] = field(default_factory=list)
    coverage: list[CoverageRequirement] = field(default_factory=list)
    baseline: list[BaselineVolume] = field(default_factory=list)
    events: list[NormalizedEvent] = field(default_factory=list)
    rejected: list[RejectedEvent] = field(default_factory=list)
    snapshot_rows: list[SnapshotRowDraft] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.report.status is not DatasetImportStatus.FAILED


def _read_manifest(file: DatasetFile, log: IssueLog) -> ManifestInfo:
    try:
        data = json.loads(file.data.decode("utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("top level must be an object")
        info = ManifestInfo(label=data.get("label"), synthetic=bool(data.get("synthetic", False)))
        if data.get("reference_time"):
            info.reference_time = to_utc(parse_iso_aware(str(data["reference_time"])))
        return info
    except NaiveDatetimeError:
        log.add(
            IssueSeverity.ERROR,
            "manifest_invalid",
            "reference_time needs a UTC offset",
            file=file.name,
        )
    except (ValueError, UnicodeDecodeError) as exc:
        log.add(IssueSeverity.ERROR, "manifest_invalid", f"invalid manifest: {exc}", file=file.name)
    return ManifestInfo()


def _classify(files: list[DatasetFile], mapping: DatasetMapping, log: IssueLog):
    by_table: dict[str, list[DatasetFile]] = {}
    manifest: DatasetFile | None = None
    for file in files:
        lower = file.name.lower()
        if lower == DATASET_MANIFEST_FILENAME:
            manifest = file
            continue
        table = next(
            (
                t
                for t, patterns in mapping.file_patterns.items()
                if any(fnmatch.fnmatch(lower, p.lower()) for p in patterns)
            ),
            None,
        )
        if table is None:
            severity = IssueSeverity.WARNING if lower.endswith(".csv") else IssueSeverity.INFO
            log.add(
                severity,
                "file_not_recognised",
                f"'{file.name}' does not match any dataset file pattern; ignored",
                file=file.name,
                hint="Rename it or add a pattern under file_patterns in the mapping.",
            )
            continue
        by_table.setdefault(table, []).append(file)

    for table, group in by_table.items():
        if len(group) > 1 and table not in MULTI_FILE_TABLES:
            log.add(
                IssueSeverity.ERROR,
                "multiple_files",
                f"{len(group)} files match {table}: {', '.join(f.name for f in group)}",
                hint="Upload exactly one file per table.",
            )
    for table in mapping.required_tables:
        if table not in by_table:
            patterns = ", ".join(mapping.file_patterns.get(table, []))
            log.add(
                IssueSeverity.ERROR,
                "missing_file",
                f"required file for '{table}' not found ({patterns})",
                hint="Include it in the ZIP/upload, or adjust file_patterns in the mapping.",
            )
    for table in LogicalTable:
        if table not in by_table and table not in mapping.required_tables:
            if table is not LogicalTable.REFERENCE_SNAPSHOT:
                log.add(
                    IssueSeverity.WARNING,
                    "optional_file_missing",
                    f"documented file '{table}' not provided; later phases will need it",
                )
    return by_table, manifest


def determine_reference_time(
    events: list[NormalizedEvent],
    *,
    override: datetime | None,
    manifest_time: datetime | None,
    env_time: datetime | None,
    snapshot_files: list[str],
    log: IssueLog,
) -> tuple[datetime | None, ReferenceTimeSource | None]:
    if override is not None:
        return to_utc(override), "import_option"
    if manifest_time is not None:
        return manifest_time, "dataset_manifest"
    if env_time is not None:
        return to_utc(env_time), "environment"
    if not events:
        return None, None

    latest = max(events, key=lambda e: (e.ingested_at, e.event_id))
    tokens = set()
    for name in snapshot_files:
        stem = name.rsplit(".", 1)[0]
        match = _SNAPSHOT_TIME.search(stem)
        if match:
            tokens.add((int(match["H"]), int(match["M"])))
    if len(tokens) == 1:
        hour, minute = next(iter(tokens))
        zone = parse_iso_aware(latest.ingested_at_raw).tzinfo
        local = latest.ingested_at.astimezone(zone)
        candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if abs(candidate - latest.ingested_at) <= timedelta(hours=1):
            log.add(
                IssueSeverity.INFO,
                "reference_time_derived",
                f"reference time {candidate.isoformat()} taken from snapshot file name "
                f"{hour:02d}{minute:02d}, in the offset of the latest event",
                hint="Override with reference_time on import if this is wrong.",
            )
            return to_utc(candidate), "snapshot_filename"

    ceiling = latest.ingested_at.replace(second=0, microsecond=0)
    if ceiling < latest.ingested_at:
        ceiling += timedelta(minutes=1)
    log.add(
        IssueSeverity.INFO,
        "reference_time_derived",
        f"reference time {ceiling.isoformat()} = latest ingested_at rounded up to the minute",
        hint="Override with reference_time on import if this is wrong.",
    )
    return ceiling, "latest_ingested_at"


def validate_dataset(
    files: list[DatasetFile],
    mapping: DatasetMapping,
    *,
    import_id: str,
    source_name: str,
    started_at: datetime,
    reference_override: datetime | None = None,
    env_reference: datetime | None = None,
) -> ValidatedDataset:
    log = IssueLog(mapping.max_reported_issues)
    ctx = ParseContext(mapping=mapping, log=log)
    by_table, manifest_file = _classify(files, mapping, log)
    manifest = _read_manifest(manifest_file, log) if manifest_file else ManifestInfo()

    tables: dict[str, list[CsvTable]] = {}
    for table, group in by_table.items():
        for file in group:
            parsed = read_csv(file.name, file.data, log)
            if parsed is not None:
                tables.setdefault(table, []).append(parsed)

    def first(table: LogicalTable) -> CsvTable | None:
        found = tables.get(table)
        return found[0] if found else None

    hospitals = parse_hospitals(ctx, t) if (t := first(LogicalTable.HOSPITALS)) else {}
    events = (
        parse_event_rows(ctx, t, source=EventSource.DATASET_IMPORT)
        if (t := first(LogicalTable.EVENT_STREAM))
        else None
    )
    event_list = events.events if events else []

    snapshot_tables = tables.get(LogicalTable.REFERENCE_SNAPSHOT, [])
    reference_time, reference_source = determine_reference_time(
        event_list,
        override=reference_override,
        manifest_time=manifest.reference_time,
        env_time=env_reference,
        snapshot_files=[t.file for t in snapshot_tables],
        log=log,
    )
    if reference_time is not None:
        pending = sum(1 for e in event_list if e.ingested_at > reference_time)
        if pending:
            log.add(
                IssueSeverity.INFO,
                "events_after_reference",
                f"{pending} event(s) are ingested after the reference time; they become "
                "visible as the simulation clock advances",
            )

    dates = RosterDatetimeParser(
        mapping,
        log,
        event_offset=events.single_offset if events else None,
        reference_time=reference_time,
    )
    on_shift = (
        parse_physicians_on_shift(ctx, t, dates)
        if (t := first(LogicalTable.PHYSICIANS_ON_SHIFT))
        else {}
    )
    off_shift = (
        parse_physicians_off_shift(ctx, t, dates, on_shift)
        if (t := first(LogicalTable.PHYSICIANS_OFF_SHIFT))
        else {}
    )
    physicians = {**on_shift, **off_shift}
    creds = (
        parse_credentials(ctx, t, physicians, hospitals)
        if (t := first(LogicalTable.CREDENTIALING))
        else {}
    )
    baseline = (
        parse_baseline(ctx, t, hospitals, reference_time)
        if (t := first(LogicalTable.BASELINE_VOLUME))
        else []
    )
    coverage = (
        parse_coverage(ctx, t, hospitals, reference_time)
        if (t := first(LogicalTable.COVERAGE_REQUIREMENTS))
        else []
    )
    snapshots = parse_snapshots(ctx, snapshot_tables)
    dates.report()

    unknown_physicians = Counter(
        e.physician_id for e in event_list if e.physician_id and e.physician_id not in physicians
    )
    unknown_hospitals = Counter(
        e.hospital_id for e in event_list if e.hospital_id and e.hospital_id not in hospitals
    )
    for label, counter in (("physician", unknown_physicians), ("hospital", unknown_hospitals)):
        for ref_id, count in sorted(counter.items()):
            log.add(
                IssueSeverity.WARNING,
                f"event_unknown_{label}",
                f"{count} event(s) reference {label} '{ref_id}', which is not in the reference "
                "files; events are kept",
                value=ref_id,
            )

    for pid, hospital_ids in creds.items():
        physicians[pid].credentialed_hospital_ids = sorted(hospital_ids)

    report = DatasetImportReport(
        import_id=import_id,
        status=DatasetImportStatus.FAILED if log.has_errors else DatasetImportStatus.COMPLETED,
        source_name=source_name,
        label=manifest.label,
        synthetic=manifest.synthetic,
        started_at=started_at,
        tables=ctx.tables,
        column_mappings=ctx.column_reports,
        issues=log.issues,
        issues_truncated=log.truncated,
        reference_time=reference_time,
        reference_source=reference_source,
        counts={
            "hospitals": len(hospitals),
            "physicians_on_shift": len(on_shift),
            "physicians_off_shift": len(off_shift),
            "credentials": sum(len(v) for v in creds.values()),
            "coverage_requirements": len(coverage),
            "baseline_rows": len(baseline),
            "events": len(event_list),
            "events_rejected": len(events.rejected) if events else 0,
            "unknown_type_events": sum(1 for e in event_list if not e.is_known_type),
            "snapshot_rows": len(snapshots),
        },
    )
    if log.has_errors:
        return ValidatedDataset(report=report)
    return ValidatedDataset(
        report=report,
        hospitals=sorted(hospitals.values(), key=lambda h: h.id),
        physicians=sorted(physicians.values(), key=lambda p: p.id),
        coverage=coverage,
        baseline=baseline,
        events=event_list,
        rejected=events.rejected if events else [],
        snapshot_rows=snapshots,
    )
