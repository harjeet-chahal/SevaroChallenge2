"""Validate one raw event record and turn it into a ``NormalizedEvent``.

Used by both dataset import (CSV rows, after column mapping) and live injection (JSON),
so both paths produce identical events and identical error messages.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, TypeAdapter, ValidationError, field_validator

from app.core.time import NaiveDatetimeError, parse_iso_aware, to_utc
from app.engines.event_processing.catalog import REQUIRED_FIELDS
from app.schemas.common import EntityId
from app.schemas.event import (
    KNOWN_EVENT_TYPES,
    EventSource,
    FieldIssue,
    KnownEventType,
    NormalizedEvent,
)
from app.schemas.physician import SelfReportedStatus
from app.schemas.simulation import SUPPORTED_RANGE, is_supported_time

CANONICAL_EVENT_FIELDS: tuple[str, ...] = (
    "event_id",
    "event_type",
    "event_time",
    "ingested_at",
    "consult_id",
    "physician_id",
    "hospital_id",
    "description",
    "status",
    "consult_type",
    "priority",
)


def normalize_label(text: str) -> str:
    """'In Meeting' -> 'in_meeting', 'CT/CTA or Imaging Pending' -> 'ct_cta_or_imaging_pending'."""
    return re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")


class EventParsingRules(BaseModel):
    """Adjustable rules for reading event payloads. Part of the dataset mapping config."""

    status_labels: dict[str, SelfReportedStatus] = Field(
        default_factory=lambda: {
            "available": SelfReportedStatus.AVAILABLE,
            "in_meeting": SelfReportedStatus.IN_MEETING,
            "temporarily_unavailable": SelfReportedStatus.TEMPORARILY_UNAVAILABLE,
        }
    )
    """Normalized label -> status. Documented values: Available, In Meeting, Temporarily
    Unavailable."""
    status_description_pattern: str | None = r"self[- ]reported status:\s*(?P<value>.+?)\s*\.?$"
    """Fallback when there is no status column: read it from the description text,
    e.g. 'Self-reported status: Available'. Uses of this fallback are counted and reported."""
    consult_type_description_pattern: str | None = r"^\s*(?P<value>.+?)\s+consult request received"
    """Fallback for consult_received without a consult_type column, e.g.
    'Stroke consult request received'."""

    @field_validator("status_description_pattern", "consult_type_description_pattern")
    @classmethod
    def _compiles(cls, value: str | None) -> str | None:
        if value is not None:
            pattern = re.compile(value, re.IGNORECASE)
            if "value" not in pattern.groupindex:
                raise ValueError("pattern must define a named group 'value'")
        return value


DEFAULT_EVENT_RULES = EventParsingRules()

_ENTITY_ID: TypeAdapter[str] = TypeAdapter(EntityId)


class EventValidationError(ValueError):
    def __init__(self, issues: list[FieldIssue], *, event_id: str | None, event_type: str | None):
        super().__init__("; ".join(i.message for i in issues))
        self.issues = issues
        self.event_id = event_id
        self.event_type = event_type


@dataclass
class NormalizationResult:
    event: NormalizedEvent
    warnings: list[str] = field(default_factory=list)
    used_fallbacks: list[str] = field(default_factory=list)
    """Names of description-text fallbacks used (reported in import summaries)."""


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_json_safe(v) for v in value]
    return str(value)


def _issues_from(exc: ValidationError) -> list[FieldIssue]:
    """Field-level issues from a pydantic error, e.g. 'consult_id: String should have at
    most 128 characters'."""
    issues = []
    for err in exc.errors():
        name = ".".join(str(part) for part in err.get("loc", ())) or None
        message = f"{name}: {err['msg']}" if name else str(err["msg"])
        issues.append(FieldIssue(field=name, message=message))
    return issues


