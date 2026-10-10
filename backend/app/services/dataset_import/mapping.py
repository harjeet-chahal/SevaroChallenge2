"""The adapter layer between dataset files and internal models.

Every source column is matched to an internal field through an explicit alias list —
never by fuzzy guessing — and the import report lists exactly which header fed which
field. If the judging dataset names a column differently, add the header to the alias
list here or in a JSON override file (``DATASET_MAPPING_FILE``) and re-import; no code
changes needed. Aliases are compared after ``normalize_label`` (lowercase, non
alphanumerics -> ``_``), so ``"Phys."`` matches ``phys`` and ``"Event time"`` matches
``event_time``.

Aliases marked "(brief)" are the display headers used in the challenge brief's tables.
They are aliases, not claims about the official CSV schema.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.core.time import validate_timezone
from app.engines.event_processing import EventParsingRules, normalize_label
from app.services.dataset_import.manifest import LogicalTable


class ColumnSpec(BaseModel):
    aliases: list[str]
    required: bool = False

    @field_validator("aliases")
    @classmethod
    def _normalize(cls, aliases: list[str]) -> list[str]:
        return [normalize_label(a) for a in aliases]


def _col(*aliases: str, required: bool = False) -> ColumnSpec:
    return ColumnSpec(aliases=list(aliases), required=required)


class CredentialingOptions(BaseModel):
    hospital_header_prefix: str | None = None
    """For a wide matrix whose hospital columns omit a common ID prefix, e.g. 'SYN-'."""
    allow_unique_suffix_match: bool = True
    """Match a matrix header like '001' to the single hospital ID ending in '-001'.
    Every such match is listed in the import report."""


class DatetimePolicy(BaseModel):
    """How roster/shift values without a UTC offset are interpreted. Events never use this:
    event timestamps without an offset are always rejected."""

    naive_timezone: str | None = None
    """Explicit IANA zone for offset-less roster values. Takes precedence when set."""
    infer_from_event_stream_offset: bool = True
    """If every event timestamp shares one UTC offset, use it (reported as a warning)."""

    @field_validator("naive_timezone")
    @classmethod
    def _zone(cls, value: str | None) -> str | None:
        return validate_timezone(value) if value else value


class SnapshotLabels(BaseModel):
    """Display labels used in reference snapshots, mapped to internal values."""

    activity_labels: dict[str, str] = Field(
        default_factory=lambda: {
            "available": "available",
            "video_consult_in_progress": "video_consult",
            "video_consult": "video_consult",
            "incoming_hospital_call": "incoming_call",
            "incoming_call": "incoming_call",
            "outgoing_hospital_call": "outgoing_call",
            "outgoing_call": "outgoing_call",
            "documentation_note": "documentation",
            "documentation": "documentation",
            "camera_active_no_synapse_session": "external_video_suspected",
            "external_video_suspected": "external_video_suspected",
            "in_meeting": "in_meeting",
            "temporarily_unavailable": "temporarily_unavailable",
            "off_shift": "off_shift",
        }
    )
    stage_labels: dict[str, str] = Field(
        default_factory=lambda: {
            "received": "received",
            "triaged": "triaged",
            "assigned": "assigned",
            "provider_contacted": "provider_contacted",
            "ct_cta_or_imaging_pending": "imaging_pending",
            "imaging_pending": "imaging_pending",
            "imaging_review": "imaging_review",
            "video_consult_in_progress": "video_in_progress",
            "video_in_progress": "video_in_progress",
            "note_pending": "note_pending",
            "documentation": "documentation",
            "signed_off": "signed_off",
        }
    )
    unassigned_values: list[str] = Field(
        default_factory=lambda: ["", "unassigned", "none", "n_a", "na"]
    )


def _default_tables() -> dict[str, dict[str, ColumnSpec]]:
    return {
        LogicalTable.EVENT_STREAM: {
            "event_id": _col("event_id", "event", "id", required=True),  # "Event" (brief)
            "event_type": _col("event_type", "type", required=True),  # "Type" (brief)
            "event_time": _col("event_time", required=True),  # documented field name
            "ingested_at": _col("ingested_at", "ingested", required=True),  # documented
            "consult_id": _col("consult_id", "consult"),  # "Consult" (brief)
            "physician_id": _col("physician_id", "phys", "physician"),  # "Phys." (brief)
            "hospital_id": _col("hospital_id", "hosp", "hospital"),  # "Hosp." (brief)
            "description": _col("description", "details", "detail"),
            "status": _col("status", "new_status", "self_reported_status"),
            "consult_type": _col("consult_type"),
            "priority": _col("priority", "consult_priority"),
        },
        LogicalTable.HOSPITALS: {
            "hospital_id": _col("hospital_id", "id", required=True),
            "name": _col("name", "hospital_name", "hospital"),
            "timezone": _col(
                "timezone",
                "time_zone",
                "tz",
                "local_time_zone",
                "local_timezone",
                required=True,
            ),
            "coverage_tier": _col("coverage_tier", "tier", "coverage_level"),
        },
        LogicalTable.PHYSICIANS_ON_SHIFT: {
            "physician_id": _col("physician_id", "id", required=True),
            "display_name": _col("name", "physician_name", "physician", "display_name"),
            "shift_start": _col(
                "shift_start",
                "shift_start_time",
                "shift_starts",
                "shift_start_at",
                "start",
                "start_time",
            ),
            "shift_end": _col(
                "shift_end",
                "shift_end_time",
                "shift_ends",
                "shift_end_at",
                "end",
                "end_time",
            ),
            "shift": _col("shift", "shift_window", "shift_hours"),  # "Shift (ET)" (brief)
            "roster_role": _col("role", "roster_role"),
        },
        LogicalTable.PHYSICIANS_OFF_SHIFT: {
            "physician_id": _col("physician_id", "id", required=True),
            "display_name": _col("name", "physician_name", "physician", "display_name"),
            "roster_role": _col("role", "roster_role"),
            "split_shift_opt_in": _col("opt_in", "split_shift_opt_in", "opted_in"),
            "last_shift_ended_at": _col(
                "last_shift_ended", "last_shift_ended_at", "last_shift_end"
            ),
            "next_shift_starts_at": _col(
                "next_shift_starts", "next_shift_starts_at", "next_shift_start"
            ),
            "hours_worked_trailing_7d": _col(
                "hrs_7d",
                "hours_7d",
                "hours_worked_7d",
                "hours_worked_trailing_7d",
                "hours_worked_last_7d",
            ),
            "minutes_to_come_online": _col(
                "min_to_online",
                "minutes_to_online",
                "minutes_to_come_online",
                "time_to_online_min",
                "est_minutes_to_online",
            ),
            "notification_channel": _col("channel", "notification_channel", "preferred_channel"),
            "offers_declined_30d": _col(
                "declined_30d", "offers_declined_30d", "offers_declined_last_30d"
            ),
        },
        LogicalTable.CREDENTIALING: {
            "physician_id": _col("physician_id", "physician", "id", required=True),
            "display_name": _col("name", "physician_name", "display_name"),
            # Long format only (one row per physician-hospital pair):
            "hospital_id": _col("hospital_id"),
            "credentialed": _col("credentialed", "is_credentialed"),
        },
        LogicalTable.BASELINE_VOLUME: {
            "hospital_id": _col("hospital_id", "hospital", required=True),
            # "hour_start_et" matches "hour_start" with zone hint "et" (converted to local).
            "hour_local": _col(
                "hour", "hour_of_day", "hour_local", "local_hour", "hour_start", required=True
            ),
            "mean_consults": _col(
                "mean", "mean_consults", "mean_volume", "avg_consults", required=True
            ),
            "p90_consults": _col("p90", "p90_consults", "p90_volume", required=True),
            "day_type": _col("day_type", "dow_type"),
        },
        LogicalTable.COVERAGE_REQUIREMENTS: {
            "hospital_id": _col("hospital_id", "hospital", required=True),
            "block_start": _col(
                "block_start", "block_start_local", "time_block_start", "start", "start_time"
            ),
            "block_end": _col("block_end", "block_end_local", "time_block_end", "end", "end_time"),
            "block": _col("time_block", "block", "window"),
            "min_available_physicians": _col(
                "min_available_physicians",
                "min_physicians",
                "minimum_physicians",
                "min_available",
                "required_physicians",
                "min_credentialed_available",
                "min_available_credentialed_physicians",
                required=True,
            ),
            "day_type": _col("day_type"),
        },
        "snapshot_physicians": {
            "physician_id": _col("physician_id", "id", "physician"),
            "derived_state": _col("derived_state", "derived", "activity", "state"),
            "self_reported": _col("self_reported", "self_reported_status"),
            "agent": _col("agent", "agent_status"),
            "consults": _col("cons", "consults", "consult_count", "consults_this_shift"),
            "calls": _col("calls", "call_count", "calls_this_shift"),
            "open_consults": _col("open", "open_consults"),
            "minutes_to_end": _col("min_to_end", "minutes_to_end", "minutes_to_shift_end"),
        },
        "snapshot_consults": {
            "consult_id": _col("consult_id", "consult"),
            "hospital": _col("hospital_id", "hospital"),
            "physician": _col("physician_id", "physician"),
            "consult_type": _col("consult_type", "type"),
            "stage": _col("current_stage", "stage"),
            "minutes_in_stage": _col("min_in_stage", "minutes_in_stage"),
            "minutes_since_received": _col("min_since_received", "minutes_since_received"),
        },
    }


class DatasetMapping(BaseModel):
    file_patterns: dict[str, list[str]] = Field(
        default_factory=lambda: {
            LogicalTable.EVENT_STREAM: ["event_stream*.csv"],
            LogicalTable.HOSPITALS: ["hospitals*.csv"],
            LogicalTable.PHYSICIANS_ON_SHIFT: ["physicians_on_shift*.csv"],
            LogicalTable.PHYSICIANS_OFF_SHIFT: ["physicians_off_shift*.csv"],
            LogicalTable.CREDENTIALING: ["credentialing*.csv"],
            LogicalTable.BASELINE_VOLUME: ["baseline*.csv"],
            LogicalTable.COVERAGE_REQUIREMENTS: ["coverage_requirements*.csv"],
            LogicalTable.REFERENCE_SNAPSHOT: ["snapshot*.csv"],
        }
    )
    required_tables: list[str] = Field(
        default_factory=lambda: [
            LogicalTable.EVENT_STREAM,
            LogicalTable.HOSPITALS,
            LogicalTable.PHYSICIANS_ON_SHIFT,
            LogicalTable.CREDENTIALING,
        ]
    )
    """Files the replay cannot work without. The other documented files are validated
    when present, and their absence is reported as a warning."""
    tables: dict[str, dict[str, ColumnSpec]] = Field(default_factory=_default_tables)
    events: EventParsingRules = Field(default_factory=EventParsingRules)
    true_values: list[str] = Field(default_factory=lambda: ["y", "yes", "true", "t", "1", "x"])
    false_values: list[str] = Field(default_factory=lambda: ["", "n", "no", "false", "f", "0"])
    timezone_labels: dict[str, str] = Field(
        default_factory=lambda: {
            "et": "America/New_York",
            "eastern": "America/New_York",
            "est": "America/New_York",
            "edt": "America/New_York",
            "us_eastern": "America/New_York",
            "ct": "America/Chicago",
            "central": "America/Chicago",
            "cst": "America/Chicago",
            "cdt": "America/Chicago",
            "us_central": "America/Chicago",
            "mt": "America/Denver",
            "mountain": "America/Denver",
            "mdt": "America/Denver",
            "us_mountain": "America/Denver",
            "pt": "America/Los_Angeles",
            "pacific": "America/Los_Angeles",
            "pst": "America/Los_Angeles",
            "pdt": "America/Los_Angeles",
            "us_pacific": "America/Los_Angeles",
            "az": "America/Phoenix",
            "arizona": "America/Phoenix",
            "us_arizona": "America/Phoenix",
            "utc": "UTC",
            "gmt": "UTC",
            "z": "UTC",
        }
    )
    """Non-IANA labels accepted for hospital time zones and header suffixes like
    'shift_et'. Each use is reported. Ambiguous labels (e.g. MST) are deliberately absent."""
    datetimes: DatetimePolicy = Field(default_factory=DatetimePolicy)
    credentialing: CredentialingOptions = Field(default_factory=CredentialingOptions)
    snapshot: SnapshotLabels = Field(default_factory=SnapshotLabels)
    max_event_rejection_ratio: float = Field(default=0.05, ge=0, le=1)
    """Above this share of invalid event rows the import fails instead of quarantining."""
    max_reported_issues: int = Field(default=300, ge=10)

    @field_validator("timezone_labels")
    @classmethod
    def _labels(cls, labels: dict[str, str]) -> dict[str, str]:
        return {normalize_label(k): validate_timezone(v) for k, v in labels.items()}

    def columns(self, table: str) -> dict[str, ColumnSpec]:
        return self.tables[str(table)]


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_mapping(override_file: Path | None = None) -> DatasetMapping:
    """Defaults, deep-merged with an optional JSON override file."""
    if override_file is None:
        return DatasetMapping()
    override = json.loads(override_file.read_text(encoding="utf-8"))
    base = DatasetMapping().model_dump(mode="json")
    return DatasetMapping.model_validate(_deep_merge(base, override))
