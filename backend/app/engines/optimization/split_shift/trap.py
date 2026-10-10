"""Split-shift trap: protection policy and a modeled demonstration (pure, simulate-only).

The brief: a physician joining mid-shift starts with zero consults, so under rule 4 the
routing engine sends them nearly every call at every hospital they are credentialed for.

Protection (implementation choice, configurable in ``TrapPolicy``):
  1. routing scope = credentialed hospitals that have the gap (not the others);
  2. seeded consult count = median consults this shift of on-shift peers who cover the same
     hospitals, so rule 3/4 treat the joiner as an equal rather than an empty queue;
  3. synchronous capacity as for everyone else.

Demonstration: modeled arrivals (deterministic, from the baseline hourly *mean* — not a
forecast of real patients) are routed with the brief's rules 3-4 under (a) unrestricted
least-loaded routing with a raw zero count and (b) the protected policy. Busy time is not
modeled, which isolates the rule-4 effect the brief describes.
"""

from __future__ import annotations

import statistics
from datetime import UTC, datetime, timedelta

from app.engines.optimization.routing.problem import role_threshold
from app.engines.optimization.split_shift.candidates import Option, PlanningContext
from app.schemas.physician import Availability, PhysicianState
from app.schemas.staffing import TrapAnalysis, TrapProtection, TrapRoutingOutcome


def _peers(ctx: PlanningContext, hospitals: tuple[str, ...]) -> list[PhysicianState]:
    on = [p for p in ctx.analysis.state.physicians if p.on_shift]
    covering = [p for p in on if set(p.credentialed_hospital_ids) & set(hospitals)]
    return covering or on


def protection_for(option: Option, ctx: PlanningContext, credentials: list[str]) -> TrapProtection:
    trap = ctx.cfg.trap
    scope = list(option.hospitals)
    excluded = sorted(h for h in credentials if h not in scope)
    peers = _peers(ctx, option.hospitals)
    profile = next(
        (p for p in ctx.analysis.state.physicians if p.physician_id == option.physician_id), None
    )
    threshold, _ = role_threshold(profile.roster_role if profile else None, ctx.cfg)
    rationale: list[str] = []
    if trap.seed_policy == "median_peer" and peers:
        seed = int(statistics.median(p.consults_this_shift for p in peers))
        rationale.append(
            f"Consult count seeded to {seed}, the median of {len(peers)} on-shift peers "
            f"covering {', '.join(option.hospitals)}, instead of 0."
        )
    elif trap.seed_policy == "none":
        seed = 0
        rationale.append("No seeding (policy 'none'): the joiner starts at 0 consults.")
    else:
        seed = threshold + 1
        rationale.append(
            f"Consult count seeded to {seed} (just above the low-volume threshold {threshold}) "
            "so rule 3 does not give the joiner priority everywhere."
        )
    if excluded:
        rationale.append(
            f"Routing limited to the gap hospital(s) {', '.join(scope)}; not routed from "
            f"{', '.join(excluded)} even though credentialed there."
        )
    else:
        rationale.append(f"All credentialed hospitals ({', '.join(scope)}) have the gap.")
    rationale.append(
        f"Synchronous capacity {ctx.cfg.routing.sync_capacity} like every other physician."
    )
    return TrapProtection(
        routing_scope_hospital_ids=scope,
        excluded_credentialed_hospital_ids=excluded,
        seeded_consult_count=seed,
        seed_policy=trap.seed_policy,
        sync_capacity=ctx.cfg.routing.sync_capacity,
        rationale=rationale,
    )


def modeled_arrivals(
    ctx: PlanningContext, hospitals: list[str], start: datetime, end: datetime
) -> tuple[list[tuple[datetime, str]], list[str]]:
    """Deterministic arrivals: one each time the cumulative baseline mean crosses k - 0.5."""
    arrivals: list[tuple[datetime, str]] = []
    notes: list[str] = []
    for hid in sorted(hospitals):
        demand = ctx.analysis.demand_models.get(hid)
        if demand is None:
            notes.append(f"{hid}: no demand model; no modeled arrivals.")
            continue
        cumulative, k, missing = 0.0, 1, False
        moment = start
        while moment < end:
            row = demand.baseline_at(moment)
            if row is None:
                missing = True
            else:
                cumulative += row.mean_consults / 60
            if cumulative >= k - 0.5:
                arrivals.append((moment, hid))
                k += 1
            moment += timedelta(minutes=1)
        notes.append(f"{hid}: baseline mean expects {cumulative:.1f} consults in the window.")
        if missing:
            notes.append(f"{hid}: baseline missing for part of the window (no arrivals modeled).")
    arrivals.sort()
    return arrivals, notes


