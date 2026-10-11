"""Consult lifecycle transition rules (pure).

Documented lifecycle: Received -> Triaged -> Assigned -> Provider Contacted ->
CT/CTA or Imaging Pending -> Imaging Review -> Video Consult In Progress -> Note Pending
-> Documentation -> Signed Off. Not every consult passes through every stage.

Rules:
1. Each lifecycle event names a *target* stage. A consult moves forward to it,
   skipping stages if needed (e.g. phone-only consults skip video).
2. A target earlier than the current stage is not applied; an ``out_of_sequence``
   anomaly is recorded and the stage is kept. State is never corrupted.
3. A call *starting* moves Assigned -> Provider Contacted; later calls (e.g. checking
   imaging status) don't change the stage.
4. A call *ending* while the consult is still at Provider Contacted, or at Imaging Review
   (scans back, then a phone-only consult), means the call was the clinical interaction,
   so the consult moves to Note Pending — *provisionally*. A later imaging or video event
   overrides a provisional Note Pending.
5. Nothing changes after Signed Off; later events are recorded as anomalies.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.consultation import ConsultStage as S
from app.schemas.event import KnownEventType as E

STAGE_RANK: dict[S, int] = {stage: rank for rank, stage in enumerate(S)}

TARGET_STAGE: dict[str, S] = {
    E.CONSULT_RECEIVED: S.RECEIVED,
    E.CONSULT_TRIAGED: S.TRIAGED,
    E.PHYSICIAN_ASSIGNED: S.ASSIGNED,
    E.INCOMING_CALL_STARTED: S.PROVIDER_CONTACTED,
    E.OUTGOING_CALL_STARTED: S.PROVIDER_CONTACTED,
    E.IMAGING_REQUESTED: S.IMAGING_PENDING,
    E.IMAGING_RETURNED: S.IMAGING_REVIEW,
    E.VIDEO_STARTED: S.VIDEO_IN_PROGRESS,
    E.VIDEO_ENDED: S.NOTE_PENDING,
    E.NOTE_STARTED: S.DOCUMENTATION,
    E.NOTE_SIGNED: S.SIGNED_OFF,
}

CALL_START_EVENTS = frozenset({E.INCOMING_CALL_STARTED, E.OUTGOING_CALL_STARTED})
CALL_END_EVENTS = frozenset({E.INCOMING_CALL_ENDED, E.OUTGOING_CALL_ENDED})
SUPERSEDES_PROVISIONAL = frozenset({S.IMAGING_PENDING, S.IMAGING_REVIEW, S.VIDEO_IN_PROGRESS})

# Events that tie a physician to a consult's clinical work. If a consult has no
# physician_assigned event, the first of these links the physician (flagged as inferred).
ASSIGNMENT_LINKING_EVENTS = frozenset(
    {
        E.INCOMING_CALL_STARTED,
        E.OUTGOING_CALL_STARTED,
        E.VIDEO_STARTED,
        E.VIDEO_ENDED,
        E.NOTE_STARTED,
        E.NOTE_SIGNED,
    }
)


@dataclass(frozen=True)
class TransitionDecision:
    target: S | None
    """Stage to enter, or None to keep the current stage."""
    provisional: bool = False
    anomaly_code: str | None = None
    note: str | None = None


KEEP = TransitionDecision(target=None)


def decide_transition(current: S | None, provisional: bool, event_type: str) -> TransitionDecision:
    if event_type in CALL_END_EVENTS:
        if current in (S.PROVIDER_CONTACTED, S.IMAGING_REVIEW):
            label = "Provider Contacted" if current is S.PROVIDER_CONTACTED else "Imaging Review"
            return TransitionDecision(
                target=S.NOTE_PENDING,
                provisional=True,
                note=f"call ended at {label}: interaction treated as complete (phone only)",
            )
        return KEEP

    target = TARGET_STAGE.get(event_type)
    if target is None:
        return KEEP
    if current is None:
        return TransitionDecision(target=target)
    if current is S.SIGNED_OFF:
        return TransitionDecision(
            target=None,
            anomaly_code="event_after_sign_off",
            note=f"{event_type} after the consult was signed off; ignored for stage",
        )
    if STAGE_RANK[target] > STAGE_RANK[current]:
        return TransitionDecision(target=target)
    if provisional and current is S.NOTE_PENDING and target in SUPERSEDES_PROVISIONAL:
        return TransitionDecision(
            target=target,
            note=f"{event_type} supersedes the provisional Note Pending from a call ending",
        )
    if STAGE_RANK[target] == STAGE_RANK[current]:
        return KEEP
    if event_type in CALL_START_EVENTS or event_type == E.PHYSICIAN_ASSIGNED:
        # A later call (e.g. checking CT status) or a reassignment: stage unchanged.
        return KEEP
    return TransitionDecision(
        target=None,
        anomaly_code="out_of_sequence",
        note=(
            f"{event_type} would move the consult back from {current.value} to "
            f"{target.value}; stage kept"
        ),
    )
