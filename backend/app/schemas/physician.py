"""Physician profile (static, from the dataset) and state (derived from events).

Availability is never taken from self-reported status alone: it is reconciled from
several system signals that can disagree, so raw signals, the derived decision and the
reasoning behind it are all returned side by side.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from app.schemas.common import ApiModel, EntityId, Severity


class ShiftWindow(ApiModel):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def _end_after_start(self) -> Self:
        if self.end <= self.start:
            raise ValueError("shift end must be after shift start")
        return self


RosterKind = Literal["on_shift", "off_shift", "unlisted"]


class PhysicianSchedule(ApiModel):
    current_shift: ShiftWindow | None = None
    """Scheduled shift from the on-shift roster."""
    last_shift_ended_at: AwareDatetime | None = None
    next_shift_starts_at: AwareDatetime | None = None
    hours_worked_trailing_7d: float | None = Field(default=None, ge=0)
    minutes_to_come_online: int | None = Field(default=None, ge=0)
    offers_declined_30d: int | None = Field(default=None, ge=0)


class Physician(ApiModel):
    id: EntityId
    display_name: str
    roster: RosterKind = "unlisted"
    roster_role: str | None = None
    """Dataset-defined roster label (for example a day/night/float designation)."""
    credentialed_hospital_ids: list[EntityId] = Field(default_factory=list)
    split_shift_opt_in: bool | None = None
    notification_channel: str | None = None
    """Preferred channel label from the roster. Messages are only ever simulated."""
    schedule: PhysicianSchedule = Field(default_factory=PhysicianSchedule)
    attributes: dict[str, Any] = Field(default_factory=dict)


class SelfReportedStatus(StrEnum):
    AVAILABLE = "available"
    IN_MEETING = "in_meeting"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    UNKNOWN = "unknown"


class Availability(StrEnum):
    """Routing view of a physician. Precedence rules live in engines/physician_state."""

    BUSY = "busy"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    OFF_SHIFT = "off_shift"


class DerivedActivity(StrEnum):
    """What the physician appears to be doing, inferred from system signals."""

    AVAILABLE = "available"
    INCOMING_CALL = "incoming_call"
    OUTGOING_CALL = "outgoing_call"
    VIDEO_CONSULT = "video_consult"
    DOCUMENTATION = "documentation"
    EXTERNAL_VIDEO_SUSPECTED = "external_video_suspected"
    IN_MEETING = "in_meeting"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    OFF_SHIFT = "off_shift"


class ActiveSession(ApiModel):
    """An open call, video session or ringing phone."""

    kind: Literal["incoming_call", "outgoing_call", "video", "ringing"]
    consult_id: EntityId | None = None
    hospital_id: EntityId | None = None
    since: AwareDatetime
    event_id: EntityId


class PresenceSignals(ApiModel):
    """Raw signals as last observed. ``None`` means never observed, not false."""

    self_reported_status: SelfReportedStatus = SelfReportedStatus.UNKNOWN
    status_since: AwareDatetime | None = None
    agent_online: bool | None = None
    """False after agent_heartbeat_lost. None when no agent signal has been seen."""
    agent_status_since: AwareDatetime | None = None
    agent_online_inferred: bool = False
    """True when "online" was inferred from a later desktop-agent event, not reported."""
    camera_active: bool | None = None
    camera_since: AwareDatetime | None = None
    active_calls: list[ActiveSession] = Field(default_factory=list)
    active_videos: list[ActiveSession] = Field(default_factory=list)
    ringing: list[ActiveSession] = Field(default_factory=list)
    last_call_ended_at: AwareDatetime | None = None


class SignalFlag(ApiModel):
    """A reconciliation concern, e.g. contradictory or unverifiable signals."""

    code: str
    message: str
    severity: Severity = Severity.WARNING


class TemporaryShift(ApiModel):
    """A split shift accepted through the Phase 5 workflow. A workflow decision, not a
    source event: ``preparing`` = accepted, not yet online (never counted as current
    capacity); ``active`` = online, counted and routable inside the approved scope."""

    intervention_id: EntityId
    offer_id: EntityId
    phase: Literal["preparing", "active"]
    start_at: AwareDatetime
    end_at: AwareDatetime
    expected_online_at: AwareDatetime
    activated_at: AwareDatetime | None = None
    routing_scope_hospital_ids: list[EntityId]
    seeded_consult_count: int


class PhysicianState(ApiModel):
    physician_id: EntityId
    display_name: str
    roster: RosterKind
    roster_role: str | None = None
    as_of: AwareDatetime
    scheduled_shift: ShiftWindow | None = None
    shift_started_at: AwareDatetime | None = None
    next_shift_starts_at: AwareDatetime | None = None
    on_shift: bool | None
    """None when the physician is not in any roster and has no shift events."""
    minutes_to_shift_end: int | None = None
    availability: Availability
    activity: DerivedActivity
    decision_rule: str
    """ID of the precedence rule that decided availability (see engines/physician_state)."""
    explanation: list[str] = Field(default_factory=list)
    """Ordered, human-readable reasoning: which signals led to the decision."""
    signals: PresenceSignals
    flags: list[SignalFlag] = Field(default_factory=list)
    evidence_event_ids: list[EntityId] = Field(default_factory=list)
    consults_this_shift: int = Field(default=0, ge=0)
    calls_this_shift: int = Field(default=0, ge=0)
    open_consult_ids: list[EntityId] = Field(default_factory=list)
    credentialed_hospital_ids: list[EntityId] = Field(default_factory=list)
    routing_scope_hospital_ids: list[EntityId] | None = None
    """None = unrestricted. Set for an approved split shift (trap protection): the
    physician is counted and routed only at these hospitals."""
    temporary_shift: TemporaryShift | None = None
