"""Turn a dispatch solution into explained, reviewable recommendations (pure)."""

from __future__ import annotations

from app.engines.optimization.ordering import natural_key
from app.engines.optimization.routing.problem import (
    TIER_LABELS,
    ConsultView,
    DispatchProblem,
    describe_eligibility,
)
from app.engines.optimization.routing.solve import Penalties, objective
from app.schemas.dispatch import (
    DispatchPhysician,
    DispatchPlan,
    DispatchPolicyUsed,
    DispatchRecommendation,
    SkippedConsult,
    UnassignedConsult,
    WorkloadChange,
)

KIND_TEXT = {
    "assign": "Assign",
    "reassign": "Reassign (proposal)",
    "confirm_ringing": "Let the ringing call connect",
}
METHOD_PHRASE = {
    "min_cost_flow": "proposed for",
    "fallback_greedy": "proposed for",
    "least_loaded_baseline": "taken earlier in arrival order by",
}


def _consult_label(c: ConsultView) -> str:
    kind = c.consult_type or "consult (type unknown)"
    return f"{kind} {c.consult_id} at {c.hospital_name or c.hospital_id or 'unknown hospital'}"


def _priority_order(consults: list[ConsultView]) -> list[ConsultView]:
    return sorted(consults, key=lambda c: (-c.tier, -c.wait_key, c.consult_id))


def _compare(problem: DispatchProblem, cid: str, chosen: str, other: str) -> str:
    a = {x.name: x.value for x in problem.edges[(cid, chosen)].components}
    b = {x.name: x.value for x in problem.edges[(cid, other)].components}
    worse = sorted(
        (name.replace("_", " ") for name in b if b[name] > a.get(name, 0)),
    )
    ca, cb = problem.edges[(cid, chosen)].cost, problem.edges[(cid, other)].cost
    reason = f" ({', '.join(worse)})" if worse else ""
    return f"{problem.physicians[other].name}: cost {cb} vs {ca}{reason}"


