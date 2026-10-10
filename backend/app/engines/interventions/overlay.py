"""Workflow overlay: accepted / activated split shifts applied on top of the replay (pure).

The event log stays the source of truth for what physicians and consults are doing. A
split shift accepted through the workflow is a *decision*, not a source event, so it is
layered on afterwards and is time-aware: at ``as_of`` an entry is

- ignored if it was accepted after ``as_of`` or had ended by then;
- **preparing** if accepted but not yet activated: the physician stays off shift and is
  never counted as current capacity; the forecast shows a *pending activation* window
  from the expected online time (uncertain, clearly labelled);
- **active** once activated: on shift until the offer ends, counted as confirmed
  coverage and routable, but only inside the approved routing scope, with the seeded
  routing count from split-shift trap protection.

Import ``apply_workflow_overlay(state, reference, entries)`` from here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.engines.replay import summarize
from app.engines.timeline import fmt_local
from app.schemas.physician import (
    Availability,
    DerivedActivity,
    ShiftWindow,
    TemporaryShift,
)
from app.schemas.state import OperationalState, ReferenceData


@dataclass(frozen=True)
class OverlayEntry:
    physician_id: str
    intervention_id: str
    offer_id: str
    start_at: datetime
    end_at: datetime
    accepted_at: datetime
    expected_online_at: datetime
    activated_at: datetime | None
    ended_at: datetime | None
    """Completed or cancelled at (None while still accepted/active)."""
    scope: tuple[str, ...]
    seeded_count: int
    minutes: int


def phase_at(entry: OverlayEntry, as_of: datetime) -> str | None:
    """'preparing', 'active' or None (not in effect at ``as_of``)."""
    if entry.accepted_at > as_of or entry.end_at <= as_of:
        return None
    if entry.ended_at is not None and entry.ended_at <= as_of:
        return None
    if entry.activated_at is not None and entry.activated_at <= as_of:
        return "active"
    return "preparing"


def apply_workflow_overlay(
    state: OperationalState, reference: ReferenceData, entries: Sequence[OverlayEntry]
) -> tuple[OperationalState, ReferenceData]:
    as_of = state.as_of
    in_effect = {}
    for e in sorted(entries, key=lambda x: (x.accepted_at, x.offer_id)):
        phase = phase_at(e, as_of)
        if phase is not None:
            in_effect[e.physician_id] = (e, phase)
    if not in_effect:
        return state, reference

    physicians = []
    for p in state.physicians:
        hit = in_effect.get(p.physician_id)
        if hit is None:
            physicians.append(p)
            continue
        e, phase = hit
        tz = next((h.timezone for h in state.hospitals if e.scope and h.id == e.scope[0]), "UTC")
        temp = TemporaryShift(
            intervention_id=e.intervention_id,
            offer_id=e.offer_id,
            phase=phase,
            start_at=e.start_at,
            end_at=e.end_at,
            expected_online_at=e.expected_online_at,
            activated_at=e.activated_at if phase == "active" else None,
            routing_scope_hospital_ids=list(e.scope),
            seeded_consult_count=e.seeded_count,
        )
        update: dict = {
            "temporary_shift": temp,
            "routing_scope_hospital_ids": list(e.scope),
        }
        if phase == "active":
            activated = e.activated_at or e.expected_online_at
            update.update(
                on_shift=True,
                scheduled_shift=ShiftWindow(start=activated, end=e.end_at),
                minutes_to_shift_end=int((e.end_at - as_of).total_seconds() // 60),
                explanation=[
                    *p.explanation,
                    f"Split shift activated at {fmt_local(activated, tz)} through the approved "
                    f"workflow ({e.intervention_id}); on shift until {fmt_local(e.end_at, tz)}, "
                    f"routable only at {', '.join(e.scope)}.",
                ],
            )
            if p.availability is Availability.OFF_SHIFT:
                update.update(
                    availability=Availability.AVAILABLE,
                    activity=DerivedActivity.AVAILABLE,
                    decision_rule="split_shift_activated",
                )
        else:
            update["explanation"] = [
                *p.explanation,
                f"Accepted a split shift ({e.intervention_id}); preparing to come online, "
                f"expected at {fmt_local(e.expected_online_at, tz)}. Not active capacity yet.",
            ]
        physicians.append(p.model_copy(update=update))

    profiles = []
    for prof in reference.physicians:
        hit = in_effect.get(prof.id)
        if hit is None:
            profiles.append(prof)
            continue
        e, phase = hit
        schedule = prof.schedule
        hours = schedule.hours_worked_trailing_7d
        nxt = schedule.next_shift_starts_at
        sched_update: dict = {
            # The committed split shift counts toward the 60 h rolling limit ...
            "hours_worked_trailing_7d": None if hours is None else hours + e.minutes / 60,
        }
        if phase == "preparing":
            # ... and blocks overlapping offers like a scheduled shift would.
            sched_update["next_shift_starts_at"] = min(nxt, e.start_at) if nxt else e.start_at
        profiles.append(
            prof.model_copy(update={"schedule": schedule.model_copy(update=sched_update)})
        )

    new_state = state.model_copy(
        update={
            "physicians": physicians,
            "summary": summarize(physicians, state.consultations),
        }
    )
    new_reference = reference.model_copy(update={"physicians": profiles})
    return new_state, new_reference
