"""Split-shift trap: protection policy and a modeled demonstration (pure, simulate-only).

The brief: a physician joining mid-shift starts with zero consults, so under rule 4 the
routing engine sends them nearly every call at every hospital they are credentialed for.

Protection (implementation choice, configurable in ``TrapPolicy``):
  1. routing scope = credentialed hospitals that have the gap (not the others);
  2. seeded consult count = median consults of the physicians who will be working at the
     same hospitals when the joiner comes online, so rule 3/4 treat the joiner as an equal
     rather than an empty queue. Peers who leave before then do not count; the seed is
     estimated at proposal and recalculated at go-live from the physicians working then;
  3. synchronous capacity as for everyone else.

Demonstration: modeled arrivals (deterministic, from the baseline hourly *mean* — not a
forecast of real patients) are routed with the brief's rules 3-4 under (a) unrestricted
least-loaded routing with a raw zero count and (b) the protected policy. Busy time is not
modeled, which isolates the rule-4 effect the brief describes.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta

from app.engines.coverage_prediction import HospitalCoverageModel
from app.engines.optimization.config import OptimizationConfig
from app.engines.optimization.routing.problem import (
    network_timezone,
    role_threshold,
    shift_start_of,
)
from app.engines.optimization.split_shift.candidates import Option, PlanningContext
from app.engines.timeline import fmt_local
from app.schemas.physician import PhysicianState
from app.schemas.staffing import TrapAnalysis, TrapProtection, TrapRoutingOutcome


def routing_count(p: PhysicianState) -> int:
    """The consult count routing uses for ``p``: 0 before their shift has started, and an
    active split shift's seeded count plus the consults taken since joining."""
    if not p.on_shift:
        return 0
    temp = p.temporary_shift
    if temp is not None and temp.phase == "active":
        return temp.seeded_consult_count + p.consults_this_shift
    return p.consults_this_shift


def seed_peers(
    physicians: Sequence[PhysicianState],
    models: Mapping[str, HospitalCoverageModel],
    joiner_id: str,
    hospitals: Iterable[str],
    at: datetime,
    overlap_minutes: int = 0,
) -> tuple[list[tuple[PhysicianState, int]], bool]:
    """Physicians who will be working at ``hospitals`` at ``at`` (when the joiner comes
    online), each with the count routing will use. Read from the coverage windows: a peer
    whose shift ends before ``at`` is left out, and one whose shift starts before ``at`` is
    included (at 0 consults until it starts). Other split shifts not yet active and what-if
    windows are ignored. If nobody works at ``hospitals`` then, everyone working anywhere at
    ``at`` is used instead; the flag is True when the peers cover ``hospitals``. With
    ``overlap_minutes``, a peer must still be working that long after ``at``."""
    by_id = {p.physician_id: p for p in physicians}
    until = at + timedelta(minutes=overlap_minutes)

    def working(hids: Iterable[str]) -> list[str]:
        ids = {
            w.physician_id
            for hid in hids
            if hid in models
            for w in models[hid].windows
            if w.physician_id != joiner_id
            and not w.proposed
            and not w.pending
            and w.covers(at)
            and (w.end is None or w.end >= until)
        }
        return sorted(i for i in ids if i in by_id)

    ids = working(hospitals)
    covering = bool(ids)
    if not covering:
        ids = working(models)
    return [(by_id[i], routing_count(by_id[i])) for i in ids], covering


def seed_count(
    cfg: OptimizationConfig,
    joiner_role: str | None,
    peers: Sequence[tuple[PhysicianState, int]],
    covering: bool,
    hospitals: Sequence[str],
    when: str,
    *,
    joiner_start: datetime | None = None,
    tz: str = "UTC",
) -> tuple[int, str]:
    """The joiner's seeded routing count under the trap policy, with one line saying why.
    ``when`` names the moment the peers were taken at (e.g. "at go-live (20:00 EDT)")."""
    policy = cfg.trap.seed_policy
    threshold, _ = role_threshold(joiner_role, cfg, shift_start=joiner_start, tz=tz)
    if policy == "median_peer" and peers:
        seed = int(statistics.median(n for _, n in peers))
        if covering:
            who = ", ".join(f"{p.display_name} {n}" for p, n in peers)
            where = f"working at {', '.join(hospitals)} {when} ({who})"
        else:
            where = f"working anywhere {when} (nobody else works at {', '.join(hospitals)})"
        return seed, (
            f"Consult count seeded to {seed}, the median of the {len(peers)} physician(s) "
            f"{where}, instead of 0."
        )
    if policy == "none":
        return 0, "No seeding (policy 'none'): the joiner starts at 0 consults."
    return threshold + 1, (
        f"Consult count seeded to {threshold + 1} (just above the low-volume threshold "
        f"{threshold}) so rule 3 does not give the joiner priority everywhere."
    )