def render_plan(
    problem: DispatchProblem, pairs: dict[str, str], method: str, pen: Penalties
) -> DispatchPlan:
    by_physician: dict[str, list[str]] = {}
    for cid, pid in pairs.items():
        by_physician.setdefault(pid, []).append(cid)
    consult_by_id = {c.consult_id: c for c in problem.consults}

    recommendations: list[DispatchRecommendation] = []
    for priority, c in enumerate(
        [c for c in _priority_order(problem.consults) if c.consult_id in pairs], start=1
    ):
        pid = pairs[c.consult_id]
        p = problem.physicians[pid]
        edge = problem.edges[(c.consult_id, pid)]
        options = problem.edges_for(c.consult_id)
        alternatives = [e.physician_id for e in options if e.physician_id != pid]
        explanation = [
            f"{KIND_TEXT[c.kind]}: {_consult_label(c)} → {p.name}.",
            f"Why this consult: {c.reason}; urgency {TIER_LABELS[c.tier]}"
            + (f", waiting {c.waiting_minutes:.0f} min" if c.waiting_minutes is not None else "")
            + ".",
        ]
        if alternatives:
            cheaper = [
                e
                for e in options
                if e.cost < edge.cost or (e.cost == edge.cost and e.physician_id < pid)
            ]
            if cheaper:
                taken = []
                for e in cheaper:
                    others = [x for x in by_physician.get(e.physician_id, []) if x != c.consult_id]
                    if others:
                        taken.append(
                            f"{problem.physicians[e.physician_id].name} was "
                            f"{METHOD_PHRASE[method]} {', '.join(others)}"
                        )
                if taken:
                    explanation.append(
                        "Lower-cost options were used elsewhere: " + "; ".join(taken) + "."
                    )
            nxt = next((e for e in options if e.physician_id != pid), None)
            if nxt is not None and nxt.cost >= edge.cost:
                explanation.append(
                    "Preferred over " + _compare(problem, c.consult_id, pid, nxt.physician_id) + "."
                )
        else:
            explanation.append(f"{p.name} is the only eligible physician.")
        if edge.overflow:
            explanation.append(
                f"{c.hospital_name or c.hospital_id} is outside {p.name}'s split-shift "
                f"hospitals ({', '.join(p.scope)}). Allowed as a last resort: the consult is "
                "past a time limit and no one else can take it."
            )
        if c.kind == "reassign":
            current = problem.physicians.get(c.current_physician_id or "")
            explanation.append(
                f"The consult stays with {current.name if current else c.current_physician_id} "
                "until a coordinator acts; nothing is reassigned automatically."
            )
        if c.kind == "confirm_ringing":
            explanation.append(
                "The routing engine already rings this physician; the optimizer keeps that "
                "route and does not offer the consult to anyone else."
            )
        explanation.append("Proposal only — not executed.")
        recommendations.append(
            DispatchRecommendation(
                consult_id=c.consult_id,
                hospital_id=c.hospital_id,
                hospital_name=c.hospital_name,
                consult_type=c.consult_type,
                consult_category=c.category,
                stage=c.stage,
                kind=c.kind,
                physician_id=pid,
                physician_name=p.name,
                current_physician_id=c.current_physician_id,
                priority=priority,
                urgency_tier=c.tier,
                urgency_label=TIER_LABELS[c.tier],
                waiting_minutes=c.waiting_minutes,
                eligibility_evidence=describe_eligibility(p, c),
                cost_breakdown=list(edge.components),
                edge_cost=edge.cost,
                workload=WorkloadChange(
                    consults_this_shift_before=p.actual_consults_this_shift,
                    consults_this_shift_after=p.actual_consults_this_shift + len(by_physician[pid]),
                    open_consults_before=p.open_consults,
                    open_consults_after=p.open_consults + len(by_physician[pid]),
                ),
                alternatives=alternatives,
                excluded=problem.exclusions.get(c.consult_id, []),
                uncertainty=list(p.uncertainty),
                explanation=explanation,
            )
        )

    unassigned: list[UnassignedConsult] = []
    for c in _priority_order(problem.consults):
        if c.consult_id in pairs:
            continue
        excluded = problem.exclusions.get(c.consult_id, [])
        options = problem.edges_for(c.consult_id)
        competing: list[str] = []
        label = _consult_label(c)
        if c.hospital_id is None:
            code, lines = (
                "missing_hospital",
                [f"{label}: no hospital on record, so credentialing cannot be checked."],
            )
        elif not problem.credentialed_on_shift.get(c.consult_id):
            code = "no_credentialed_on_shift"
            lines = [
                f"No on-shift physician is credentialed at {c.hospital_name or c.hospital_id}. "
                "This is a coverage problem: see split-shift recommendations."
            ]
        elif not options:
            code = "no_eligible_physician"
            lines = [f"Every credentialed on-shift physician is excluded for {label}:"]
            lines += [f"{x.display_name} — {'; '.join(x.reasons)}" for x in excluded]
        else:
            code = "capacity_used_by_higher_priority"
            for e in options:
                competing += [x for x in by_physician.get(e.physician_id, []) if x != c.consult_id]
            competing = sorted(set(competing))
            ranked = ", ".join(f"{x} ({TIER_LABELS[consult_by_id[x].tier]})" for x in competing)
            names = ", ".join(problem.physicians[e.physician_id].name for e in options)
            lines = [f"Eligible physicians ({names}) were {METHOD_PHRASE[method]} {ranked}."]
        if c.kind == "reassign":
            lines.append(
                "No alternative found: the consult stays with its current physician; escalate."
            )
        else:
            lines.append(
                "Retry at the next routing attempt (rule 5); escalate if it nears the standard."
            )
        unassigned.append(
            UnassignedConsult(
                consult_id=c.consult_id,
                hospital_id=c.hospital_id,
                hospital_name=c.hospital_name,
                consult_type=c.consult_type,
                stage=c.stage,
                urgency_tier=c.tier,
                urgency_label=TIER_LABELS[c.tier],
                waiting_minutes=c.waiting_minutes,
                reason_code=code,
                explanation=lines,
                excluded=excluded,
                competing_consult_ids=competing,
            )
        )
    return DispatchPlan(
        method=method,
        recommendations=recommendations,
        unassigned=unassigned,
        objective_cost=objective(problem, pairs, pen),
    )


