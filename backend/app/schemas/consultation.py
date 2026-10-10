"""Consultation lifecycle state, tracked independently of physician activity."""

from __future__ import annotations

from enum import StrEnum

from pydantic import AwareDatetime, Field

from app.schemas.common import ApiModel, EntityId


class ConsultStage(StrEnum):
    """Lifecycle stages in documented order. Not every consult passes through every stage."""

    RECEIVED = "received"
    TRIAGED = "triaged"
    ASSIGNED = "assigned"
    PROVIDER_CONTACTED = "provider_contacted"
    IMAGING_PENDING = "imaging_pending"
    IMAGING_REVIEW = "imaging_review"
    VIDEO_IN_PROGRESS = "video_in_progress"
    NOTE_PENDING = "note_pending"
    DOCUMENTATION = "documentation"
    SIGNED_OFF = "signed_off"


class ConsultStageTransition(ApiModel):
    stage: ConsultStage
    entered_at: AwareDatetime
    event_id: EntityId
    event_type: str
    provisional: bool = False
    """True for a Note Pending inferred from a call ending; later imaging/video events
    override it."""


class AssignmentChange(ApiModel):
    physician_id: EntityId
    at: AwareDatetime
    event_id: EntityId
    inferred: bool = False
    """True when no physician_assigned event exists and the link came from another event."""


class StateAnomaly(ApiModel):
    """Something unexpected in the event stream. Recorded instead of corrupting state."""

    code: str
    message: str
    event_id: EntityId | None = None
    consult_id: EntityId | None = None
    physician_id: EntityId | None = None


class ConsultationState(ApiModel):
    consult_id: EntityId
    hospital_id: EntityId | None = None
    hospital_name: str | None = None
    hospital_timezone: str | None = None
    consult_type: str | None = None
    """Dataset-defined category (e.g. stroke vs general neuro). None if not provided."""
    priority: str | None = None
    stage: ConsultStage
    is_open: bool
    assigned_physician_id: EntityId | None = None
    received_at: AwareDatetime | None = None
    stage_entered_at: AwareDatetime
    closed_at: AwareDatetime | None = None
    as_of: AwareDatetime
    seconds_in_stage: int = Field(ge=0)
    seconds_since_received: int | None = Field(default=None, ge=0)
    stage_history: list[ConsultStageTransition] = Field(default_factory=list)
    assignment_history: list[AssignmentChange] = Field(default_factory=list)
    routing_failures: int = Field(default=0, ge=0)
    last_routing_failure_at: AwareDatetime | None = None
    evidence_event_ids: list[EntityId] = Field(default_factory=list)
    anomalies: list[StateAnomaly] = Field(default_factory=list)
