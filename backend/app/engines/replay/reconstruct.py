"""``reconstruct_state(events, as_of, reference) -> OperationalState``.

Pure and deterministic: the same events, reference data and ``as_of`` always produce the
same state, regardless of the order the events are passed in. State is rebuilt from
scratch on every call, so a late event automatically lands in its correct place in the
timeline and can never be overwritten by an older event that merely arrived later.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from datetime import datetime

from app.core.time import ensure_aware, to_utc
from app.engines.consultation_state import ConsultationTracker
from app.engines.event_processing import annotate_event_log, replay_sort_key
from app.engines.physician_state import PhysicianStateTracker, build_physician_states
from app.schemas.common import Severity
from app.schemas.consultation import ConsultationState, StateAnomaly
from app.schemas.event import DedupeStatus, StoredEvent
from app.schemas.physician import Availability, PhysicianState
from app.schemas.state import (
    OperationalState,
    ReferenceData,
    ReplayDiagnostics,
    StateSummary,
)

MAX_REPORTED_ANOMALIES = 200


def _summary(physicians: list[PhysicianState], consults: list[ConsultationState]) -> StateSummary:
    on_shift = [p for p in physicians if p.on_shift]
    open_consults = [c for c in consults if c.is_open]
    by_stage = Counter(c.stage.value for c in open_consults)
    return StateSummary(
        physicians_total=len(physicians),
        physicians_on_shift=len(on_shift),
        on_shift_busy=sum(p.availability is Availability.BUSY for p in on_shift),
        on_shift_available=sum(p.availability is Availability.AVAILABLE for p in on_shift),
        on_shift_unavailable=sum(p.availability is Availability.UNAVAILABLE for p in on_shift),
        physicians_flagged=sum(
            any(f.severity is not Severity.INFO for f in p.flags) for p in physicians
        ),
        consults_open=len(open_consults),
        consults_open_assigned=sum(c.assigned_physician_id is not None for c in open_consults),
        consults_open_unassigned=sum(c.assigned_physician_id is None for c in open_consults),
        consults_closed=len(consults) - len(open_consults),
        open_consults_by_stage=dict(sorted(by_stage.items())),
    )


def summarize(physicians: list[PhysicianState], consults: list[ConsultationState]) -> StateSummary:
    """Summary counts for a (possibly overlaid) set of physicians and consults."""
    return _summary(physicians, consults)


def reconstruct_state(
    events: Sequence[StoredEvent],
    as_of: datetime,
    reference: ReferenceData | None = None,
    *,
    data_version: int = 0,
) -> OperationalState:
    as_of = to_utc(ensure_aware(as_of, field="as_of"))
    reference = reference or ReferenceData()

    not_yet_ingested = future_event_time = duplicates = conflicts = late = 0
    unknown_types: Counter[str] = Counter()
    applicable = []
    for annotated in annotate_event_log(events):
        event = annotated.event
        if event.ingested_at > as_of:
            not_yet_ingested += 1
            continue
        if annotated.dedupe_status is DedupeStatus.DUPLICATE:
            duplicates += 1
            continue
        if annotated.dedupe_status is DedupeStatus.CONFLICTING_DUPLICATE:
            conflicts += 1
            continue
        if event.event_time > as_of:
            future_event_time += 1
            continue
        if not event.is_known_type:
            unknown_types[event.event_type] += 1
            continue
        applicable.append(annotated)

    applicable.sort(key=lambda a: replay_sort_key(a.event))
    consult_tracker = ConsultationTracker()
    physician_tracker = PhysicianStateTracker()
    for annotated in applicable:
        consult_tracker.apply(annotated.event)
        physician_tracker.apply(annotated.event)
        late += annotated.arrived_out_of_order

    hospitals = {h.id: h for h in reference.hospitals}
    profiles = {p.id: p for p in reference.physicians}
    consults = consult_tracker.finalize(as_of, hospitals)
    physicians = build_physician_states(physician_tracker, profiles, consults, as_of)

    anomalies: list[StateAnomaly] = [a for c in consults for a in c.anomalies]
    for pid in physician_tracker.physician_ids:
        signals = physician_tracker.signals(pid)
        if signals:
            anomalies.extend(signals.anomalies)

    seen_physicians = {a.event.physician_id for a in applicable if a.event.physician_id}
    seen_hospitals = {a.event.hospital_id for a in applicable if a.event.hospital_id}

    return OperationalState(
        as_of=as_of,
        data_version=data_version,
        summary=_summary(physicians, consults),
        physicians=physicians,
        consultations=consults,
        hospitals=sorted(reference.hospitals, key=lambda h: h.id),
        diagnostics=ReplayDiagnostics(
            events_total=len(events),
            events_applied=len(applicable),
            events_not_yet_ingested=not_yet_ingested,
            events_future_event_time=future_event_time,
            duplicates_skipped=duplicates,
            conflicting_duplicates=conflicts,
            late_arrivals_applied=late,
            unknown_event_types=dict(sorted(unknown_types.items())),
            unknown_physician_ids=(sorted(seen_physicians - set(profiles)) if profiles else []),
            unknown_hospital_ids=sorted(seen_hospitals - set(hospitals)) if hospitals else [],
            anomalies=anomalies[:MAX_REPORTED_ANOMALIES],
        ),
    )