def physician_rows(problem: DispatchProblem) -> list[DispatchPhysician]:
    rows = []
    for pid, p in sorted(problem.physicians.items(), key=lambda kv: natural_key(kv[0])):
        reserved = p.ringing_consult_ids and all(
            chk.passed or chk.code == "not_ringing" for chk in p.checks
        )
        uncertainty = list(p.uncertainty)
        if reserved:
            uncertainty.append(
                f"capacity reserved for the ringing call ({', '.join(p.ringing_consult_ids)})"
            )
        rows.append(
            DispatchPhysician(
                physician_id=pid,
                display_name=p.name,
                availability=p.availability,
                activity=p.activity,
                on_shift=p.on_shift,
                counts_for_coverage=p.counts_for_coverage,
                coverage_hospital_ids=list(p.coverage_hospitals),
                eligible_for_dispatch=p.eligible,
                effective_routing_capacity=p.capacity,
                routing_scope_hospital_ids=list(p.scope),
                consults_this_shift=p.actual_consults_this_shift,
                open_consults=p.open_consults,
                open_async_consults=p.open_async,
                low_volume=p.low_volume if p.low_volume_known else None,
                low_volume_threshold=p.threshold,
                minutes_since_last_call=(
                    round(p.minutes_since_last_call, 2)
                    if p.minutes_since_last_call is not None
                    else None
                ),
                minutes_to_shift_end=p.minutes_to_shift_end,
                checks=list(p.checks),
                uncertainty=uncertainty,
            )
        )
    return rows


def skipped_rows(problem: DispatchProblem) -> list[SkippedConsult]:
    return [
        SkippedConsult(consult_id=cid, stage=stage, assigned_physician_id=pid, reason=reason)
        for cid, stage, pid, reason in problem.skipped
    ]


def policy_used(problem: DispatchProblem) -> DispatchPolicyUsed:
    cfg = problem.config
    r = cfg.routing
    return DispatchPolicyUsed(
        rules=[
            "Brief rule 1: only on-shift physicians credentialed at the consult's hospital.",
            "Brief rule 2: exclude busy physicians (Synapse call/video, suspected external "
            "video), phones ringing for another call, and calls ended < "
            f"{r.call_cooldown_seconds // 60} min ago.",
            f"Brief rule 3: low volume (≤ {r.low_volume_day_max} day / ≤ "
            f"{r.low_volume_night_max} night consults this shift) gets priority — modeled as "
            "a cost on non-low-volume physicians.",
            "Brief rule 4: fewest consults this shift, then least recently answered — modeled "
            "as workload and recency costs.",
            "Brief rule 5: no eligible physician → unassigned with an explanation (retry).",
            "Temporarily Unavailable physicians are excluded (brief availability rules).",
        ],
        assumptions=[
            "Routing starts after triage; received-but-untriaged consults are skipped.",
            "Consults assigned to a Temporarily Unavailable or off-shift physician may be "
            "proposed for reassignment (before notes); never executed automatically.",
            "A call ringing to an eligible physician is kept on that route.",
            "Unknown day/night role uses the day low-volume threshold (flagged).",
            *problem.notes,
        ],
        implementation_choices=[
            "Lexicographic objective: urgency tier, then waiting time, then edge costs, "
            "then lower physician id.",
            "Urgency tier = 2 × alert severity (critical 2, warning 1, none 0) + 1 if stroke, "
            "consistent with the Phase 3 alert ranking (severity first, then stroke).",
            f"Synchronous capacity {r.sync_capacity} new consult per physician per round; "
            "asynchronous open consults add workload cost only.",
            "Split-shift scope: a physician on a split shift takes consults only at the gap "
            "hospitals, except a consult at another credentialed hospital that already has a "
            f"{cfg.trap.overflow_min_severity} alert or worse; that option costs more than any "
            "regular one, so it is used only when no one else can take the consult."
            if cfg.trap.overflow_outside_scope
            else "Split-shift scope: a physician on a split shift takes consults only at the "
            "gap hospitals.",
            "Edge-cost weights are bounded integers (see weights).",
        ],
        weights=cfg.weights.model_dump(),
        urgency_tiers=[f"{k}: {v}" for k, v in sorted(TIER_LABELS.items(), reverse=True)],
    )
