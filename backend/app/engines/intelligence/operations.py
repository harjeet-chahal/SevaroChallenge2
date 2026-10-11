"""Coverage Debt, Shift Handoff Intelligence and Problem grouping (pure).

Coverage debt  Σ max(0, required - usable capacity) × minutes, in physician-minutes.
  - projected: exact integral over the forecast horizon (same models as the dashboard);
  - historical: reconstructed by replaying state at earlier simulation times and sampling
    the instantaneous deficit every ``step`` minutes (left Riemann sum). It is labelled as
    a reconstruction, never mixed with the projection.
  Fragile coverage: minutes where the requirement is met with zero spare.

Problem groups (alert deduplication). Alerts that share one underlying cause get one
deterministic fingerprint (sha1 of kind + scope): a hospital's staffing failure groups its
coverage-gap, routing-failure, unassigned and surge alerts; consult delays group per
consult; workload and signal alerts per physician. Every member alert, including each
critical consult alert, stays listed. Ordering is a lexicographic tier policy, then a
transparent weighted tie-breaker, then the fingerprint (stable).
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta

from app.engines.analysis import OperationalAnalysis
from app.engines.intelligence.common import Models, evaluation_at, is_stroke, profile
from app.schemas.alert import Alert, RuleCode
from app.schemas.common import Severity
from app.schemas.consultation import ConsultStage
from app.schemas.intelligence import (
    CoverageDebtReport,
    DebtSample,
    GenomeDiagnosis,
    HandoffConsult,
    HandoffCoverageChange,
    HandoffDeadline,
    HandoffReport,
    HandoffTransition,
    HospitalDebt,
    ProblemGroup,
    ProblemReport,
)

NOTE_STAGES = {ConsultStage.NOTE_PENDING, ConsultStage.DOCUMENTATION}

# ------------------------------------------------------------------------- debt --


def coverage_debt_report(
    analysis: OperationalAnalysis,
    history: Sequence[OperationalAnalysis],
    *,
    lookback_minutes: int,
    step_minutes: int,
) -> CoverageDebtReport:
    """``history``: analyses at as_of - k*step (k = lookback/step .. 1), oldest first."""
    as_of = analysis.state.as_of
    hospitals: list[HospitalDebt] = []
    for h in analysis.coverage.hospitals:
        hid = h.hospital_id
        samples: list[DebtSample] = []
        hist = 0.0
        for past in history:
            ph = next((x for x in past.coverage.hospitals if x.hospital_id == hid), None)
            if ph is None:
                continue
            m = ph.metrics
            samples.append(
                DebtSample(
                    at=past.state.as_of,
                    required=m.required_now,
                    counted=m.available_now,
                    deficit=m.deficit_now,
                    kind="historical",
                )
            )
            hist += (m.deficit_now or 0) * step_minutes
        for seg in h.segments:
            samples.append(
                DebtSample(
                    at=seg.start,
                    required=seg.required,
                    counted=seg.available,
                    deficit=seg.deficit,
                    kind="projected",
                )
            )
        pr = profile(analysis.coverage_models[hid])
        hospitals.append(
            HospitalDebt(
                hospital_id=hid,
                hospital_name=h.hospital_name,
                historical_debt_physician_minutes=round(hist, 4),
                projected_debt_physician_minutes=h.metrics.deficit_physician_minutes,
                projected_debt_if_uncertain_excluded=h.metrics.deficit_physician_minutes_if_uncertain_excluded,
                fragile_minutes_projected=pr.fragile_minutes,
                samples=samples,
            )
        )
    return CoverageDebtReport(
        as_of=as_of,
        data_version=analysis.state.data_version,
        lookback_minutes=lookback_minutes,
        horizon_minutes=analysis.coverage.horizon_minutes,
        step_minutes=step_minutes,
        network_historical=round(sum(h.historical_debt_physician_minutes for h in hospitals), 4),
        network_projected=round(sum(h.projected_debt_physician_minutes for h in hospitals), 4),
        network_projected_if_uncertain_excluded=round(
            sum(h.projected_debt_if_uncertain_excluded for h in hospitals), 4
        ),
        network_fragile_minutes=round(sum(h.fragile_minutes_projected for h in hospitals), 4),
        hospitals=hospitals,
        method=[
            "Projected debt: exact integral of max(0, R(t) - A(t)) over the forecast horizon "
            "(Phase 3 coverage engine).",
            f"Historical debt: state replayed every {step_minutes} min over the last "
            f"{lookback_minutes} min; instantaneous deficit × step (reconstruction, not a log "
            "of what coordinators saw).",
            "Fragile minutes: requirement met exactly (zero spare); one loss creates a gap.",
        ],
    )


# ------------------------------------------------------------------------- handoff --


def handoff_report(
    analysis: OperationalAnalysis,
    models: Models,
    *,
    horizon_minutes: int,
    pending_rescues: Sequence[dict] = (),
) -> HandoffReport:
    state = analysis.state
    as_of = state.as_of
    end = as_of + timedelta(minutes=horizon_minutes)
    names = {h.id: h.name for h in state.hospitals}
    consults = {c.consult_id: c for c in state.consultations}
    transitions: list[HandoffTransition] = []

    def coverage_change(hids: Sequence[str], at: datetime) -> list[HandoffCoverageChange]:
        out = []
        for hid in sorted(hids):
            m = models.get(hid)
            if m is None:
                continue
            before = evaluation_at(m, at - timedelta(seconds=1))
            after = evaluation_at(m, at)
            if before is None or after is None:
                continue
            out.append(
                HandoffCoverageChange(
                    hospital_id=hid,
                    hospital_name=names.get(hid, hid),
                    counted_before=len(before[2].active),
                    counted_after=len(after[2].active),
                    required_after=after[2].required,
                    deficit_after=after[2].deficit,
                )
            )
        return out

    seen_arrivals: set[tuple[str, datetime]] = set()
    for p in sorted(state.physicians, key=lambda x: x.physician_id):
        cred = list(p.credentialed_hospital_ids)
        if p.on_shift and p.scheduled_shift and as_of < p.scheduled_shift.end <= end:
            at = p.scheduled_shift.end
            open_c = [consults[c] for c in p.open_consult_ids if c in consults]
            items = [
                HandoffConsult(
                    consult_id=c.consult_id,
                    hospital_id=c.hospital_id,
                    stage=c.stage.value,
                    consult_type=c.consult_type,
                    seconds_in_stage=c.seconds_in_stage,
                    unfinished_note=c.stage in NOTE_STAGES,
                )
                for c in open_c
            ]
            changes = coverage_change(cred, at)
            notes = sum(i.unfinished_note for i in items)
            risk = (
                "critical"
                if any((c.deficit_after or 0) > 0 for c in changes)
                else ("warning" if items else "ok")
            )
            msgs = []
            if notes >= 2:
                msgs.append(
                    f"{notes} unfinished notes at shift end (brief: flag ≥ 2 within 60 min)."
                )
            if any(not i.unfinished_note for i in items):
                msgs.append("Active clinical work still assigned: hand off or confirm stay.")
            transitions.append(
                HandoffTransition(
                    at=at,
                    kind="departing",
                    physician_id=p.physician_id,
                    display_name=p.display_name,
                    certainty="rescue_shift" if p.temporary_shift else "scheduled",
                    open_consults=items,
                    unfinished_notes=notes,
                    coverage_changes=changes,
                    risk=risk,  # type: ignore[arg-type]
                    notes=msgs,
                )
            )
        for m in models.values():
            for w in m.windows:
                if w.physician_id != p.physician_id or not (as_of < w.start <= end):
                    continue
                key = (p.physician_id, w.start)
                if key in seen_arrivals:
                    continue
                seen_arrivals.add(key)
                certainty = (
                    "rescue_shift"
                    if w.pending or w.proposed
                    else ("assumed" if w.certainty == "uncertain" else "scheduled")
                )
                changes = coverage_change(cred, w.start)
                transitions.append(
                    HandoffTransition(
                        at=w.start,
                        kind="arriving",
                        physician_id=p.physician_id,
                        display_name=p.display_name,
                        certainty=certainty,  # type: ignore[arg-type]
                        open_consults=[],
                        unfinished_notes=0,
                        coverage_changes=changes,
                        risk="ok",
                        notes=list(w.reasons),
                    )
                )
    transitions.sort(key=lambda t: (t.at, t.kind != "departing", t.physician_id))

    routing = [
        {
            "consult_id": c.consult_id,
            "hospital_id": c.hospital_id,
            "hospital_name": names.get(c.hospital_id or "", c.hospital_id),
            "consult_type": c.consult_type,
            "routing_failures": c.routing_failures,
            "last_failure_at": c.last_routing_failure_at,
            "next_retry_at": c.last_routing_failure_at + timedelta(minutes=5)
            if c.last_routing_failure_at
            else None,
        }
        for c in state.consultations
        if c.is_open and c.assigned_physician_id is None and c.routing_failures > 0
    ]
    deadlines: list[HandoffDeadline] = []
    for a in analysis.alerts.alerts:
        if a.consult_id is None or a.critical_after_seconds is None or a.condition_since is None:
            continue
        crit_at = a.condition_since + timedelta(seconds=a.critical_after_seconds)
        if crit_at > end:
            continue
        deadlines.append(
            HandoffDeadline(
                consult_id=a.consult_id,
                hospital_id=a.hospital_id,
                rule_code=a.rule_code.value,
                stage=a.rule_name,
                severity_now=a.severity,
                critical_at=crit_at,
                minutes_to_critical=round((crit_at - as_of).total_seconds() / 60, 2),
            )
        )
    deadlines.sort(key=lambda d: (d.critical_at or as_of, d.consult_id))
    return HandoffReport(
        as_of=as_of,
        data_version=state.data_version,
        horizon_minutes=horizon_minutes,
        transitions=transitions,
        pending_routing_failures=routing,
        pending_rescues=list(pending_rescues),
        deadlines=deadlines,
        notes=[
            "Departures come from scheduled shift ends; arrivals from scheduled or assumed "
            "shift starts and accepted rescue shifts (pending activation is uncertain).",
            "Coverage before/after is counted at the transition instant (projected).",
            "Deadlines: when a consult's current stage crosses its critical threshold if "
            "nothing changes; negative = already critical.",
        ],
    )


# ------------------------------------------------------------------------- problems --

TIER_POLICY = [
    "Tier 1: critical stroke consult delay or an unroutable stroke consult.",
    "Tier 2: other stroke warnings, or stroke stages reaching critical within 5 min.",
    "Tier 3: coverage shortfall now.",
    "Tier 4: projected coverage shortfall within the horizon.",
    "Tier 5: critical delay of a general consult; physician workload at shift end.",
    "Tier 6: availability uncertainty, demand signals and other warnings.",
    "Within a tier: weighted tie-breaker of computed factors (SLA share consumed, minutes "
    "over threshold, routing failures, affected items, deficit, imminence, certainty), then "
    "the fingerprint for a stable order.",
]

STAFFING_RULES = {
    RuleCode.COVERAGE_GAP_NOW,
    RuleCode.COVERAGE_GAP_PROJECTED,
    RuleCode.ROUTING_FAILURE,
    RuleCode.STAGE_TRIAGED_UNASSIGNED,
    RuleCode.DEMAND_SPIKE,
}
CONSULT_RULES = {
    RuleCode.STAGE_ASSIGNED_NOT_CONTACTED,
    RuleCode.STAGE_IMAGING_PENDING,
    RuleCode.STAGE_IMAGING_REVIEW,
    RuleCode.NOTE_OVERDUE,
    RuleCode.ASSIGNED_PHYSICIAN_UNAVAILABLE,
}


def _fingerprint(kind: str, scope: str) -> str:
    return hashlib.sha1(f"{kind}|{scope}".encode()).hexdigest()[:12]


def problem_report(
    analysis: OperationalAnalysis, genome: Sequence[GenomeDiagnosis] = ()
) -> ProblemReport:
    state = analysis.state
    consults = {c.consult_id: c for c in state.consultations}
    alerts = analysis.alerts.alerts
    groups: dict[tuple[str, str], list[Alert]] = defaultdict(list)
    for a in alerts:
        if a.rule_code in STAFFING_RULES and a.hospital_id:
            # A stand-alone surge alert is a demand signal, grouped with staffing only if
            # the hospital also has a staffing/routing alert (resolved below).
            groups[("hospital_staffing", a.hospital_id)].append(a)
        elif a.rule_code in CONSULT_RULES and a.consult_id:
            groups[("consult_delay", a.consult_id)].append(a)
        elif a.rule_code is RuleCode.OPEN_NOTES_NEAR_SHIFT_END and a.physician_id:
            groups[("physician_workload", a.physician_id)].append(a)
        else:
            groups[("physician_signal", a.physician_id or a.alert_id)].append(a)
    genome_by_h = {}
    for d in genome:
        genome_by_h.setdefault(d.hospital_id, d)

    out: list[ProblemGroup] = []
    for (kind, scope), members in groups.items():
        rules = {m.rule_code for m in members}
        if kind == "hospital_staffing" and rules == {RuleCode.DEMAND_SPIKE}:
            kind = "demand_surge"
        severity = (
            Severity.CRITICAL
            if any(m.severity is Severity.CRITICAL for m in members)
            else (
                Severity.WARNING
                if any(m.severity is Severity.WARNING for m in members)
                else Severity.INFO
            )
        )
        stroke_members = [
            m
            for m in members
            if m.consult_id
            and is_stroke(
                consults.get(m.consult_id).consult_type if consults.get(m.consult_id) else None
            )
        ]
        imminent = [
            m
            for m in stroke_members
            if m.severity is Severity.WARNING
            and m.critical_after_seconds is not None
            and m.elapsed_seconds is not None
            and m.critical_after_seconds - m.elapsed_seconds <= 300
        ]
        if any(m.severity is Severity.CRITICAL for m in stroke_members):
            tier = 1
        elif (
            stroke_members
            and kind in ("consult_delay", "hospital_staffing")
            and (RuleCode.ROUTING_FAILURE in rules or RuleCode.STAGE_TRIAGED_UNASSIGNED in rules)
            and severity is Severity.CRITICAL
        ):
            tier = 1
        elif stroke_members or imminent:
            tier = 2
        elif RuleCode.COVERAGE_GAP_NOW in rules:
            tier = 3
        elif RuleCode.COVERAGE_GAP_PROJECTED in rules:
            tier = 4
        elif severity is Severity.CRITICAL or kind == "physician_workload":
            tier = 5
        else:
            tier = 6
        sla = max(
            (
                m.elapsed_seconds / m.critical_after_seconds
                for m in members
                if m.elapsed_seconds is not None and m.critical_after_seconds
            ),
            default=0.0,
        )
        over = max(
            (
                (m.elapsed_seconds - m.critical_after_seconds) / 60
                for m in members
                if m.elapsed_seconds is not None
                and m.critical_after_seconds
                and m.elapsed_seconds > m.critical_after_seconds
            ),
            default=0.0,
        )
        failures = sum(
            consults[m.consult_id].routing_failures
            for m in members
            if m.consult_id in consults and m.rule_code is RuleCode.ROUTING_FAILURE
        )
        deficit = max((m.rank.coverage_risk for m in members), default=0)
        imminence = min(
            (m.minutes_to_impact for m in members if m.minutes_to_impact is not None), default=None
        )
        uncertain = any(a.rule_code in (RuleCode.SIGNAL_AGENT_OFFLINE,) for a in members)
        factors = {
            "sla_share_consumed": round(sla, 4),
            "minutes_over_critical": round(over, 2),
            "routing_failures": float(failures),
            "affected_items": float(len(members)),
            "coverage_risk": float(deficit),
            "imminence": round(1 / (1 + imminence), 4) if imminence is not None else 0.0,
            "data_certainty": 0.0 if uncertain else 1.0,
        }
        score = round(
            3 * factors["sla_share_consumed"]
            + 0.2 * factors["minutes_over_critical"]
            + 0.5 * factors["routing_failures"]
            + 0.3 * factors["affected_items"]
            + 1.0 * factors["coverage_risk"]
            + 2 * factors["imminence"]
            + 0.2 * factors["data_certainty"],
            4,
        )
        factors["tiebreak_score"] = score
        lead = min(members, key=lambda m: m.priority)
        hospital_id = (
            lead.hospital_id
            if kind in ("hospital_staffing", "demand_surge", "consult_delay")
            else None
        )
        g = genome_by_h.get(hospital_id) if kind == "hospital_staffing" else None
        crit_ids = [
            m.alert_id
            for m in sorted(members, key=lambda m: m.priority)
            if m.severity is Severity.CRITICAL
        ]
        if kind == "hospital_staffing":
            hname = lead.hospital_name or hospital_id
            title = f"{hname}: staffing / routing failure ({len(members)} linked alert(s))"
            action = g.recommended_intervention if g else lead.recommended_action_reason
        elif kind == "demand_surge":
            title = lead.title
            action = "Monitor; requirement +1 while the spike lasts (coverage forecast)."
        else:
            title = lead.title
            action = lead.recommended_action_reason
        text = (
            f"Tier {tier}: "
            + TIER_POLICY[tier - 1].split(": ", 1)[1]
            + f" Lead alert: {lead.title}."
        )
        if g:
            text += f" Root cause: {g.primary_cause.value} — {g.explanation}"
        out.append(
            ProblemGroup(
                fingerprint=_fingerprint(kind, scope),
                kind=kind,  # type: ignore[arg-type]
                tier=tier,
                priority=0,
                severity=severity,
                title=title,
                summary=lead.summary,
                hospital_id=hospital_id,
                physician_id=lead.physician_id,
                member_alert_ids=[m.alert_id for m in sorted(members, key=lambda m: m.priority)],
                critical_alert_ids=crit_ids,
                root_cause=g.primary_cause if g else None,
                recommended_action=action,
                factors=factors,
                explanation=text,
            )
        )
    out.sort(key=lambda g: (g.tier, -g.factors["tiebreak_score"], g.fingerprint))
    for i, g in enumerate(out, start=1):
        g.priority = i
    return ProblemReport(
        as_of=state.as_of,
        data_version=state.data_version,
        groups=out,
        alerts_total=len(alerts),
        tier_policy=TIER_POLICY,
    )