def _check_ids(values: Mapping[str, str | None], issues: list[FieldIssue]) -> None:
    for name, value in values.items():
        if value is None:
            continue
        try:
            _ENTITY_ID.validate_python(value)
        except ValidationError as exc:
            issues.extend(
                FieldIssue(field=name, message=f"{name}: {err['msg']} (got {len(value)})")
                for err in exc.errors()
            )


def _parse_timestamp(name: str, raw: str, issues: list[FieldIssue]) -> datetime | None:
    try:
        parsed = parse_iso_aware(raw, field=name)
        if is_supported_time(parsed):  # also keeps the UTC conversion from overflowing
            return to_utc(parsed)
        issues.append(
            FieldIssue(
                field=name,
                message=f"{name} '{raw}' is outside the supported range ({SUPPORTED_RANGE})",
            )
        )
    except NaiveDatetimeError:
        issues.append(
            FieldIssue(
                field=name,
                message=(
                    f"{name} '{raw}' has no UTC offset; event timestamps must include one "
                    "(e.g. 2030-05-14T17:30:00-04:00 or ...Z)"
                ),
            )
        )
    except ValueError:
        issues.append(
            FieldIssue(field=name, message=f"{name} '{raw}' is not a valid ISO-8601 timestamp")
        )
    return None


