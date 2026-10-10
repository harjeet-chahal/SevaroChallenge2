"""Operational events — the source of truth from which all live state is rebuilt.

Every event carries two timestamps:
- ``event_time``: when it happened (orders state transitions)
- ``ingested_at``: when the system learned about it (decides visibility at time T)
Ordering by arrival alone is wrong because events can arrive late.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import AwareDatetime, Field

from app.schemas.common import ApiModel, EntityId


class KnownEventType(StrEnum):
    """Event types documented in the challenge brief.

    ``event_type`` fields are plain strings so unknown types are stored and reported
    rather than rejected or dropped. Only these types drive state transitions.
    """

    CONSULT_RECEIVED = "consult_received"
    CONSULT_TRIAGED = "consult_triaged"
    PHYSICIAN_ASSIGNED = "physician_assigned"
    INCOMING_CALL_RINGING = "incoming_call_ringing"
    INCOMING_CALL_STARTED = "incoming_call_started"
    INCOMING_CALL_ENDED = "incoming_call_ended"
    OUTGOING_CALL_STARTED = "outgoing_call_started"
    OUTGOING_CALL_ENDED = "outgoing_call_ended"
    IMAGING_REQUESTED = "imaging_requested"
    IMAGING_RETURNED = "imaging_returned"
    VIDEO_STARTED = "video_started"
    VIDEO_ENDED = "video_ended"
    NOTE_STARTED = "note_started"
    NOTE_SIGNED = "note_signed"
    ROUTING_ATTEMPT_FAILED = "routing_attempt_failed"
    PHYSICIAN_STATUS_CHANGED = "physician_status_changed"
    CAMERA_ACTIVE = "camera_active"
    CAMERA_INACTIVE = "camera_inactive"
    AGENT_HEARTBEAT_LOST = "agent_heartbeat_lost"
    SHIFT_STARTED = "shift_started"


KNOWN_EVENT_TYPES: frozenset[str] = frozenset(t.value for t in KnownEventType)


class EventSource(StrEnum):
    DATASET_IMPORT = "dataset_import"
    LIVE_INGEST = "live_ingest"
    WORKFLOW = "workflow"
    """Recorded by an applied Phase 5 intervention (e.g. a coordinator reassignment). A
    simulated Synapse action, kept distinguishable from imported source events."""


class NormalizedEvent(ApiModel):
    """An event after validation. Timestamps are UTC; the original strings are kept."""

    event_id: EntityId
    event_type: str = Field(min_length=1)
    event_time: AwareDatetime
    ingested_at: AwareDatetime
    event_time_raw: str
    ingested_at_raw: str
    consult_id: EntityId | None = None
    physician_id: EntityId | None = None
    hospital_id: EntityId | None = None
    description: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    """Typed values extracted per event type (e.g. ``status``) plus unmapped source columns."""
    raw: dict[str, Any] = Field(default_factory=dict)
    """The source record exactly as received, for debugging."""
    source: EventSource
    source_file: str | None = None
    source_row: int | None = None
    content_hash: str
    """Hash of the event's meaning (excludes id, ingest time and source) for duplicate checks."""

    @property
    def is_known_type(self) -> bool:
        return self.event_type in KNOWN_EVENT_TYPES


class StoredEvent(NormalizedEvent):
    sequence: int = Field(ge=0)
    """Insertion order in the event log; the final tie-breaker."""
    import_id: EntityId | None = None


class DedupeStatus(StrEnum):
    CANONICAL = "canonical"
    DUPLICATE = "duplicate"
    CONFLICTING_DUPLICATE = "conflicting_duplicate"
    """Same event_id as an earlier copy but different content. The first copy wins."""


class EventView(StoredEvent):
    """An event annotated for the history/debug view at a given ``as_of``."""

    recognized: bool
    dedupe_status: DedupeStatus
    duplicate_of_sequence: int | None = None
    ingest_lag_seconds: float
    arrived_out_of_order: bool
    """True when an event with a later ``event_time`` had already been ingested."""
    visible: bool
    """Known at ``as_of``: ingested_at <= as_of and event_time <= as_of."""
    applied: bool
    """Visible, canonical and of a known type — i.e. it drove state at ``as_of``."""


class EventPage(ApiModel):
    as_of: AwareDatetime
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
    items: list[EventView]


class EventInput(ApiModel):
    """Body for live event injection. Field names match the dataset's event columns."""

    event_id: str
    event_type: str
    event_time: str
    """ISO-8601 with a UTC offset, e.g. 2030-05-14T17:31:00-04:00."""
    ingested_at: str | None = None
    """Defaults to the current simulation time."""
    consult_id: str | None = None
    physician_id: str | None = None
    hospital_id: str | None = None
    description: str | None = None
    status: str | None = None
    """For physician_status_changed: Available, In Meeting or Temporarily Unavailable."""
    consult_type: str | None = None
    priority: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class FieldIssue(ApiModel):
    field: str | None = None
    message: str


class EventIngestOutcome(ApiModel):
    index: int
    event_id: str | None
    status: Literal["accepted", "duplicate", "conflicting_duplicate", "rejected"]
    errors: list[FieldIssue] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    visible_now: bool | None = None
    """Whether the event is already known at the current simulation time."""


class EventIngestResult(ApiModel):
    received: int = Field(ge=0)
    accepted: int = Field(ge=0)
    duplicates: int = Field(ge=0)
    rejected: int = Field(ge=0)
    simulation_time: AwareDatetime | None
    outcomes: list[EventIngestOutcome]


class EventRejection(ApiModel):
    """A record that failed validation. Kept so nothing is silently discarded."""

    id: int
    source: EventSource
    import_id: EntityId | None = None
    source_file: str | None = None
    source_row: int | None = None
    event_id: str | None = None
    event_type: str | None = None
    errors: list[FieldIssue]
    raw: dict[str, Any]
    recorded_at: AwareDatetime
