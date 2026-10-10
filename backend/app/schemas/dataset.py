"""Dataset import reports and status. See docs/dataset-import-plan.md."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, Field

from app.schemas.common import ApiModel, EntityId
from app.schemas.simulation import ReferenceTimeSource


class DatasetImportStatus(StrEnum):
    PENDING = "pending"
    VALIDATING = "validating"
    IMPORTING = "importing"
    COMPLETED = "completed"
    FAILED = "failed"


class IssueSeverity(StrEnum):
    """Import issue severity: ``error`` blocks the import; the others are reported only."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ImportIssue(ApiModel):
    """A descriptive, locatable problem found while validating or importing a dataset.

    ``error`` blocks the import; ``warning`` and ``info`` are reported but do not.
    """

    severity: IssueSeverity
    code: str
    message: str
    file: str | None = None
    row: int | None = Field(default=None, ge=1)
    """1-based data row number (header excluded)."""
    column: str | None = None
    value: str | None = None
    hint: str | None = None
    """How to fix it, when there is an obvious action."""


class TableImportSummary(ApiModel):
    table: str
    files: list[str] = Field(default_factory=list)
    rows_read: int = Field(ge=0)
    rows_imported: int = Field(ge=0)
    rows_rejected: int = Field(ge=0)


class ColumnMappingReport(ApiModel):
    """Which source header fed which internal field. Nothing is mapped silently."""

    file: str
    table: str
    mapped: dict[str, str]
    unmapped_headers: list[str] = Field(default_factory=list)
    zone_hint: str | None = None


class DatasetImportReport(ApiModel):
    import_id: EntityId
    status: DatasetImportStatus
    source_name: str
    label: str | None = None
    synthetic: bool = False
    started_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    tables: list[TableImportSummary] = Field(default_factory=list)
    column_mappings: list[ColumnMappingReport] = Field(default_factory=list)
    issues: list[ImportIssue] = Field(default_factory=list)
    issues_truncated: int = 0
    reference_time: AwareDatetime | None = None
    reference_source: ReferenceTimeSource | None = None
    counts: dict[str, int] = Field(default_factory=dict)

    @property
    def error_count(self) -> int:
        return sum(1 for issue in self.issues if issue.severity is IssueSeverity.ERROR)


class ActiveDataset(ApiModel):
    import_id: EntityId
    label: str | None
    synthetic: bool
    source_name: str
    imported_at: AwareDatetime
    reference_time: AwareDatetime | None
    reference_source: ReferenceTimeSource | None
    counts: dict[str, int]
    live_events: int = 0
    rejected_events: int = 0
    warnings: int = 0


class DatasetStatus(ApiModel):
    loaded: bool
    active: ActiveDataset | None = None
    active_report: DatasetImportReport | None = None
    last_attempt: DatasetImportReport | None = None
    """The most recent import attempt, if it differs from the active dataset (e.g. failed)."""


class SnapshotMismatch(ApiModel):
    kind: str
    """``physician`` or ``consult``."""
    entity_id: str
    field: str
    expected: Any
    actual: Any


class SnapshotVerification(ApiModel):
    """Comparison of the replay at the reference time against reference snapshot files.

    Mismatches are reported as-is; the engine is never tuned to force a match.
    """

    available: bool
    as_of: AwareDatetime | None = None
    files: list[str] = Field(default_factory=list)
    compared_entities: int = 0
    compared_fields: int = 0
    mismatches: list[SnapshotMismatch] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SampleDataset(ApiModel):
    name: str
    label: str
    synthetic: bool
    reference_time: str | None = None
    default: bool = False
