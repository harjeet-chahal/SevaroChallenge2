"""Optimizer-ready snapshot (pure). Data only — no matching, no solver, no offers.

Candidate interventions report the *coverage effect* of adding an off-shift physician:
the deficit physician-minutes saved at each credentialed hospital if they came online
after their stated time-to-online. Split-shift eligibility rules (opt-in, rest, weekly
hours, overlap, minimum length) are deliberately NOT applied here; Phase 4 does that.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.engines.analysis.analyze import OperationalAnalysis
from app.engines.coverage_prediction import hypothetical_window
from app.engines.event_processing import normalize_label
from app.schemas.alert import Alert
from app.schemas.common import Severity
from app.schemas.optimization import (
    CandidateIntervention,
    CoverageEffect,
    DeficitInterval,
    OptConsult,
    OptHospital,
    OptimizationInput,
    OptPhysician,
)

SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.WARNING: 1, Severity.INFO: 2}

MODELING_NOTES = [
    "Coverage counts each physician at every hospital they are credentialed at (non-exclusive), "
    "as the brief defines the coverage rule. A matching/staffing optimizer may add an exclusive-"
    "allocation constraint (one physician serves one consult at a time); that is a model choice "
    "for Phase 4, not part of the coverage metric.",
    "Deficit intervals are exact piecewise segments from the coverage forecast (half-open).",
    "Candidate interventions are hypothetical coverage effects only; eligibility is not evaluated.",
    "No future events are used: everything is derived from state visible at as_of plus schedules.",
]


def _max_severity(alerts: list[Alert]) -> str | None:
    if not alerts:
        return None
    return min(alerts, key=lambda a: SEVERITY_ORDER[a.severity]).severity.value


def build_optimization_input(analysis: OperationalAnalysis) -> OptimizationInput:
    state = analysis.state
    as_of = state.as_of
    coverage = analysis.coverage
    horizon_end = coverage.horizon_end
    profiles = {p.id: p for p in analysis.reference.physicians}
    alerts_by_consult: dict[str, list[Alert]] = {}
    for a in analysis.alerts.alerts:
        if a.consult_id:
            alerts_by_consult.setdefault(a.consult_id, []).append(a)

    hospitals = [
        OptHospital(
            hospital_id=h.hospital_id,
            timezone=h.timezone,
            required_now=h.metrics.required_now,
            deficit_now=h.metrics.deficit_now,
            deficit_physician_minutes=h.metrics.deficit_physician_minutes,
            deficit_intervals=[
                DeficitInterval(
                    start=s.start,
                    end=s.end,
                    required=s.required,
                    available=s.available,
                    available_confirmed=s.available_confirmed,
                    deficit=s.deficit,
                )
                for s in h.segments
                if s.deficit
            ],
            spike_active=next(
                (
                    d.current.spike
                    for d in analysis.demand.hospitals
                    if d.hospital_id == h.hospital_id
                ),
                None,
            ),
        )
        for h in coverage.hospitals
    ]

    open_notes_stages = set(analysis.config.open_notes.note_stages)
    physicians = []
    for p in state.physicians:
        profile = profiles.get(p.physician_id)
        schedule = profile.schedule if profile else None
        notes = [
            c.consult_id
            for c in state.consultations
            if c.is_open
            and c.assigned_physician_id == p.physician_id
            and c.stage in open_notes_stages
        ]
        physicians.append(
            OptPhysician(
                physician_id=p.physician_id,
                roster=p.roster,
                roster_role=p.roster_role,
                on_shift=p.on_shift,
                availability=p.availability.value,
                activity=p.activity.value,
                credentialed_hospital_ids=p.credentialed_hospital_ids,
                shift_start=p.scheduled_shift.start if p.scheduled_shift else p.shift_started_at,
                shift_end=p.scheduled_shift.end if p.scheduled_shift else None,
                shift_end_known=p.scheduled_shift is not None,
                consults_this_shift=p.consults_this_shift,
                calls_this_shift=p.calls_this_shift,
                open_consult_ids=p.open_consult_ids,
                open_note_consult_ids=sorted(notes),
                phone_ringing=bool(p.signals.ringing),
                last_call_ended_at=p.signals.last_call_ended_at,
                uncertainty_flags=sorted(
                    f.code for f in p.flags if f.severity is not Severity.INFO
                ),
                split_shift_opt_in=profile.split_shift_opt_in if profile else None,
                last_shift_ended_at=schedule.last_shift_ended_at if schedule else None,
                next_shift_starts_at=schedule.next_shift_starts_at if schedule else None,
                hours_worked_trailing_7d=schedule.hours_worked_trailing_7d if schedule else None,
                minutes_to_come_online=schedule.minutes_to_come_online if schedule else None,
                offers_declined_30d=schedule.offers_declined_30d if schedule else None,
            )
        )

    on_shift_by_hospital: dict[str, list[str]] = {}
    for p in state.physicians:
        if p.on_shift:
            for hid in p.credentialed_hospital_ids:
                on_shift_by_hospital.setdefault(hid, []).append(p.physician_id)

    consults = []
    for c in state.consultations:
        if not c.is_open:
            continue
        related = alerts_by_consult.get(c.consult_id, [])
        upcoming = [a.impact_at for a in related if a.impact_at is not None and a.impact_at > as_of]
        consults.append(
            OptConsult(
                consult_id=c.consult_id,
                hospital_id=c.hospital_id,
                consult_type=c.consult_type,
                consult_category=next(
                    (
                        cat
                        for cat, labels in analysis.config.consult_categories.items()
                        if c.consult_type and normalize_label(c.consult_type) in labels
                    ),
                    None,
                ),
                stage=c.stage.value,
                assigned_physician_id=c.assigned_physician_id,
                seconds_since_received=c.seconds_since_received,
                seconds_in_stage=c.seconds_in_stage,
                routing_failures=c.routing_failures,
                max_alert_severity=_max_severity(related),
                next_threshold_at=min(upcoming) if upcoming else None,
                credentialed_on_shift_physician_ids=sorted(
                    on_shift_by_hospital.get(c.hospital_id or "", [])
                ),
            )
        )

    return OptimizationInput(
        as_of=as_of,
        horizon_end=horizon_end,
        data_version=state.data_version,
        hospitals=hospitals,
        physicians=physicians,
        consults=consults,
        candidate_interventions=candidate_interventions(analysis, as_of, horizon_end),
        modeling_notes=MODELING_NOTES,
    )


def candidate_interventions(
    analysis: OperationalAnalysis, as_of: datetime, horizon_end: datetime
) -> list[CandidateIntervention]:
    gap_hospitals = {
        h.hospital_id
        for h in analysis.coverage.hospitals
        if h.metrics.deficit_physician_minutes > 0
    }
    if not gap_hospitals:
        return []
    candidates: list[CandidateIntervention] = []
    for p in analysis.state.physicians:
        if p.on_shift or p.roster != "off_shift":
            continue
        relevant = sorted(set(p.credentialed_hospital_ids) & gap_hospitals)
        if not relevant:
            continue
        profile = next((x for x in analysis.reference.physicians if x.id == p.physician_id), None)
        delay = profile.schedule.minutes_to_come_online if profile else None
        notes = ["Eligibility rules not evaluated (Phase 4)."]
        if delay is None:
            notes.append("No time-to-online in the roster; assumed available immediately.")
        start = as_of + timedelta(minutes=delay or 0)
        if start >= horizon_end:
            continue
        window = hypothetical_window(
            p.physician_id,
            p.display_name,
            start,
            horizon_end,
            f"hypothetical: online after {delay or 0} min",
        )
        effects = []
        for hid in relevant:
            model = analysis.coverage_models[hid]
            before = model.deficit_physician_minutes()
            after = model.deficit_physician_minutes([window])
            effects.append(
                CoverageEffect(
                    hospital_id=hid,
                    deficit_physician_minutes_before=round(before, 4),
                    deficit_physician_minutes_after=round(after, 4),
                    reduction=round(before - after, 4),
                )
            )
        candidates.append(
            CandidateIntervention(
                physician_id=p.physician_id,
                available_from=start,
                available_until=horizon_end,
                effects=effects,
                total_reduction=round(sum(e.reduction for e in effects), 4),
                notes=notes,
            )
        )
    candidates.sort(key=lambda c: (-c.total_reduction, c.physician_id))
    return candidates
