"""Rescue Impact Simulator and Physician Load Guardian (pure).

Every option is applied to an *isolated copy* of the planning-window coverage models and
re-evaluated network-wide with the same exact piecewise engine as the dashboard. The live
analysis is never mutated (dataclass copies; see common.py).

Options: do nothing (always), escalation, consult reassignment (Phase 4 dispatch plan),
one split shift per eligible candidate credentialed at a target hospital (rule-checked by
the Phase 4 planner), the optimizer's combined plan, and a shift extension what-if.
Shift extensions are simulation-only: the dataset has no extension authority and no
rest/weekly-hour data for on-shift physicians, so eligibility is UNKNOWN and the option
can never be proposed. Ineligible candidates are listed with their failed rules and no
projection is used to rank them.

Lexicographic objective (lower is better, compared element by element):
  1. invalid / unauthorized / simulation-only            (hard constraints first)
  2. target deficit after (physician-minutes)            (resolve the selected problem)
  3. new shortfalls created elsewhere                    (avoid new critical problems)
  4. network deficit after (physician-minutes)           (horizon-wide coverage)
  5. joiner workload excess over peer median (modeled)   (load concentration)
  6. number of physicians contacted                      (coordination burden)
  7. activation delay (minutes)
A minor efficiency gain can therefore never outweigh a worse result on an earlier level.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta

from app.engines.coverage_prediction import Window, hypothetical_window
from app.engines.intelligence.common import (
    Models,
    add_windows,
    profiles,
    single_point_physicians,
)
from app.engines.intelligence.config import IntelligenceConfig
from app.engines.optimization.split_shift import proposed_window
from app.engines.optimization.split_shift.candidates import (
    Candidate,
    Option,
    PlanningContext,
)
from app.engines.optimization.split_shift.trap import protection_for, trap_analysis
from app.engines.timeline import fmt_local
from app.schemas.dispatch import DispatchResult
from app.schemas.intelligence import (
    LoadGuardianReport,
    OptionOutcome,
    RescueOption,
    RescueSimulation,
)
from app.schemas.staffing import StaffingResult, TrapAnalysis

OBJECTIVE = [
    "1. Hard constraints: invalid, unauthorized or simulation-only options rank last.",
    "2. Smallest remaining deficit at the target hospital(s).",
    "3. Fewest new shortfalls created elsewhere.",
    "4. Smallest network-wide deficit over the planning horizon.",
    "5. Least modeled workload concentration on a joining physician.",
    "6. Fewest physicians contacted.",
    "7. Earliest activation.",
]


def _outcome(
    ctx: PlanningContext,
    before: Models,
    after: Models,
    targets: Sequence[str],
    sp_before: int,
    activation: datetime | None,
) -> OptionOutcome:
    pb, pa = profiles(before), profiles(after)
    per = []
    for hid in sorted(before):
        b, a = pb[hid], pa[hid]
        if b.deficit_pm == 0 and a.deficit_pm == 0 and hid not in targets:
            continue
        per.append(
            {
                "hospital_id": hid,
                "hospital_name": ctx.hospital_name(hid),
                "deficit_before": b.deficit_pm,
                "deficit_after": a.deficit_pm,
                "first_shortfall_before": b.first_shortfall,
                "first_shortfall_after": a.first_shortfall,
                "target": hid in targets,
            }
        )
    sp_after = len(single_point_physicians(after)) if after is not before else sp_before
    return OptionOutcome(
        network_deficit_before=round(sum(p.deficit_pm for p in pb.values()), 4),
        network_deficit_after=round(sum(p.deficit_pm for p in pa.values()), 4),
        target_deficit_before=round(sum(pb[h].deficit_pm for h in targets if h in pb), 4),
        target_deficit_after=round(sum(pa[h].deficit_pm for h in targets if h in pa), 4),
        resolved_hospital_ids=sorted(
            h for h in pb if pb[h].deficit_pm > 0 and pa[h].deficit_pm == 0
        ),
        residual_hospital_ids=sorted(h for h in pa if pa[h].deficit_pm > 0),
        new_shortfall_hospital_ids=sorted(
            h for h in pa if pb[h].deficit_pm == 0 and pa[h].deficit_pm > 0
        ),
        single_points_before=sp_before,
        single_points_after=sp_after,
        activation_at=activation,
        activation_delay_minutes=round((activation - ctx.as_of).total_seconds() / 60, 2)
        if activation
        else None,
        per_hospital=per,
    )


def _workload(trap: TrapAnalysis | None) -> tuple[dict | None, float]:
    if trap is None:
        return None, 0.0
    p = trap.protected
    u = trap.unrestricted
    median = p.peer_median_consults or 0.0
    excess = max(0.0, p.joiner_final_consults - median)
    return (
        {
            "physician_id": trap.physician_id,
            "modeled_window": [trap.window_start, trap.window_end],
            "unrestricted_routed_to_joiner": u.routed_to_joiner,
            "unrestricted_elsewhere": u.routed_to_joiner_elsewhere,
            "protected_routed_to_joiner": p.routed_to_joiner,
            "protected_elsewhere": p.routed_to_joiner_elsewhere,
            "peer_median_consults": p.peer_median_consults,
            "joiner_final_consults_protected": p.joiner_final_consults,
            "conclusion": trap.conclusion,
        },
        excess,
    )


def _best_option_for(
    pid: str, options: Sequence[Option], ctx: PlanningContext, targets: Sequence[str]
) -> Option | None:
    mine = [o for o in options if o.physician_id == pid and set(o.hospitals) & set(targets)]
    if not mine:
        return None

    def gain(o: Option) -> tuple:
        w = proposed_window(o)
        red = sum(
            ctx.base_deficit.get(h, 0.0) - ctx.models[h].deficit_physician_minutes([w])
            for h in o.hospitals
            if h in ctx.models
        )
        return (-round(red, 4), o.online_at, -o.minutes, o.index)

    return min(mine, key=gain)


def simulate_rescues(
    ctx: PlanningContext,
    candidates: Sequence[Candidate],
    options: Sequence[Option],
    staffing: StaffingResult,
    dispatch: DispatchResult | None,
    cfg: IntelligenceConfig,
    *,
    target_hospital_ids: Sequence[str],
    target_label: str,
    alert_id: str | None = None,
) -> RescueSimulation:
    as_of = ctx.as_of
    base = dict(ctx.models)
    sp_before = len(single_point_physicians(base))
    targets = [h for h in target_hospital_ids if h in base]
    names = {h: ctx.hospital_name(h) for h in base}
    result: list[RescueOption] = []

    nothing = _outcome(ctx, base, base, targets, sp_before, None)
    result.append(
        RescueOption(
            option_id="do_nothing",
            kind="do_nothing",
            label="Do nothing (comparator)",
            feasible=True,
            simulation_only=False,
            requires_approval=False,
            hospital_ids=targets,
            outcome=nothing,
            why=["Baseline: the forecast if no action is taken."],
        )
    )
    escalation_proposal = {"type": "escalation", "hospital_id": targets[0] if targets else None}
    if alert_id:
        escalation_proposal["alert_id"] = alert_id
    result.append(
        RescueOption(
            option_id="escalation",
            kind="escalation",
            label="Escalate to the clinical lead",
            feasible=bool(targets),
            simulation_only=False,
            requires_approval=True,
            hospital_ids=targets,
            outcome=nothing,
            why=[
                "Puts the problem in front of the clinical lead with evidence. No modeled "
                "capacity change: it does not by itself close a coverage gap."
            ],
            proposal=escalation_proposal if targets else None,
        )
    )

    if dispatch is not None:
        for r in dispatch.plan.recommendations:
            consult = r.consult_id
            hid = r.hospital_id
            if targets and hid not in targets:
                continue
            result.append(
                RescueOption(
                    option_id=f"reassign:{consult}:{r.physician_id}",
                    kind="reassignment",
                    label=f"{r.kind.replace('_', ' ').capitalize()} {consult} → {r.physician_name}",
                    feasible=True,
                    simulation_only=False,
                    requires_approval=False,
                    physician_ids=[r.physician_id],
                    hospital_ids=[hid] if hid else [],
                    outcome=nothing,
                    why=[
                        "Routes a waiting consult to an eligible credentialed physician (Phase 4 "
                        "dispatch, brief routing rules). Coverage capacity is unchanged."
                    ],
                    proposal={
                        "type": "reassign_consult",
                        "consult_id": consult,
                        "target_physician_id": r.physician_id,
                    },
                )
            )

    trap_by_pid: dict[str, TrapAnalysis] = {}
    for c in sorted(candidates, key=lambda x: x.physician_id):
        cred_targets = [h for h in targets if h in c.state.credentialed_hospital_ids]
        if not cred_targets:
            continue
        e = c.eligibility
        if not e.eligible:
            result.append(
                RescueOption(
                    option_id=f"split:{c.physician_id}",
                    kind="split_shift",
                    label=f"Split shift: {c.state.display_name}",
                    feasible=False,
                    simulation_only=False,
                    requires_approval=True,
                    physician_ids=[c.physician_id],
                    hospital_ids=cred_targets,
                    blocking_reasons=[
                        f"{ch.label}: {ch.message}" for ch in e.checks if not ch.passed
                    ],
                    why=["Not offered: fails at least one hard split-shift rule."],
                )
            )
            continue
        opt = _best_option_for(c.physician_id, options, ctx, targets)
        if opt is None:
            result.append(
                RescueOption(
                    option_id=f"split:{c.physician_id}",
                    kind="split_shift",
                    label=f"Split shift: {c.state.display_name}",
                    feasible=False,
                    simulation_only=False,
                    requires_approval=True,
                    physician_ids=[c.physician_id],
                    hospital_ids=cred_targets,
                    blocking_reasons=["No valid offer window overlaps the target shortfall."],
                )
            )
            continue
        window = proposed_window(opt)
        after = add_windows(base, {h: [window] for h in opt.hospitals})
        prot = protection_for(opt, ctx, sorted(c.state.credentialed_hospital_ids))
        trap = trap_analysis(ctx, opt, prot)
        trap_by_pid[c.physician_id] = trap
        workload, _ = _workload(trap)
        tz = ctx.tz_for(opt.hospitals)
        result.append(
            RescueOption(
                option_id=f"split:{c.physician_id}",
                kind="split_shift",
                label=(
                    f"Split shift: {c.state.display_name} "
                    f"{fmt_local(opt.start, tz)}–{fmt_local(opt.end, tz)}"
                ),
                feasible=True,
                simulation_only=False,
                requires_approval=True,
                physician_ids=[c.physician_id],
                hospital_ids=list(opt.hospitals),
                start_at=opt.start,
                end_at=opt.end,
                outcome=_outcome(ctx, base, after, targets, sp_before, opt.online_at),
                workload=workload,
                why=[
                    f"All split-shift rules pass for {c.state.display_name} at the offered start.",
                    f"Expected online {fmt_local(opt.online_at, tz)} ({c.online_minutes} min to "
                    "come online counts against the offer).",
                    f"Routing scope limited to {', '.join(names.get(h, h) for h in opt.hospitals)} "
                    "(split-shift trap protection).",
                ],
                uncertainty=[
                    "Acceptance is not assumed; projection shows coverage if accepted.",
                    "Counted as uncertain until the physician is online.",
                ],
                proposal={
                    "type": "split_shift",
                    "physician_ids": [c.physician_id],
                    "hospital_ids": list(opt.hospitals),
                    "start_at": opt.start.isoformat(),
                    "duration_minutes": opt.minutes,
                    **({"alert_id": alert_id} if alert_id else {}),
                },
            )
        )

    recs = [r for r in staffing.recommendations if set(r.hospital_ids) & set(targets)]
    if len(recs) >= 2:
        adds: dict[str, list[Window]] = {}
        for r in recs:
            w = hypothetical_window(
                r.physician_id, r.display_name, r.online_at, r.offer_end, "combined plan"
            )
            for h in r.hospital_ids:
                adds.setdefault(h, []).append(w)
        after = add_windows(base, adds)
        first_online = min(r.online_at for r in recs)
        result.append(
            RescueOption(
                option_id="combination:optimizer",
                kind="combination",
                label="Optimizer plan: " + " + ".join(r.display_name for r in recs),
                feasible=True,
                simulation_only=False,
                requires_approval=True,
                physician_ids=[r.physician_id for r in recs],
                hospital_ids=sorted({h for r in recs for h in r.hospital_ids}),
                outcome=_outcome(ctx, base, after, targets, sp_before, first_online),
                why=["CP-SAT staffing plan (Phase 4) restricted to the target hospitals."],
                proposal={
                    "type": "split_shift",
                    "physician_ids": [r.physician_id for r in recs][:4],
                    "hospital_ids": sorted({h for r in recs for h in r.hospital_ids}),
                },
            )
        )

    first_short = {h: profiles({h: base[h]})[h].first_shortfall for h in targets}
    for p in sorted(ctx.analysis.state.physicians, key=lambda x: x.physician_id):
        if not (p.on_shift and p.scheduled_shift):
            continue
        cred = [h for h in targets if h in p.credentialed_hospital_ids]
        if not cred:
            continue
        end = p.scheduled_shift.end
        if not any(first_short[h] and end <= first_short[h] for h in cred):
            continue
        new_end = end + timedelta(minutes=cfg.extension_minutes)
        after = {
            hid: replace(
                m,
                windows=[
                    replace(w, end=new_end)
                    if w.physician_id == p.physician_id and w.end == end
                    else w
                    for w in m.windows
                ],
            )
            for hid, m in base.items()
        }
        result.append(
            RescueOption(
                option_id=f"extend:{p.physician_id}",
                kind="shift_extension",
                label=f"Extend {p.display_name} by {cfg.extension_minutes} min (what-if)",
                feasible=False,
                simulation_only=True,
                requires_approval=True,
                physician_ids=[p.physician_id],
                hospital_ids=cred,
                start_at=end,
                end_at=new_end,
                blocking_reasons=[
                    "Simulation only: the dataset has no shift-extension authority and no "
                    "rest/weekly-hour data for on-shift physicians (eligibility UNKNOWN).",
                ],
                outcome=_outcome(ctx, base, after, targets, sp_before, end),
                why=["Shows what keeping this physician on would do; not a proposal."],
            )
        )

    for o in result:
        out = o.outcome
        invalid = 0 if (o.feasible and not o.simulation_only) else 1
        _, excess = (
            _workload(trap_by_pid.get(o.physician_ids[0]))
            if o.kind == "split_shift" and o.physician_ids
            else (None, 0.0)
        )
        o.lexicographic_key = [
            float(invalid),
            out.target_deficit_after if out else 1e9,
            float(len(out.new_shortfall_hospital_ids)) if out else 1e9,
            out.network_deficit_after if out else 1e9,
            float(excess),
            float(len(o.physician_ids)),
            out.activation_delay_minutes or 0.0 if out else 1e9,
        ]
    order = sorted(result, key=lambda o: (o.lexicographic_key, o.option_id))
    for i, o in enumerate(order, start=1):
        o.rank = i
    best = order[0] if order else None
    target_needs = nothing.target_deficit_before > 0
    stranded = any(
        c.is_open
        and c.assigned_physician_id is None
        and c.routing_failures > 0
        and c.hospital_id in targets
        for c in ctx.analysis.state.consultations
    )
    if best is not None:
        improves = (
            best.outcome and best.outcome.target_deficit_after < nothing.target_deficit_before
        )
        if improves:
            best.recommended = True
            best.why.insert(
                0,
                f"Why this option: reduces the target deficit from "
                f"{nothing.target_deficit_before:g} to {best.outcome.target_deficit_after:g} "
                f"physician-min without creating new shortfalls "
                f"({len(best.outcome.new_shortfall_hospital_ids)}).",
            )
        else:
            esc = next((o for o in result if o.kind == "escalation" and o.feasible), None)
            pick = esc if (target_needs or stranded) and esc else result[0]
            pick.recommended = True
            pick.why.insert(
                0,
                "Why this option: no feasible staffing action reduces the target deficit"
                + (
                    "; escalate so a person decides."
                    if pick.kind == "escalation"
                    else "; there is nothing to fix in the planning window."
                ),
            )
    return RescueSimulation(
        as_of=as_of,
        data_version=ctx.analysis.state.data_version,
        horizon_minutes=ctx.horizon_minutes,
        target_hospital_ids=targets,
        target_label=target_label,
        options=order,
        objective=OBJECTIVE,
    )


def load_guardian_report(
    ctx: PlanningContext, staffing: StaffingResult, internals_options: Sequence[Option]
) -> LoadGuardianReport:
    as_of = ctx.as_of
    trap = staffing.trap
    if trap is None or not staffing.recommendations:
        return LoadGuardianReport(
            as_of=as_of,
            data_version=ctx.analysis.state.data_version,
            available=False,
            conclusion="No split shift is recommended now, so no joining physician needs "
            "protection. The guardian runs whenever the planner proposes one.",
        )
    rec = next(r for r in staffing.recommendations if r.physician_id == trap.physician_id)
    joiner = next(p for p in ctx.analysis.state.physicians if p.physician_id == rec.physician_id)
    creds = sorted(joiner.credentialed_hospital_ids)
    scope = list(rec.protection.routing_scope_hospital_ids)
    excluded = [h for h in creds if h not in scope]
    w = hypothetical_window(
        rec.physician_id, rec.display_name, rec.online_at, rec.offer_end, "guardian"
    )
    forgone = []
    for h in excluded:
        m = ctx.models.get(h)
        if m is None:
            continue
        before = m.deficit_physician_minutes()
        after = m.deficit_physician_minutes([w])
        forgone.append(
            {
                "hospital_id": h,
                "hospital_name": ctx.hospital_name(h),
                "deficit_without_joiner": round(before, 4),
                "deficit_if_unrestricted": round(after, 4),
                "forgone_reduction": round(before - after, 4),
            }
        )
    leaves_gap = [f for f in forgone if f["forgone_reduction"] > 0]
    conclusion = trap.conclusion + (
        " Protection forgoes coverage at "
        + ", ".join(f["hospital_name"] for f in leaves_gap)
        + " — consider widening the scope there."
        if leaves_gap
        else " Restricting the scope leaves no shortfall elsewhere (computed)."
    )
    to_dict = lambda o: o.model_dump(mode="json")  # noqa: E731
    return LoadGuardianReport(
        as_of=as_of,
        data_version=ctx.analysis.state.data_version,
        available=True,
        physician_id=rec.physician_id,
        display_name=rec.display_name,
        unrestricted=to_dict(trap.unrestricted),
        protected=to_dict(trap.protected),
        workload_limit=rec.protection.seeded_consult_count,
        scope_hospital_ids=scope,
        excluded_hospital_ids=excluded,
        forgone_coverage=forgone,
        release_conditions=[
            "Release the routing scope when the gap hospitals have no projected deficit for "
            "the rest of the rescue shift (recomputed on every state change).",
            "Release the seeded count when the joiner's actual consults this shift reach the "
            "seed (they are then treated on their real count).",
            "Release earlier only by coordinator decision, recorded in the audit log.",
        ],
        conclusion=conclusion,
    )


def options_by_hospital(candidates: Sequence[Candidate]) -> Mapping[str, list[str]]:
    out: dict[str, list[str]] = {}
    for c in candidates:
        if c.eligibility.eligible:
            for h in c.eligibility.gap_hospital_ids:
                out.setdefault(h, []).append(c.physician_id)
    return out