def content_hash(
    *,
    event_type: str,
    event_time: datetime,
    consult_id: str | None,
    physician_id: str | None,
    hospital_id: str | None,
    description: str | None,
    payload: Mapping[str, Any],
) -> str:
    """Identity of an event's *meaning*: excludes event_id, ingested_at and source."""
    body = json.dumps(
        {
            "t": event_type,
            "at": event_time.isoformat(),
            "c": consult_id,
            "p": physician_id,
            "h": hospital_id,
            "d": description,
            "x": payload,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(body.encode()).hexdigest()


def _match(pattern: str | None, text: str | None) -> str | None:
    if not pattern or not text:
        return None
    found = re.search(pattern, text, re.IGNORECASE)
    return found.group("value").strip() if found else None


def normalize_event(
    fields: Mapping[str, Any],
    *,
    source: EventSource,
    rules: EventParsingRules = DEFAULT_EVENT_RULES,
    extra: Mapping[str, Any] | None = None,
    raw: Mapping[str, Any] | None = None,
    default_ingested_at: datetime | None = None,
    source_file: str | None = None,
    source_row: int | None = None,
) -> NormalizationResult:
    """Validate canonical ``fields`` (see ``CANONICAL_EVENT_FIELDS``).

    ``extra`` holds unmapped source columns; they are preserved under
    ``payload['attributes']``. Raises ``EventValidationError`` listing every problem.
    """
    issues: list[FieldIssue] = []
    warnings: list[str] = []
    fallbacks: list[str] = []

    event_id = _clean(fields.get("event_id"))
    raw_type = _clean(fields.get("event_type"))
    event_type = raw_type.lower() if raw_type else None
    if not event_id:
        issues.append(FieldIssue(field="event_id", message="event_id is required"))
    if not event_type:
        issues.append(FieldIssue(field="event_type", message="event_type is required"))

    event_time_raw = _clean(fields.get("event_time"))
    ingested_raw = _clean(fields.get("ingested_at"))
    event_time = ingested_at = None
    if event_time_raw is None:
        issues.append(FieldIssue(field="event_time", message="event_time is required"))
    else:
        event_time = _parse_timestamp("event_time", event_time_raw, issues)
    if ingested_raw is None:
        if default_ingested_at is not None:
            ingested_at = to_utc(default_ingested_at)
            ingested_raw = default_ingested_at.isoformat()
            warnings.append("ingested_at not provided; set to the current simulation time")
        else:
            issues.append(FieldIssue(field="ingested_at", message="ingested_at is required"))
    else:
        ingested_at = _parse_timestamp("ingested_at", ingested_raw, issues)

    consult_id = _clean(fields.get("consult_id"))
    physician_id = _clean(fields.get("physician_id"))
    hospital_id = _clean(fields.get("hospital_id"))
    description = _clean(fields.get("description"))
    payload: dict[str, Any] = {}
    _check_ids(
        {
            "event_id": event_id,
            "consult_id": consult_id,
            "physician_id": physician_id,
            "hospital_id": hospital_id,
        },
        issues,
    )

    known = KnownEventType(event_type) if event_type in KNOWN_EVENT_TYPES else None
    if known is not None:
        present = {
            "consult_id": consult_id,
            "physician_id": physician_id,
            "hospital_id": hospital_id,
        }
        for name in REQUIRED_FIELDS.get(known, ()):
            if not present[name]:
                issues.append(FieldIssue(field=name, message=f"{event_type} events require {name}"))

    if known is KnownEventType.PHYSICIAN_STATUS_CHANGED:
        label = _clean(fields.get("status"))
        status_source = "column"
        if label is None:
            label = _match(rules.status_description_pattern, description)
            status_source = "description"
        if label is None:
            issues.append(
                FieldIssue(
                    field="status",
                    message=(
                        "physician_status_changed requires the new status, either in a "
                        "status column or a description like 'Self-reported status: Available'"
                    ),
                )
            )
        else:
            status = rules.status_labels.get(normalize_label(label))
            if status is None:
                accepted = ", ".join(sorted(rules.status_labels))
                issues.append(
                    FieldIssue(
                        field="status",
                        message=f"unknown status '{label}'; accepted (normalized): {accepted}",
                    )
                )
            else:
                payload["status"] = status.value
                payload["status_source"] = status_source
                if status_source == "description":
                    fallbacks.append("status_from_description")

    consult_type = _clean(fields.get("consult_type"))
    if known is KnownEventType.CONSULT_RECEIVED:
        type_source = "column"
        if consult_type is None:
            consult_type = _match(rules.consult_type_description_pattern, description)
            type_source = "description"
        if consult_type is None:
            warnings.append("consult_received has no consult type (column or description)")
        else:
            payload["consult_type_source"] = type_source
            if type_source == "description":
                fallbacks.append("consult_type_from_description")
    if consult_type is not None:
        payload["consult_type"] = consult_type

    priority = _clean(fields.get("priority"))
    if priority is not None:
        payload["priority"] = priority

    attributes = {str(k): _json_safe(v) for k, v in (extra or {}).items() if _clean(v) is not None}
    if attributes:
        payload["attributes"] = attributes

    if issues or event_time is None or ingested_at is None or not event_id or not event_type:
        raise EventValidationError(issues, event_id=event_id, event_type=event_type)

    if known is None:
        warnings.append(f"unknown event_type '{event_type}': stored and reported, not applied")
    if event_time > ingested_at:
        skew = (event_time - ingested_at).total_seconds()
        warnings.append(f"event_time is {skew:.0f}s after ingested_at (clock skew)")

    raw_record = {str(k): _json_safe(v) for k, v in (raw if raw is not None else fields).items()}
    try:
        event = NormalizedEvent(
            event_id=event_id,
            event_type=event_type,
            event_time=event_time,
            ingested_at=ingested_at,
            event_time_raw=event_time_raw or "",
            ingested_at_raw=ingested_raw or "",
            consult_id=consult_id,
            physician_id=physician_id,
            hospital_id=hospital_id,
            description=description,
            payload=payload,
            raw=raw_record,
            source=source,
            source_file=source_file,
            source_row=source_row,
            content_hash=content_hash(
                event_type=event_type,
                event_time=event_time,
                consult_id=consult_id,
                physician_id=physician_id,
                hospital_id=hospital_id,
                description=description,
                payload=payload,
            ),
        )
    except ValidationError as exc:  # any schema constraint not checked above: still a row issue
        raise EventValidationError(
            _issues_from(exc), event_id=event_id, event_type=event_type
        ) from exc
    return NormalizationResult(event=event, warnings=warnings, used_fallbacks=fallbacks)