def _route(
    ctx: PlanningContext,
    option: Option,
    arrivals: list[tuple[datetime, str]],
    joiner_scope: set[str],
    joiner_seed: int,
    joiner_creds: list[str],
    policy: str,
) -> TrapRoutingOutcome:
    state = ctx.analysis.state
    never = datetime.min.replace(tzinfo=UTC)
    people: dict[str, dict] = {}
    for p in state.physicians:
        if not p.on_shift or p.availability is Availability.UNAVAILABLE:
            continue
        threshold, _ = role_threshold(p.roster_role, ctx.cfg)
        people[p.physician_id] = {
            "creds": set(p.credentialed_hospital_ids),
            "count": p.consults_this_shift,
            "last": p.signals.last_call_ended_at or never,
            "until": p.scheduled_shift.end if p.scheduled_shift else None,
            "from": state.as_of,
            "threshold": threshold,
        }
    joiner = next(p for p in state.physicians if p.physician_id == option.physician_id)
    threshold, _ = role_threshold(joiner.roster_role, ctx.cfg)
    people[option.physician_id] = {
        "creds": joiner_scope & set(joiner_creds),
        "count": joiner_seed,
        "last": never,
        "until": option.end,
        "from": option.online_at,
        "threshold": threshold,
    }
    gap = set(option.hospitals)
    to_joiner = at_gap = unrouted = 0
    by_hospital: dict[str, dict[str, int]] = {}
    for at, hid in arrivals:
        row = by_hospital.setdefault(hid, {"arrivals": 0, "to_joiner": 0})
        row["arrivals"] += 1
        pool = [
            pid
            for pid, x in people.items()
            if hid in x["creds"] and x["from"] <= at and (x["until"] is None or at < x["until"])
        ]
        if not pool:
            unrouted += 1
            continue
        chosen = min(
            pool,
            key=lambda pid: (
                people[pid]["count"] > people[pid]["threshold"],
                people[pid]["count"],
                people[pid]["last"],
                pid,
            ),
        )
        people[chosen]["count"] += 1
        people[chosen]["last"] = at
        if chosen == option.physician_id:
            to_joiner += 1
            row["to_joiner"] += 1
            at_gap += hid in gap
    peers = [x["count"] for pid, x in people.items() if pid != option.physician_id]
    joiner_final = people[option.physician_id]["count"] - joiner_seed
    return TrapRoutingOutcome(
        policy=policy,
        modeled_arrivals=len(arrivals),
        routed_to_joiner=to_joiner,
        routed_to_joiner_at_gap_hospitals=at_gap,
        routed_to_joiner_elsewhere=to_joiner - at_gap,
        joiner_final_consults=joiner_final,
        peer_median_consults=float(statistics.median(peers)) if peers else None,
        max_consults_any_physician=max([*peers, joiner_final]),
        unrouted=unrouted,
        by_hospital=dict(sorted(by_hospital.items())),
    )


def trap_analysis(ctx: PlanningContext, option: Option, protection: TrapProtection) -> TrapAnalysis:
    joiner = next(p for p in ctx.analysis.state.physicians if p.physician_id == option.physician_id)
    creds = sorted(joiner.credentialed_hospital_ids)
    start = option.online_at
    end = min(option.end, start + timedelta(minutes=ctx.cfg.trap.model_window_minutes))
    arrivals, notes = modeled_arrivals(ctx, creds, start, end)
    unrestricted = _route(ctx, option, arrivals, set(creds), 0, creds, "unrestricted_least_loaded")
    protected = _route(
        ctx,
        option,
        arrivals,
        set(protection.routing_scope_hospital_ids),
        protection.seeded_consult_count,
        creds,
        "protected",
    )
    name = joiner.display_name
    u, p = unrestricted, protected
    if not arrivals:
        conclusion = (
            "The baseline expects under one consult at these hospitals in the window (or has "
            "no usable baseline), so the trap cannot be shown numerically here; the protection "
            "policy still applies."
        )
    else:
        conclusion = (
            f"Unrestricted least-loaded routing would send {name} {u.routed_to_joiner} of "
            f"{u.modeled_arrivals} modeled consults ({u.routed_to_joiner_elsewhere} at "
            f"hospitals without a gap). With protection: {p.routed_to_joiner} "
            f"({p.routed_to_joiner_elsewhere} without a gap)."
        )
    assumptions = [
        "Arrivals are modeled from the baseline hourly mean (deterministic rounding), not "
        "forecast patients.",
        "Busy time is not modeled; each arrival goes to the routing-rule winner among "
        "physicians on shift and not Temporarily Unavailable.",
        "Ties: least recently assigned in the model (initially last call end), then id.",
        *notes,
    ]
    return TrapAnalysis(
        physician_id=option.physician_id,
        display_name=name,
        window_start=start,
        window_end=end,
        unrestricted=unrestricted,
        protected=protected,
        conclusion=conclusion,
        assumptions=assumptions,
    )
