"""Accumulate raw physician signals from events, then derive state at ``as_of``.

Signals are tracked independently (a physician can be on a call *and* have the camera
on *and* have a phone ringing); ``availability.decide_availability`` reconciles them.
Consult lifecycles are not touched here.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime

from app.engines.physician_state.availability import AvailabilityInputs, decide_availability
from app.schemas.common import Severity
from app.schemas.consultation import ConsultationState, ConsultStage, StateAnomaly
from app.schemas.event import KnownEventType as E
from app.schemas.event import StoredEvent
from app.schemas.physician import (
    ActiveSession,
    Physician,
    PhysicianState,
    PresenceSignals,
    SelfReportedStatus,
    SignalFlag,
)

NO_CONSULT = "-"


@dataclass
class PhysicianSignals:
    physician_id: str
    status: SelfReportedStatus = SelfReportedStatus.UNKNOWN
    status_since: datetime | None = None
    status_event: str | None = None
    agent_online: bool | None = None
    agent_since: datetime | None = None
    agent_event: str | None = None
    agent_inferred: bool = False
    camera_active: bool | None = None
    camera_since: datetime | None = None
    camera_event: str | None = None
    calls: dict[str, ActiveSession] = field(default_factory=dict)
    videos: dict[str, ActiveSession] = field(default_factory=dict)
    ringing: dict[str, ActiveSession] = field(default_factory=dict)
    last_call_ended_at: datetime | None = None
    shift_started_at: datetime | None = None
    shift_event: str | None = None
    call_starts: list[tuple[datetime, str]] = field(default_factory=list)
    assignments: dict[str, datetime] = field(default_factory=dict)
    anomalies: list[StateAnomaly] = field(default_factory=list)

    def anomaly(self, code: str, message: str, event: StoredEvent) -> None:
        self.anomalies.append(
            StateAnomaly(
                code=code,
                message=message,
                event_id=event.event_id,
                consult_id=event.consult_id,
                physician_id=self.physician_id,
            )
        )


def _session(kind: str, event: StoredEvent) -> ActiveSession:
    return ActiveSession(
        kind=kind,  # type: ignore[arg-type]
        consult_id=event.consult_id,
        hospital_id=event.hospital_id,
        since=event.event_time,
        event_id=event.event_id,
    )


class PhysicianStateTracker:
    def __init__(self) -> None:
        self._signals: dict[str, PhysicianSignals] = {}

    @property
    def physician_ids(self) -> list[str]:
        return sorted(self._signals)

    def signals(self, physician_id: str) -> PhysicianSignals | None:
        return self._signals.get(physician_id)

    def apply(self, event: StoredEvent) -> None:
        pid = event.physician_id
        if not pid:
            return
        s = self._signals.setdefault(pid, PhysicianSignals(physician_id=pid))
        t = event.event_type
        key = event.consult_id or NO_CONSULT

        if t == E.PHYSICIAN_STATUS_CHANGED:
            s.status = SelfReportedStatus(event.payload.get("status", SelfReportedStatus.UNKNOWN))
            s.status_since, s.status_event = event.event_time, event.event_id
        elif t in (E.CAMERA_ACTIVE, E.CAMERA_INACTIVE):
            s.camera_active = t == E.CAMERA_ACTIVE
            s.camera_since, s.camera_event = event.event_time, event.event_id
            if s.agent_online is False:
                # Camera events come from the desktop agent, so it is reporting again.
                s.agent_online, s.agent_inferred = True, True
                s.agent_since, s.agent_event = event.event_time, event.event_id
        elif t == E.AGENT_HEARTBEAT_LOST:
            s.agent_online, s.agent_inferred = False, False
            s.agent_since, s.agent_event = event.event_time, event.event_id
        elif t == E.INCOMING_CALL_RINGING:
            s.ringing[event.consult_id or event.event_id] = _session("ringing", event)
        elif t in (E.INCOMING_CALL_STARTED, E.OUTGOING_CALL_STARTED):
            direction = "incoming" if t == E.INCOMING_CALL_STARTED else "outgoing"
            if direction == "incoming":
                s.ringing.pop(key, None)
            s.calls[f"{direction}:{key}"] = _session(f"{direction}_call", event)
            s.call_starts.append((event.event_time, event.event_id))
        elif t in (E.INCOMING_CALL_ENDED, E.OUTGOING_CALL_ENDED):
            direction = "incoming" if t == E.INCOMING_CALL_ENDED else "outgoing"
            if direction == "incoming":
                s.ringing.pop(key, None)
            self._end_session(s.calls, f"{direction}:{key}", f"{direction}:", event, s)
            s.last_call_ended_at = event.event_time
        elif t == E.VIDEO_STARTED:
            s.videos[key] = _session("video", event)
        elif t == E.VIDEO_ENDED:
            self._end_session(s.videos, key, "", event, s)
        elif t == E.SHIFT_STARTED:
            s.shift_started_at, s.shift_event = event.event_time, event.event_id
        elif t == E.PHYSICIAN_ASSIGNED and event.consult_id:
            s.assignments.setdefault(event.consult_id, event.event_time)

    @staticmethod
    def _end_session(
        sessions: dict[str, ActiveSession],
        key: str,
        prefix: str,
        event: StoredEvent,
        s: PhysicianSignals,
    ) -> None:
        if sessions.pop(key, None) is not None:
            return
        # An end without a consult id closes the only open session of that kind, if unambiguous.
        candidates = [k for k in sessions if k.startswith(prefix)]
        if event.consult_id is None and len(candidates) == 1:
            sessions.pop(candidates[0])
            return
        s.anomaly(
            "session_end_without_start",
            f"{event.event_type} has no matching open session; ignored",
            event,
        )


def _resolve_shift(
    profile: Physician | None, signals: PhysicianSignals | None, as_of: datetime
) -> tuple[bool | None, int | None, str | None, list[SignalFlag]]:
    """Return (on_shift, minutes_to_shift_end, note, flags)."""
    flags: list[SignalFlag] = []
    started = signals.shift_started_at if signals else None
    scheduled = profile.schedule.current_shift if profile else None

    if scheduled is not None:
        within = scheduled.start <= as_of < scheduled.end
        started_early = started is not None and started <= as_of < scheduled.end
        if within or started_early:
            minutes = int((scheduled.end - as_of).total_seconds() // 60)
            return True, minutes, "On shift per roster schedule.", flags
        return False, None, "Outside the scheduled shift.", flags
    if started is not None and started <= as_of:
        return True, None, "On shift: shift_started event (no scheduled end).", flags
    next_start = profile.schedule.next_shift_starts_at if profile else None
    if next_start is not None and next_start <= as_of:
        flags.append(
            SignalFlag(
                code="shift_assumed_from_roster",
                message="Assumed on shift from the roster's next shift start; no shift_started "
                "event and no known end time.",
                severity=Severity.INFO,
            )
        )
        return True, None, "Assumed on shift from roster next-shift start.", flags
    if profile is not None and profile.roster != "unlisted":
        return False, None, "Not scheduled on shift.", flags
    return None, None, "Shift unknown (not in any roster).", flags


def _since(times: Iterable[datetime], anchor: datetime | None) -> int:
    return sum(1 for t in times if anchor is None or t >= anchor)


def build_physician_state(
    physician_id: str,
    *,
    profile: Physician | None,
    signals: PhysicianSignals | None,
    consults: Iterable[ConsultationState],
    as_of: datetime,
) -> PhysicianState:
    s = signals or PhysicianSignals(physician_id=physician_id)
    on_shift, minutes_to_end, shift_note, shift_flags = _resolve_shift(profile, signals, as_of)

    mine = [c for c in consults if c.assigned_physician_id == physician_id and c.is_open]
    open_ids = sorted(c.consult_id for c in mine)
    documentation = sorted(c.consult_id for c in mine if c.stage is ConsultStage.DOCUMENTATION)

    calls = sorted(s.calls.values(), key=lambda x: (x.since, x.event_id))
    videos = sorted(s.videos.values(), key=lambda x: (x.since, x.event_id))
    ringing = sorted(s.ringing.values(), key=lambda x: (x.since, x.event_id))

    decision = decide_availability(
        AvailabilityInputs(
            status=s.status,
            agent_online=s.agent_online,
            agent_online_inferred=s.agent_inferred,
            camera_active=s.camera_active,
            active_calls=calls,
            active_videos=videos,
            ringing=ringing,
            on_shift=on_shift,
            documentation_consult_ids=documentation,
            in_roster=profile is not None and profile.roster != "unlisted",
            shift_note=shift_note,
        )
    )

    scheduled = profile.schedule.current_shift if profile else None
    anchors = [t for t in (scheduled.start if scheduled else None, s.shift_started_at) if t]
    shift_anchor = min(anchors) if anchors else None
    evidence = [
        e for e in (s.status_event, s.agent_event, s.camera_event, s.shift_event) if e is not None
    ] + [x.event_id for x in (*calls, *videos, *ringing)]

    return PhysicianState(
        physician_id=physician_id,
        display_name=profile.display_name if profile else physician_id,
        roster=profile.roster if profile else "unlisted",
        roster_role=profile.roster_role if profile else None,
        as_of=as_of,
        scheduled_shift=scheduled,
        shift_started_at=s.shift_started_at,
        next_shift_starts_at=profile.schedule.next_shift_starts_at if profile else None,
        on_shift=on_shift,
        minutes_to_shift_end=minutes_to_end,
        availability=decision.availability,
        activity=decision.activity,
        decision_rule=decision.rule,
        explanation=decision.explanation,
        signals=PresenceSignals(
            self_reported_status=s.status,
            status_since=s.status_since,
            agent_online=s.agent_online,
            agent_status_since=s.agent_since,
            agent_online_inferred=s.agent_inferred,
            camera_active=s.camera_active,
            camera_since=s.camera_since,
            active_calls=calls,
            active_videos=videos,
            ringing=ringing,
            last_call_ended_at=s.last_call_ended_at,
        ),
        flags=[*shift_flags, *decision.flags],
        evidence_event_ids=sorted(set(evidence)),
        consults_this_shift=_since(s.assignments.values(), shift_anchor),
        calls_this_shift=_since((t for t, _ in s.call_starts), shift_anchor),
        open_consult_ids=open_ids,
        credentialed_hospital_ids=profile.credentialed_hospital_ids if profile else [],
    )


def build_physician_states(
    tracker: PhysicianStateTracker,
    profiles: Mapping[str, Physician],
    consults: list[ConsultationState],
    as_of: datetime,
) -> list[PhysicianState]:
    ids = sorted(set(profiles) | set(tracker.physician_ids))
    return [
        build_physician_state(
            pid,
            profile=profiles.get(pid),
            signals=tracker.signals(pid),
            consults=consults,
            as_of=as_of,
        )
        for pid in ids
    ]
