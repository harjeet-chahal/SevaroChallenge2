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
  routing count from split-shift trap protection;
- **worked** once it has ended (completed, or cancelled after activation): the physician
  is back off shift, but the shift counts as their last shift for the 10 h rest rule and
  its hours count toward the rolling 7-day limit, exactly like a scheduled shift.

Import ``apply_workflow_overlay(state, reference, entries)`` from here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

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


def worked_shifts(
    entries: Sequence[OverlayEntry], as_of: datetime
) -> dict[str, list[tuple[datetime, datetime]]]:
    """physician_id -> [(online, ended)] for split shifts fully worked by ``as_of``
    (completed, or cancelled after activation)."""
    worked: dict[str, list[tuple[datetime, datetime]]] = {}
    for e in entries:
        if e.activated_at is None or e.activated_at > as_of:
            continue
        end = min(e.ended_at or e.end_at, e.end_at)
        if e.activated_at < end <= as_of:
            worked.setdefault(e.physician_id, []).append((e.activated_at, end))
    return worked


def apply_workflow_overlay(
    state: OperationalState, reference: ReferenceData, entries: Sequence[OverlayEntry]
) -> tuple[OperationalState, ReferenceData]:
    as_of = state.as_of
    in_effect = {}
    for e in sorted(entries, key=lambda x: (x.accepted_at, x.offer_id)):
        phase = phase_at(e, as_of)
        if phase is not None:
            in_effect[e.physician_id] = (e, phase)
    worked = worked_shifts(entries, as_of)
    if not in_effect and not worked:
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
        done = worked.get(prof.id, [])
        if hit is None and not done:
            profiles.append(prof)
            continue
        schedule = prof.schedule
        hours = schedule.hours_worked_trailing_7d
        sched_update: dict = {}
        if done:
            # A split shift already worked is a real shift: it resets the 10 h rest clock and
            # its hours stay in the rolling 7-day total for 7 days.
            last = max(end for _, end in done)
            previous = schedule.last_shift_ended_at
            sched_update["last_shift_ended_at"] = (
                last if previous is None or last > previous else previous
            )
            recent = sum(
                (end - start).total_seconds() / 3600
                for start, end in done
                if end > as_of - timedelta(days=7)
            )
            hours = None if hours is None else hours + recent
        if hit is not None:
            e, phase = hit
            # The committed split shift counts toward the 60 h rolling limit ...
            hours = None if hours is None else hours + e.minutes / 60
            if phase == "preparing":
                # ... and blocks overlapping offers like a scheduled shift would.
                nxt = schedule.next_shift_starts_at
                sched_update["next_shift_starts_at"] = min(nxt, e.start_at) if nxt else e.start_at
        sched_update["hours_worked_trailing_7d"] = hours
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