def protection_for(option: Option, ctx: PlanningContext, credentials: list[str]) -> TrapProtection:
    trap = ctx.cfg.trap
    scope = list(option.hospitals)
    excluded = sorted(h for h in credentials if h not in scope)
    peers, covering = seed_peers(
        ctx.analysis.state.physicians,
        ctx.models,
        option.physician_id,
        scope,
        option.online_at,
        trap.seed_peer_overlap_minutes,
    )
    profile = next(
        (p for p in ctx.analysis.state.physicians if p.physician_id == option.physician_id), None
    )
    online = fmt_local(option.online_at, ctx.tz_for(scope))
    seed, line = seed_count(
        ctx.cfg,
        profile.roster_role if profile else None,
        peers,
        covering,
        scope,
        f"when they come online ({online})",
        joiner_start=option.start,
        tz=network_timezone(ctx.analysis.state.hospitals),
    )
    rationale = [line]
    if trap.seed_policy == "median_peer":
        rationale.append("Estimated now; recalculated at go-live from the physicians working then.")
    if excluded:
        rationale.append(
            f"Routing limited to the gap hospital(s) {', '.join(scope)}; not routed from "
            f"{', '.join(excluded)} even though credentialed there"
            + (
                f", unless a consult there already has a {trap.overflow_min_severity} alert "
                "and no one else can take it."
                if trap.overflow_outside_scope
                else "."
            )
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
    by_id = {p.physician_id: p for p in state.physicians}
    net_tz = network_timezone(state.hospitals)
    # Who works where and when comes from the coverage windows, like the seed: peers who
    # leave stop taking consults, and a shift that starts later (e.g. a night physician)
    # joins at its start with the consult count routing would use (0 before it starts).
    people: dict[str, dict] = {}
    for hid, model in ctx.models.items():
        for w in model.windows:
            p = by_id.get(w.physician_id)
            if p is None or w.physician_id == option.physician_id or w.proposed or w.pending:
                continue
            if w.physician_id not in people:
                threshold, _ = role_threshold(
                    p.roster_role, ctx.cfg, shift_start=shift_start_of(p) or w.start, tz=net_tz
                )
                people[w.physician_id] = {
                    "spans": {},
                    "count": routing_count(p),
                    "last": (p.signals.last_call_ended_at if p.on_shift else None) or never,
                    "threshold": threshold,
                }
            people[w.physician_id]["spans"].setdefault(hid, []).append((w.start, w.end))
    joiner = next(p for p in state.physicians if p.physician_id == option.physician_id)
    threshold, _ = role_threshold(joiner.roster_role, ctx.cfg, shift_start=option.start, tz=net_tz)
    people[option.physician_id] = {
        "spans": {
            hid: [(option.online_at, option.end)] for hid in joiner_scope & set(joiner_creds)
        },
        "count": joiner_seed,
        "last": never,
        "threshold": threshold,
    }

    def working(x: dict, hid: str, at: datetime) -> bool:
        return any(a <= at and (b is None or at < b) for a, b in x["spans"].get(hid, ()))

    gap = set(option.hospitals)
    to_joiner = at_gap = unrouted = 0
    by_hospital: dict[str, dict[str, int]] = {}
    for at, hid in arrivals:
        row = by_hospital.setdefault(hid, {"arrivals": 0, "to_joiner": 0})
        row["arrivals"] += 1
        pool = [pid for pid, x in people.items() if working(x, hid, at)]
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
        "Busy time is not modeled; each arrival goes to the routing-rule winner among the "
        "physicians counted at that hospital at that minute (coverage windows: shifts that end "
        "drop out, shifts that start later join, Temporarily Unavailable excluded).",
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
