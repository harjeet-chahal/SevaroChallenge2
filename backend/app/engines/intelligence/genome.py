"""Coverage Genome: why can't resources meet a hospital's demand? (pure)

For every projected shortfall (planning window) and every hospital with unroutable
consults, the engine measures a fixed set of factors at the problem instant and turns
them into weighted root causes. Each factor's raw weight is a count taken from state:

  CREDENTIALING_BOTTLENECK     on-duty physicians elsewhere who are not credentialed here
                               (capped at the deficit): capacity exists, qualification
                               does not
  TOTAL_CAPACITY_SHORTAGE      deficit not explained by idle capacity elsewhere, plus the
                               demand-spike +1 if active
  SHIFT_COLLISION              credentialed physicians whose shift ends in the 30 minutes
                               up to the problem instant (capped at the deficit)
  AVAILABILITY_UNCERTAINTY     Temporarily Unavailable credentialed physicians, plus the
                               extra deficit if uncertain windows were not counted
  ROUTING_ELIGIBILITY_FAILURE  unroutable consults while credentialed capacity is on duty
  WORKLOAD_CONCENTRATION       credentialed on-duty physicians busy right now
  DOCUMENTATION_HANDOFF_RISK   open notes of credentialed physicians leaving within 60 min
                               (secondary: 0.25 per note, capped at 0.5)

Weights are normalised to shares. The primary cause is the largest share; when the top
two are within ``multi_factor_margin`` it is MULTI_FACTOR. Explanations are generated only
from these counts.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from app.engines.analysis import OperationalAnalysis
from app.engines.intelligence.common import Models, evaluation_at, profile
from app.engines.intelligence.config import IntelligenceConfig
from app.engines.timeline import fmt_local
from app.schemas.alert import RuleCode
from app.schemas.common import Severity
from app.schemas.consultation import ConsultStage
from app.schemas.intelligence import (
    AvailabilityClass,
    GenomeDiagnosis,
    GenomeFactor,
    GenomeReport,
    RootCause,
    StrategicSuggestion,
)

R = RootCause

INTERVENTION = {
    R.CREDENTIALING_BOTTLENECK: "Off-shift physician credentialed here (split shift); "
    "credentialing expansion is a planning item only.",
    R.TOTAL_CAPACITY_SHORTAGE: "Bring additional credentialed capacity online (split shift) "
    "or escalate.",
    R.SHIFT_COLLISION: "Split shift starting before the shift ends; stagger future shift ends.",
    R.ROUTING_ELIGIBILITY_FAILURE: "Reassign or escalate the waiting consult; capacity exists "
    "but nobody is routable now.",
    R.WORKLOAD_CONCENTRATION: "Rebalance: reassign waiting work to a less-loaded credentialed "
    "physician.",
    R.AVAILABILITY_UNCERTAINTY: "Confirm availability of physicians with stale or "
    "contradictory signals before relying on them.",
    R.DOCUMENTATION_HANDOFF_RISK: "Plan the handoff of open notes before the shift ends.",
    R.MULTI_FACTOR: "Combined plan: see the factors; usually a split shift plus escalation.",
}

LIMIT = {
    R.CREDENTIALING_BOTTLENECK: "hospital-specific credentialing",
    R.TOTAL_CAPACITY_SHORTAGE: "network capacity on duty",
    R.SHIFT_COLLISION: "simultaneous shift ends",
    R.ROUTING_ELIGIBILITY_FAILURE: "routing eligibility (busy / ringing / cooldown)",
    R.WORKLOAD_CONCENTRATION: "concurrent workload of credentialed physicians",
    R.AVAILABILITY_UNCERTAINTY: "signal reliability",
    R.DOCUMENTATION_HANDOFF_RISK: "open documentation at handoff",
    R.MULTI_FACTOR: "several interacting constraints",
}


def _diag_id(hid: str, problem: str, at: datetime) -> str:
    return "GEN-" + hashlib.sha1(f"{hid}|{problem}|{at.isoformat()}".encode()).hexdigest()[:10]


def genome_report(
    analysis: OperationalAnalysis,
    models: Models,
    classes: Mapping[str, AvailabilityClass],
    routable: Mapping[str, bool],
    cfg: IntelligenceConfig,
    *,
    horizon_minutes: int,
    single_points: Mapping[str, list[str]] | None = None,
    uncovered_by_candidates: Sequence[str] = (),
) -> GenomeReport:
    state = analysis.state
    as_of = state.as_of
    names = {h.id: h.name for h in state.hospitals}
    physicians = {p.physician_id: p for p in state.physicians}
    consults = state.consultations
    alerts = analysis.alerts.alerts
    diagnoses: list[GenomeDiagnosis] = []

    problems: list[tuple[str, str, datetime]] = []
    for hid in sorted(models):
        pr = profile(models[hid])
        if pr.first_shortfall is not None:
            kind = "coverage_gap_now" if pr.first_shortfall <= as_of else "coverage_gap_projected"
            problems.append((hid, kind, max(pr.first_shortfall, as_of)))
    stranded = Counter(
        c.hospital_id
        for c in consults
        if c.is_open
        and c.assigned_physician_id is None
        and c.routing_failures > 0
        and c.hospital_id
    )
    for hid in sorted(stranded):
        if hid in models and not any(p[0] == hid and p[1] == "coverage_gap_now" for p in problems):
            problems.append((hid, "unroutable_consults", as_of))

    def who(ids) -> str:
        return ", ".join(physicians[x].display_name for x in ids if x in physicians)

    def active_at(moment: datetime) -> dict[str, list[str]]:
        out = {}
        for h, m in models.items():
            piece = evaluation_at(m, moment)
            out[h] = [w.physician_id for w in piece[2].active] if piece else []
        return out

    for hid, kind, at in problems:
        model = models[hid]
        piece = evaluation_at(model, at)
        e = piece[2]
        required = e.required or 0
        counted = [w.physician_id for w in e.active]
        deficit = max(0, required - len(counted))
        active_net = active_at(at)
        on_duty_net = sorted({pid for ids in active_net.values() for pid in ids})
        credentialed = sorted(
            p.physician_id for p in state.physicians if hid in p.credentialed_hospital_ids
        )
        elsewhere = [pid for pid in on_duty_net if pid not in credentialed]
        # spare elsewhere: physicians whose own hospitals keep their requirement without them
        spare_elsewhere = []
        for pid in elsewhere:
            needed = False
            for h2, ids in active_net.items():
                if pid in ids:
                    p2 = evaluation_at(models[h2], at)
                    if p2 and p2[2].required is not None and len(ids) - 1 < p2[2].required:
                        needed = True
                        break
            if not needed:
                spare_elsewhere.append(pid)
        window_start = at - timedelta(minutes=30)
        ending = sorted(
            w.physician_id
            for w in model.windows
            if w.end is not None and window_start < w.end <= at + timedelta(seconds=1)
        )
        uncertain = sorted(w.physician_id for w in e.active if w.certainty == "uncertain")
        tu = sorted(
            pid
            for pid in credentialed
            if classes.get(pid) is AvailabilityClass.UNAVAILABLE and physicians[pid].on_shift
        )
        busy_now = sorted(
            pid
            for pid in credentialed
            if physicians[pid].on_shift
            and classes.get(pid)
            in (
                AvailabilityClass.BUSY_CALL,
                AvailabilityClass.BUSY_VIDEO,
                AvailabilityClass.PROBABLY_BUSY_EXTERNAL,
            )
        )
        routable_here = sorted(
            pid for pid in credentialed if routable.get(pid) and physicians[pid].on_shift
        )
        notes_leaving = []
        for pid in credentialed:
            p = physicians[pid]
            if (
                p.on_shift
                and p.scheduled_shift
                and p.scheduled_shift.end <= at + timedelta(minutes=60)
            ):
                open_notes = [
                    c
                    for c in consults
                    if c.consult_id in p.open_consult_ids
                    and c.stage in (ConsultStage.NOTE_PENDING, ConsultStage.DOCUMENTATION)
                ]
                if open_notes:
                    notes_leaving.append((pid, len(open_notes)))
        spike = bool(e.spike_adjustment)
        n_stranded = stranded.get(hid, 0)

        raw: dict[R, float] = {}
        ev: dict[R, list[str]] = {}
        if deficit > 0:
            cred_block = min(deficit, len(spare_elsewhere))
            if cred_block:
                raw[R.CREDENTIALING_BOTTLENECK] = float(cred_block)
                ev[R.CREDENTIALING_BOTTLENECK] = [
                    f"{len(spare_elsewhere)} physician(s) on duty elsewhere with spare capacity "
                    f"are not credentialed here: {who(spare_elsewhere[:5])}"
                ]
            shortage = deficit - cred_block + (1 if spike else 0)
            if shortage > 0:
                raw[R.TOTAL_CAPACITY_SHORTAGE] = float(shortage)
                ev[R.TOTAL_CAPACITY_SHORTAGE] = [
                    f"{len(counted)} counted vs {required} required"
                    + (" (requirement +1 for an active demand spike)" if spike else "")
                    + f"; no idle capacity elsewhere covers the remaining {deficit - cred_block}."
                ]
            if ending:
                raw[R.SHIFT_COLLISION] = float(min(len(ending), deficit))
                ev[R.SHIFT_COLLISION] = [
                    f"Shift end(s) in the 30 min before {fmt_local(at, model.tz)}: " + who(ending)
                ]
        # Uncertainty explains the problem only where it changes the count: physicians
        # who would count but are Temporarily Unavailable, or windows counted only as
        # uncertain (a confirmed-only reading would be short by that many more).
        confirmed_gap = max(0, required - len(e.confirmed)) - deficit
        if tu or (confirmed_gap > 0 and uncertain):
            raw[R.AVAILABILITY_UNCERTAINTY] = float(len(tu) + confirmed_gap)
            ev[R.AVAILABILITY_UNCERTAINTY] = [
                *([f"Counted only as uncertain: {who(uncertain)}"] if uncertain else []),
                *([f"Credentialed but Temporarily Unavailable: {who(tu)}"] if tu else []),
            ]
        if n_stranded:
            raw[R.ROUTING_ELIGIBILITY_FAILURE] = float(n_stranded) * (
                2.0 if not routable_here else 1.0
            )
            ev[R.ROUTING_ELIGIBILITY_FAILURE] = [
                f"{n_stranded} consult(s) failed routing and are unassigned; routable "
                f"credentialed physicians now: {len(routable_here)} of {len(counted)} counted."
            ]
            if busy_now:
                raw[R.WORKLOAD_CONCENTRATION] = (
                    float(len(busy_now)) / max(1, len(counted)) * n_stranded
                )
                ev[R.WORKLOAD_CONCENTRATION] = [
                    f"Busy now: {', '.join(physicians[x].display_name for x in busy_now)}."
                ]
        if notes_leaving:
            # Secondary factor: open notes complicate the handoff, they do not create the gap.
            raw[R.DOCUMENTATION_HANDOFF_RISK] = min(0.5, 0.25 * sum(n for _, n in notes_leaving))
            ev[R.DOCUMENTATION_HANDOFF_RISK] = [
                f"{physicians[pid].display_name}: {n} open note(s), shift ends within 60 min."
                for pid, n in notes_leaving
            ]
        if not raw:
            raw[R.TOTAL_CAPACITY_SHORTAGE] = 1.0
            ev[R.TOTAL_CAPACITY_SHORTAGE] = ["Requirement exceeds counted capacity."]
        total = sum(raw.values())
        factors = sorted(
            (
                GenomeFactor(cause=k, weight=round(v / total, 4), evidence=ev.get(k, []))
                for k, v in raw.items()
            ),
            key=lambda f: (-f.weight, f.cause.value),
        )
        primary = factors[0].cause
        if len(factors) > 1 and factors[0].weight - factors[1].weight <= cfg.multi_factor_margin:
            primary = R.MULTI_FACTOR
        excluded = Counter()
        for pid in on_duty_net:
            if pid not in credentialed:
                excluded["not_credentialed_here"] += 1
        for pid in credentialed:
            p = physicians[pid]
            if pid in counted:
                continue
            if classes.get(pid) is AvailabilityClass.UNAVAILABLE:
                excluded["temporarily_unavailable"] += 1
            elif (
                p.routing_scope_hospital_ids is not None and hid not in p.routing_scope_hospital_ids
            ):
                excluded["outside_approved_scope"] += 1
            else:
                excluded["off_shift_at_problem_time"] += 1
        severity = (
            Severity.CRITICAL
            if kind == "coverage_gap_now" or (n_stranded and not routable_here)
            else Severity.WARNING
        )
        when = "now" if at <= as_of else f"at {fmt_local(at, model.tz)}"
        if primary is R.CREDENTIALING_BOTTLENECK:
            text = (
                f"{len(spare_elsewhere)} physician(s) have spare capacity elsewhere in the network "
                f"{when}, but none is credentialed at {names[hid]}. General staffing capacity "
                "exists; hospital-specific qualification is the bottleneck."
            )
        elif primary is R.SHIFT_COLLISION:
            text = (
                f"{len(ending)} credentialed shift(s) end just before {names[hid]} falls short "
                f"{when}; the gap is created by the schedule, not by demand."
            )
        elif primary is R.ROUTING_ELIGIBILITY_FAILURE:
            text = (
                f"{names[hid]} has {len(counted)} credentialed physician(s) on duty (requirement "
                f"{required}), yet {n_stranded} consult(s) cannot be routed: nobody credentialed "
                "is free, ringing-free and past the 2-minute cooldown."
            )
        elif primary is R.TOTAL_CAPACITY_SHORTAGE:
            text = (
                f"{names[hid]} needs {required} and has {len(counted)} {when}; there is no idle "
                "credentialed capacity in the network to absorb it."
            )
        elif primary is R.MULTI_FACTOR:
            text = (
                f"{names[hid]} {when}: "
                + " + ".join(f"{f.cause.value} ({f.weight:.0%})" for f in factors[:3])
                + "."
            )
        else:
            text = f"{names[hid]} {when}: primary cause {primary.value}."
        related = [
            a.alert_id
            for a in alerts
            if a.hospital_id == hid
            and a.rule_code
            in (
                RuleCode.COVERAGE_GAP_NOW,
                RuleCode.COVERAGE_GAP_PROJECTED,
                RuleCode.ROUTING_FAILURE,
                RuleCode.STAGE_TRIAGED_UNASSIGNED,
                RuleCode.DEMAND_SPIKE,
            )
        ]
        diagnoses.append(
            GenomeDiagnosis(
                diagnosis_id=_diag_id(hid, kind, at),
                hospital_id=hid,
                hospital_name=names[hid],
                problem=kind,  # type: ignore[arg-type]
                problem_at=at,
                severity=severity,
                primary_cause=primary,
                factors=factors,
                counts={
                    "required": required,
                    "credentialed_total": len(credentialed),
                    "counted": len(counted),
                    "routable_now": len(routable_here),
                    "deficit": deficit,
                    "on_duty_network": len(on_duty_net),
                    "spare_elsewhere": len(spare_elsewhere),
                    "stranded_consults": n_stranded,
                },
                excluded_by_reason=dict(sorted(excluded.items())),
                limiting_constraint=LIMIT[primary],
                recommended_intervention=INTERVENTION[primary],
                explanation=text,
                related_alert_ids=related,
            )
        )
    diagnoses.sort(key=lambda d: (d.severity != Severity.CRITICAL, d.problem_at, d.hospital_id))

    # ---- strategic, planning-only suggestions ---------------------------------------------
    strategic: list[StrategicSuggestion] = []
    for d in diagnoses:
        f = {x.cause for x in d.factors}
        if R.CREDENTIALING_BOTTLENECK in f:
            at = d.problem_at
            active_net = active_at(at)
            cands = Counter()
            for ids in active_net.values():
                for pid in ids:
                    if d.hospital_id not in physicians[pid].credentialed_hospital_ids:
                        cands[pid] += 1
            top = [pid for pid, _ in sorted(cands.items(), key=lambda kv: (kv[1], kv[0]))[:3]]
            if top:
                strategic.append(
                    StrategicSuggestion(
                        kind="credentialing_expansion",
                        title=f"Future credentialing candidates for {d.hospital_name}",
                        detail=(
                            "Physicians on duty at the shortfall time who are not credentialed "
                            f"here: {', '.join(physicians[x].display_name for x in top)}. "
                            "Credentialing takes time; this does not authorize routing now."
                        ),
                        basis=[d.explanation],
                    )
                )
        if R.SHIFT_COLLISION in f:
            strategic.append(
                StrategicSuggestion(
                    kind="shift_overlap",
                    title=f"Stagger shift ends covering {d.hospital_name}",
                    detail="Several credentialed shifts end within 30 minutes of each other; "
                    "a staggered end or a planned overlap shift would remove this cliff.",
                    basis=[
                        e for x in d.factors if x.cause is R.SHIFT_COLLISION for e in x.evidence
                    ],
                )
            )
    for hid, pids in sorted((single_points or {}).items()):
        if len(pids) and hid in names:
            strategic.append(
                StrategicSuggestion(
                    kind="dependency_reduction",
                    title=f"Reduce single-physician dependency at {names[hid]}",
                    detail=(
                        f"Losing {who(pids)} "
                        "alone would create or deepen a shortfall. Add a credentialed backup "
                        "to the schedule in this window."
                    ),
                    basis=["Network Fragility Scanner single-point analysis."],
                )
            )
    for hid in uncovered_by_candidates:
        if hid in names:
            strategic.append(
                StrategicSuggestion(
                    kind="backup_placement",
                    title=f"No eligible off-shift backup for {names[hid]}",
                    detail="Every off-shift physician fails at least one split-shift rule or is "
                    "not credentialed here. Consider rostering an opted-in backup credentialed "
                    "at this hospital.",
                    basis=["Rescue Scarcity Index: no feasible candidate."],
                )
            )
    return GenomeReport(
        as_of=as_of,
        data_version=state.data_version,
        horizon_minutes=horizon_minutes,
        diagnoses=diagnoses,
        strategic=strategic,
        method=[
            "Factors are counts measured at the problem instant from the coverage models, "
            "availability classes and consult state; shares are normalised counts.",
            f"MULTI_FACTOR when the top two shares differ by ≤ {cfg.multi_factor_margin:.0%}.",
            "Strategic suggestions are planning items only and never relax credentialing.",
        ],
    )
