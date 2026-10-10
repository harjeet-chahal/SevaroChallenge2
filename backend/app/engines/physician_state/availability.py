"""Availability precedence (pure). Implements the brief's "availability is inferred" rules.

Rules are evaluated top to bottom; the first that applies decides availability:

  R1_SYNAPSE_CALL           active Synapse call (incoming or outgoing)      -> busy
  R2_SYNAPSE_VIDEO          active Synapse video session                     -> busy
  R3_OFF_SHIFT              not on shift                                     -> off_shift
  R4_TEMPORARILY_UNAVAILABLE self-reported Temporarily Unavailable           -> unavailable
  R5_CAMERA_NO_SYNAPSE      camera active, no Synapse video, not In Meeting  -> busy
                            (probably on an external video platform; flagged)
  R6_CAMERA_IN_MEETING      camera active while In Meeting                   -> available
                            (internal meetings are interruptible)
  R7_IN_MEETING             In Meeting, camera not active                    -> available
  R8_AGENT_OFFLINE          desktop agent offline                            -> available
                            (routing assumes available; flagged as unverified)
  R9_DOCUMENTATION          writing a note (consult in Documentation)       -> available
                            (documentation is not a busy signal in the routing rules)
  R10_DEFAULT               none of the above                                -> available

Camera rules (R5/R6) only apply while the agent is online: an offline agent means the
camera state is unknown. Every input signal is echoed in the explanation, including the
ones a higher-priority rule overrode.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.schemas.common import Severity
from app.schemas.physician import (
    ActiveSession,
    Availability,
    DerivedActivity,
    SelfReportedStatus,
    SignalFlag,
)


@dataclass(frozen=True)
class AvailabilityInputs:
    status: SelfReportedStatus
    agent_online: bool | None
    """None means no agent signal was ever seen; treated as online (nothing reported lost)."""
    agent_online_inferred: bool
    camera_active: bool | None
    active_calls: Sequence[ActiveSession]
    active_videos: Sequence[ActiveSession]
    ringing: Sequence[ActiveSession]
    on_shift: bool | None
    documentation_consult_ids: Sequence[str] = ()
    in_roster: bool = True
    shift_note: str | None = None


@dataclass
class AvailabilityDecision:
    availability: Availability
    activity: DerivedActivity
    rule: str
    explanation: list[str] = field(default_factory=list)
    flags: list[SignalFlag] = field(default_factory=list)


def _sessions(sessions: Sequence[ActiveSession]) -> str:
    return ", ".join(s.consult_id or "no consult" for s in sessions)


def decide_availability(i: AvailabilityInputs) -> AvailabilityDecision:
    agent_offline = i.agent_online is False
    camera_known = i.camera_active is not None and not agent_offline
    camera_on = bool(i.camera_active) and not agent_offline
    in_meeting = i.status is SelfReportedStatus.IN_MEETING

    observed: list[str] = [
        f"Self-reported status: {i.status.value}.",
        f"Desktop agent: {'offline' if agent_offline else 'online'}"
        + (" (inferred from a later desktop-agent event)" if i.agent_online_inferred else "")
        + (" (no heartbeat loss reported)" if i.agent_online is None else "")
        + ".",
    ]
    if agent_offline:
        observed.append("Camera: unknown (agent offline).")
    elif camera_known:
        observed.append(f"Camera: {'active' if camera_on else 'inactive'}.")
    if i.active_calls:
        observed.append(f"Active Synapse call(s): {_sessions(i.active_calls)}.")
    if i.active_videos:
        observed.append(f"Active Synapse video: {_sessions(i.active_videos)}.")
    if i.ringing:
        observed.append(f"Phone ringing for: {_sessions(i.ringing)}.")
    if i.documentation_consult_ids:
        observed.append(f"Writing notes for: {', '.join(i.documentation_consult_ids)}.")
    if i.shift_note:
        observed.append(i.shift_note)

    flags: list[SignalFlag] = []

    def decision(
        availability: Availability, activity: DerivedActivity, rule: str, because: str
    ) -> AvailabilityDecision:
        return AvailabilityDecision(
            availability=availability,
            activity=activity,
            rule=rule,
            explanation=[*observed, f"Decision: {availability.value} — {rule}: {because}"],
            flags=flags,
        )

    if not i.in_roster:
        flags.append(
            SignalFlag(
                code="not_in_roster",
                message="Physician appears in events but in no roster file.",
            )
        )
    if i.ringing:
        flags.append(
            SignalFlag(
                code="phone_ringing",
                message=f"Phone ringing for {_sessions(i.ringing)}.",
                severity=Severity.INFO,
            )
        )
    if i.agent_online_inferred:
        flags.append(
            SignalFlag(
                code="agent_online_inferred",
                message="Agent assumed back online because a later desktop-agent event arrived.",
                severity=Severity.INFO,
            )
        )

    busy_by_synapse = bool(i.active_calls or i.active_videos)
    if busy_by_synapse:
        if i.status is SelfReportedStatus.AVAILABLE:
            flags.append(
                SignalFlag(
                    code="status_contradiction",
                    message="Self-reported Available while in a Synapse session "
                    "(status is self-reported and often stale).",
                    severity=Severity.INFO,
                )
            )
        if agent_offline:
            flags.append(
                SignalFlag(
                    code="agent_offline",
                    message="Desktop agent offline; camera state unknown.",
                    severity=Severity.INFO,
                )
            )

    if i.active_calls:
        incoming = any(s.kind == "incoming_call" for s in i.active_calls)
        return decision(
            Availability.BUSY,
            DerivedActivity.INCOMING_CALL if incoming else DerivedActivity.OUTGOING_CALL,
            "R1_SYNAPSE_CALL",
            "an active Synapse call means busy; it overrides every lower-priority signal.",
        )
    if i.active_videos:
        return decision(
            Availability.BUSY,
            DerivedActivity.VIDEO_CONSULT,
            "R2_SYNAPSE_VIDEO",
            "an active Synapse video session means busy.",
        )
    if i.on_shift is False:
        return decision(
            Availability.OFF_SHIFT,
            DerivedActivity.OFF_SHIFT,
            "R3_OFF_SHIFT",
            "not on shift, so not routable.",
        )
    if i.status is SelfReportedStatus.TEMPORARILY_UNAVAILABLE:
        return decision(
            Availability.UNAVAILABLE,
            DerivedActivity.TEMPORARILY_UNAVAILABLE,
            "R4_TEMPORARILY_UNAVAILABLE",
            "self-reported Temporarily Unavailable.",
        )
    if camera_on and not in_meeting:
        flags.append(
            SignalFlag(
                code="external_video_suspected",
                message="Camera active with no Synapse video and not In Meeting: probably on "
                "an external video platform.",
            )
        )
        return decision(
            Availability.BUSY,
            DerivedActivity.EXTERNAL_VIDEO_SUSPECTED,
            "R5_CAMERA_NO_SYNAPSE",
            "camera active without a Synapse session and not in a meeting is treated as busy.",
        )
    if camera_on and in_meeting:
        return decision(
            Availability.AVAILABLE,
            DerivedActivity.IN_MEETING,
            "R6_CAMERA_IN_MEETING",
            "camera active while In Meeting is an internal meeting, which is interruptible.",
        )
    if in_meeting:
        return decision(
            Availability.AVAILABLE,
            DerivedActivity.IN_MEETING,
            "R7_IN_MEETING",
            "internal meetings are interruptible.",
        )

    activity = (
        DerivedActivity.DOCUMENTATION if i.documentation_consult_ids else DerivedActivity.AVAILABLE
    )
    if agent_offline:
        flags.append(
            SignalFlag(
                code="availability_unverified",
                message="Desktop agent offline: routing assumes available, but this is "
                "unverified (camera state unknown).",
            )
        )
        return decision(
            Availability.AVAILABLE,
            activity,
            "R8_AGENT_OFFLINE",
            "routing assumes an offline-agent physician is available; unverified.",
        )
    if i.documentation_consult_ids:
        return decision(
            Availability.AVAILABLE,
            activity,
            "R9_DOCUMENTATION",
            "writing a note is not a busy signal under the routing rules.",
        )
    return decision(
        Availability.AVAILABLE,
        activity,
        "R10_DEFAULT",
        "no busy or unavailable signal is active.",
    )
