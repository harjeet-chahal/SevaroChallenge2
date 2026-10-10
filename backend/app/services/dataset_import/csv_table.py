"""CSV decoding and explicit header -> field resolution."""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field

from app.engines.event_processing import normalize_label
from app.schemas.dataset import ColumnMappingReport, IssueSeverity
from app.services.dataset_import.issues import IssueLog
from app.services.dataset_import.mapping import ColumnSpec

MAX_ROWS = 1_000_000


@dataclass
class CsvRow:
    number: int
    """1-based data row number (header excluded)."""
    values: dict[str, str]
    """Original header -> stripped cell value."""


@dataclass
class CsvTable:
    file: str
    headers: list[str]
    rows: list[CsvRow]


def read_csv(file: str, data: bytes, log: IssueLog) -> CsvTable | None:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
        log.add(
            IssueSeverity.WARNING,
            "encoding_fallback",
            "file is not UTF-8; read as Latin-1",
            file=file,
        )

    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|") if sample.strip() else csv.excel
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)

    headers: list[str] | None = None
    rows: list[CsvRow] = []
    for line in reader:
        if not any(cell.strip() for cell in line):
            continue
        if headers is None:
            headers = [cell.strip() for cell in line]
            normalized = [normalize_label(h) for h in headers]
            dupes = sorted({h for h in normalized if h and normalized.count(h) > 1})
            if dupes:
                log.add(
                    IssueSeverity.ERROR,
                    "duplicate_headers",
                    f"duplicate column headers after normalization: {', '.join(dupes)}",
                    file=file,
                )
                return None
            continue
        number = len(rows) + 1
        if len(line) > len(headers):
            extra = [c for c in line[len(headers) :] if c.strip()]
            if extra:
                log.add(
                    IssueSeverity.ERROR,
                    "row_too_long",
                    f"row has {len(line)} cells but the header has {len(headers)}",
                    file=file,
                    row=number,
                )
                continue
        cells = [*line, *([""] * (len(headers) - len(line)))]
        rows.append(
            CsvRow(
                number=number, values=dict(zip(headers, (c.strip() for c in cells), strict=False))
            )
        )
        if len(rows) > MAX_ROWS:
            log.add(IssueSeverity.ERROR, "too_many_rows", f"more than {MAX_ROWS:,} rows", file=file)
            return None

    if headers is None:
        log.add(IssueSeverity.ERROR, "empty_file", "file has no header row", file=file)
        return None
    return CsvTable(file=file, headers=headers, rows=rows)


@dataclass
class ColumnResolution:
    columns: dict[str, str] = field(default_factory=dict)
    """Internal field -> original header."""
    unmapped: list[str] = field(default_factory=list)
    zone_hints: dict[str, str] = field(default_factory=dict)
    """Internal field -> zone label found as a header suffix (e.g. 'shift_et' -> 'et')."""

    def get(self, row: CsvRow, name: str) -> str | None:
        header = self.columns.get(name)
        if header is None:
            return None
        value = row.values.get(header, "")
        return value if value != "" else None

    def extras(self, row: CsvRow) -> dict[str, str]:
        return {h: row.values[h] for h in self.unmapped if row.values.get(h)}


def resolve_columns(
    table: CsvTable,
    spec: dict[str, ColumnSpec],
    *,
    table_name: str,
    zone_labels: dict[str, str],
    log: IssueLog,
) -> tuple[ColumnResolution, ColumnMappingReport, bool]:
    """Match headers to fields by alias. Returns (resolution, report, ok)."""
    resolution = ColumnResolution()
    normalized = {h: normalize_label(h) for h in table.headers}
    ok = True

    for name, column in spec.items():
        matches: list[tuple[str, str | None]] = []
        for header, norm in normalized.items():
            if header in resolution.columns.values():
                continue  # already claimed by an earlier field
            if norm in column.aliases:
                matches.append((header, None))
                continue
            # Allow a trailing time-zone label, e.g. "Shift (ET)" -> shift + zone hint "et".
            stem, _, suffix = norm.rpartition("_")
            if stem in column.aliases and suffix in zone_labels:
                matches.append((header, suffix))
        if len(matches) > 1:
            log.add(
                IssueSeverity.ERROR,
                "ambiguous_column",
                f"columns {', '.join(repr(h) for h, _ in matches)} all match field '{name}'",
                file=table.file,
                hint=f"Remove one, or narrow tables.{table_name}.{name}.aliases in the mapping.",
            )
            ok = False
        elif matches:
            header, zone = matches[0]
            resolution.columns[name] = header
            if zone:
                resolution.zone_hints[name] = zone
        elif column.required:
            log.add(
                IssueSeverity.ERROR,
                "missing_column",
                f"required field '{name}' not found. Accepted headers: "
                f"{', '.join(column.aliases)}. Found: {', '.join(table.headers)}",
                file=table.file,
                column=name,
                hint=(
                    f"Rename the column, or add its header to tables.{table_name}.{name}.aliases "
                    "in a DATASET_MAPPING_FILE override."
                ),
            )
            ok = False

    claimed = set(resolution.columns.values())
    resolution.unmapped = [h for h in table.headers if h not in claimed]
    report = ColumnMappingReport(
        file=table.file,
        table=table_name,
        mapped=dict(resolution.columns),
        unmapped_headers=resolution.unmapped,
        zone_hint=", ".join(sorted(set(resolution.zone_hints.values()))) or None,
    )
    return resolution, report, ok
