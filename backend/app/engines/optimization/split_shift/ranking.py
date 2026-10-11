"""Who to ask first for a coverage need: ranking, voluntary availability and cost (pure).

Voluntary availability is a preference, never a rule. Only physicians who pass every
split-shift rule (opt-in, credentialed at the short hospital, off shift, 10 h rest, weekly
hours, no clash with a scheduled shift, offer length, offer limits, declines) are ranked;
the dataset has no separate specialty field, so credentialing at the hospital is the
suitability check. Everyone else credentialed there is listed unranked, with the reason.

Ranking order (CHOICE, consistent with the CP-SAT plan):
  1. physicians in the optimizer's recommended plan for this need (what a proposal offers
     by default);
  2. deficit physician-minutes the physician's best valid offer removes at the need
     hospitals. With voluntary availability on, an offer that lies inside a window the
     physician volunteered counts as removing 1 / (1 - coverage_tolerance) times its
     deficit: a volunteer ranks first unless someone else removes more than the tolerance
     more (the same tolerance the CP-SAT re-solve allows per hospital). At equal coverage a
     volunteer always ranks first;
  3. lower estimated cost (fewer paid offer minutes, the optimizer's existing cost stage);
  4. online sooner;
  5. lower workload (fewer hours worked in the trailing 7 days);
  6. physician id.

``rank_without_voluntary`` repeats the ranking with nobody's availability counting and
with the reference plan (the CP-SAT plan without voluntary availability), so a movement is
exactly what volunteering changed. Cost uses the same hourly rate for every physician.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.engines.optimization.config import OptimizationConfig
from app.engines.optimization.ordering import natural_key
from app.engines.optimization.split_shift.candidates import (
    AvailabilityWindow,
    Candidate,
    Option,
    PlanningContext,
    proposed_window,
)
from app.engines.timeline import fmt_local
from app.schemas.staffing import (
    CostEstimate,
    NeedRanking,
    RankedCandidate,
    RankedOffer,
    VoluntaryMatch,
    VoluntaryStatus,
)

# --------------------------------------------------------------------------- cost --


def money(cfg: OptimizationConfig, amount: float) -> str:
    if cfg.cost.currency.upper() == "USD":
        return f"${amount:,.0f}"
    return f"{amount:,.0f} {cfg.cost.currency}"


def paid_minutes(cfg: OptimizationConfig, minutes: int, online_minutes: int) -> int:
    return minutes if cfg.cost.paid_includes_time_to_online else max(0, minutes - online_minutes)


def cost_estimate(
    cfg: OptimizationConfig,
    paid: int,
    covered: float,
    *,
    basis: str = "simulated",
    note: str | None = None,
) -> CostEstimate:
    """Paid minutes × the policy's hourly rate. ``covered``: deficit physician-minutes the
    offer(s) remove, for the cost-effectiveness figure."""
    rate = cfg.cost.hourly_rate
    amount = round(paid / 60 * rate, 2)
    per_hour = round(amount / (covered / 60), 2) if covered > 0 else None
    default = (
        f"{paid} paid min × {money(cfg, rate)}/h (illustrative rate, same for every physician)"
        + (" — projected if accepted, not confirmed" if basis == "simulated" else "")
    )
    return CostEstimate(
        basis=basis,  # type: ignore[arg-type]
        paid_minutes=paid,
        hourly_rate=rate,
        currency=cfg.cost.currency,
        amount=amount,
        covered_physician_minutes=round(covered, 4),
        cost_per_covered_hour=per_hour,
        note=note or default,
    )


# ------------------------------------------------------------- shortage overlap --


def shortage_periods(ctx: PlanningContext, hospitals: Sequence[str]) -> list[tuple]:
    """Merged intervals in the planning window when any of these short hospitals has a
    deficit (Phase 3 coverage engine)."""
    raw = sorted(
        (a, b)
        for hid in dict.fromkeys(hospitals)
        if hid in ctx.models and hid in ctx.gap_hospitals
        for a, b, deficit in ctx.models[hid].deficit_profile()
        if deficit > 0
    )
    merged: list[list] = []
    for a, b in raw:
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def window_overlap(
    window: AvailabilityWindow, periods: Sequence[tuple]
) -> tuple[float, datetime | None, datetime | None]:
    """Minutes of the shortage inside the window, and the first/last shortage moment in it."""
    minutes, first, last = 0.0, None, None
    for a, b in periods:
        lo, hi = max(a, window.start), min(b, window.end)
        if hi > lo:
            minutes += (hi - lo).total_seconds() / 60
            first = lo if first is None else min(first, lo)
            last = hi if last is None else max(last, hi)
    return round(minutes, 2), first, last


def _relevant_hospitals(ctx: PlanningContext, cand: Candidate, need: Sequence[str]) -> list[str]:
    creds = set(cand.state.credentialed_hospital_ids)
    return [h for h in need if h in creds and h in ctx.gap_hospitals]


def _window_text(ctx: PlanningContext, w: AvailabilityWindow, tz: str) -> str:
    return f"{fmt_local(w.start, tz)}–{fmt_local(w.end, tz)}"


def voluntary_match(
    ctx: PlanningContext,
    cand: Candidate,
    need: Sequence[str],
    *,
    option: Option | None,
    status: VoluntaryStatus | None = None,
    message: str | None = None,
) -> VoluntaryMatch | None:
    """The physician's most relevant volunteered window for this need, how it overlaps the
    shortage and (unless the caller decides) the status for ``option``."""
    windows = ctx.availability.get(cand.physician_id)
    if not windows:
        return None
    hospitals = _relevant_hospitals(ctx, cand, need)
    periods = shortage_periods(ctx, hospitals)
    tz = ctx.tz_for(hospitals or need or cand.state.credentialed_hospital_ids)
    inside = (
        ctx.window_for(cand.physician_id, option.start, option.end) if option is not None else None
    )
    window = inside or max(
        windows, key=lambda w: (window_overlap(w, periods)[0], -w.start.timestamp())
    )
    minutes, first, last = window_overlap(window, periods)
    text = _window_text(ctx, window, tz)
    names = ", ".join(ctx.hospital_name(h) for h in hospitals) or "their hospitals"
    if status is None:
        if not ctx.cfg.voluntary.enabled:
            status, message = "disabled", "Voluntary availability is switched off in the policy."
        elif not cand.eligibility.eligible:
            first_fail = next((c for c in cand.eligibility.checks if not c.passed), None)
            status = "not_eligible"
            message = f"Volunteered {text}, but cannot be asked under the split-shift rules" + (
                f": {first_fail.message}." if first_fail else "."
            )
        elif minutes <= 0:
            status = "no_shortage_overlap"
            message = f"Volunteered {text}; no shortage at {names} falls in that time."
        elif inside is not None:
            status = "applied"
            message = (
                f"Volunteered {text}, overlapping {minutes:g} min of the shortage at {names}; "
                "the offer fits inside that window."
            )
        else:
            status = "no_offer_fits"
            message = (
                f"Volunteered {text}, overlapping {minutes:g} min of the shortage, but no offer "
                "that passes every rule fits inside it (≥ "
                f"{ctx.cfg.staffing.min_offer_minutes} min of coverage plus "
                f"{cand.online_minutes} min to come online)."
            )
    return VoluntaryMatch(
        availability_id=window.availability_id,
        start_at=window.start,
        end_at=window.end,
        overlaps_shortage=minutes > 0,
        overlap_minutes=minutes,
        shortage_start=first,
        shortage_end=last,
        offer_within_window=inside is not None,
        status=status,
        message=message or "",
    )


# ------------------------------------------------------------------- ranking --


@dataclass
class _Scored:
    cand: Candidate
    option: Option
    reduction: float
    voluntary: bool
    score: float
    in_plan: bool
    best_voluntary: Option | None
    best_voluntary_reduction: float | None


class _Reductions:
    """Deficit removed at the need hospitals by one offer alone (cached; Phase 3 engine)."""

    def __init__(self, ctx: PlanningContext, need: Sequence[str]) -> None:
        self.ctx, self.need = ctx, list(need)
        self.cache: dict[tuple, float] = {}

    def __call__(self, o: Option) -> float:
        key = (o.physician_id, o.start, o.minutes, o.hospitals)
        if key not in self.cache:
            total = 0.0
            for hid in self.need:
                if hid in o.hospitals and hid in self.ctx.models:
                    total += self.ctx.base_deficit[hid] - self.ctx.models[
                        hid
                    ].deficit_physician_minutes([proposed_window(o)])
            self.cache[key] = round(total, 4)
        return self.cache[key]


def _hours(cand: Candidate) -> float | None:
    schedule = cand.profile.schedule if cand.profile else None
    return schedule.hours_worked_trailing_7d if schedule else None


def _order(
    ctx: PlanningContext,
    candidates: Sequence[Candidate],
    options: Sequence[Option],
    need: Sequence[str],
    plan: Sequence[Option],
    reduction: _Reductions,
    *,
    use_voluntary: bool,
) -> tuple[list[_Scored], list[Candidate]]:
    tol = ctx.cfg.voluntary.coverage_tolerance
    use_voluntary = use_voluntary and ctx.cfg.voluntary.enabled
    need_set = set(need)
    by_pid: dict[str, list[Option]] = {}
    for o in options:
        if need_set & set(o.hospitals):
            by_pid.setdefault(o.physician_id, []).append(o)
    in_plan = {o.physician_id: o for o in plan if need_set & set(o.hospitals)}

    def is_vol(o: Option) -> bool:
        return use_voluntary and ctx.window_for(o.physician_id, o.start, o.end) is not None

    def best(opts: list[Option]) -> Option:
        return max(
            opts,
            key=lambda o: (
                reduction(o),
                -o.minutes,
                -o.online_at.timestamp(),
                -o.start.timestamp(),
            ),
        )

    ranked: list[_Scored] = []
    unranked: list[Candidate] = []
    for cand in candidates:
        if not need_set & set(cand.state.credentialed_hospital_ids):
            continue
        opts = by_pid.get(cand.physician_id, [])
        if not cand.eligibility.eligible or not opts:
            unranked.append(cand)
            continue
        vol_opts = [o for o in opts if is_vol(o)]
        best_vol = best(vol_opts) if vol_opts else None
        if cand.physician_id in in_plan:
            chosen = in_plan[cand.physician_id]
            vol = is_vol(chosen)
        else:
            any_best = best(opts)
            vol_score = reduction(best_vol) / (1 - tol) if best_vol is not None else -1.0
            chosen, vol = (
                (best_vol, True)
                if best_vol is not None and vol_score >= reduction(any_best)
                else (any_best, False)
            )
        value = reduction(chosen)
        ranked.append(
            _Scored(
                cand=cand,
                option=chosen,
                reduction=value,
                voluntary=vol,
                score=value / (1 - tol) if vol else value,
                in_plan=cand.physician_id in in_plan,
                best_voluntary=best_vol,
                best_voluntary_reduction=reduction(best_vol) if best_vol is not None else None,
            )
        )
    ranked.sort(
        key=lambda s: (
            not s.in_plan,
            -round(s.score, 4),
            not s.voluntary,
            paid_minutes(ctx.cfg, s.option.minutes, s.cand.online_minutes),
            s.option.online_at,
            _hours(s.cand) if _hours(s.cand) is not None else float("inf"),
            natural_key(s.cand.physician_id),
        )
    )
    return ranked, unranked


def rank_for_need(
    ctx: PlanningContext,
    candidates: Sequence[Candidate],
    options: Sequence[Option],
    need: Sequence[str],
    plan: Sequence[Option],
    reference: Sequence[Option],
) -> NeedRanking:
    """Ranked physicians for ``need`` (hospital ids). ``plan`` is the recommended plan,
    ``reference`` the plan without voluntary availability."""
    need = [h for h in dict.fromkeys(need) if h in ctx.models]
    tz = ctx.tz_for(need)
    tol = ctx.cfg.voluntary.coverage_tolerance
    reduction = _Reductions(ctx, need)
    ranked, unranked = _order(ctx, candidates, options, need, plan, reduction, use_voluntary=True)
    before, _ = _order(ctx, candidates, options, need, reference, reduction, use_voluntary=False)
    before_rank = {s.cand.physician_id: i + 1 for i, s in enumerate(before)}
    best = max((s.reduction for s in ranked), default=0.0)
    base = round(sum(ctx.base_deficit.get(h, 0.0) for h in need), 4)
    names = ", ".join(ctx.hospital_name(h) for h in need)
    first_volunteer = next((s for s in ranked if s.voluntary), None)
    plan_names = [s.cand.state.display_name for s in ranked if s.in_plan]
    plan_lead = next((s for s in ranked if s.in_plan), None)

    entries: list[RankedCandidate] = []
    for i, s in enumerate(ranked):
        rank, cand, o = i + 1, s.cand, s.option
        prev = before_rank.get(cand.physician_id)
        movement = (prev - rank) if prev is not None else 0
        status: VoluntaryStatus | None = None
        message: str | None = None
        if ctx.availability.get(cand.physician_id) and ctx.cfg.voluntary.enabled:
            if s.voluntary and not s.in_plan and plan_lead is not None:
                lead = plan_lead.cand.state.display_name
                if s.reduction < (1 - tol) * plan_lead.reduction - 1e-9:
                    status = "outside_tolerance"
                    message = (
                        f"An offer inside the volunteered window removes {s.reduction:g} "
                        f"physician-minutes vs {plan_lead.reduction:g} for {lead}: more than "
                        f"{tol:.0%} less coverage, so the plan keeps {lead}. Can be added as "
                        "a backup."
                    )
                else:
                    status = "not_needed"
                    message = (
                        "Volunteered and eligible; the recommended plan already covers this "
                        f"need with {', '.join(plan_names)}. Can be added as a backup."
                    )
            elif not s.voluntary and s.best_voluntary is not None:
                status = "outside_tolerance"
                message = (
                    f"An offer inside the volunteered window removes "
                    f"{s.best_voluntary_reduction:g} physician-minutes vs {s.reduction:g} for "
                    f"this offer: more than {tol:.0%} less coverage, so it is ranked on its "
                    "best offer instead."
                )
        match = voluntary_match(ctx, cand, need, option=o, status=status, message=message)
        if match is not None and match.status == "applied" and not s.voluntary:
            match = match.model_copy(update={"status": "outside_tolerance"})
        cost = cost_estimate(
            ctx.cfg, paid_minutes(ctx.cfg, o.minutes, cand.online_minutes), s.reduction
        )
        hours = _hours(cand)
        remaining = cand.eligibility.remaining_weekly_hours
        reasons = [
            "In the optimizer's recommended plan for this need."
            if s.in_plan
            else "Not in the recommended plan: ranked by coverage, then cost, online time "
            "and workload.",
            f"Removes {s.reduction:g} of {base:g} deficit physician-minutes at {names} over the "
            f"next {ctx.horizon_minutes} min"
            + (f" ({s.reduction / best:.0%} of the best offer)." if best > 0 else "."),
        ]
        if match is not None:
            reasons.append(match.message)
        reasons += [
            f"Offer {fmt_local(o.start, tz)}–{fmt_local(o.end, tz)} ({o.minutes} min); online "
            f"about {fmt_local(o.online_at, tz)} ({cand.online_minutes} min to come online).",
            f"Estimated cost {money(ctx.cfg, cost.amount)} ({cost.paid_minutes} paid min, "
            "simulated).",
        ]
        if hours is not None:
            reasons.append(
                f"Workload: {hours:g} h worked in the trailing 7 days"
                + (f"; {remaining:g} h left under the limit." if remaining is not None else ".")
            )
        if movement > 0:
            reasons.insert(
                0,
                f"Moved up from #{prev} to #{rank}: voluntarily available for the whole offer, "
                f"and its coverage is within {tol:.0%} of the best alternative, so the "
                "physician who already said yes ranks first.",
            )
        elif movement < 0 and first_volunteer is not None:
            reasons.insert(
                0,
                f"Moved down from #{prev} to #{rank}: "
                f"{first_volunteer.cand.state.display_name} volunteered for this time with "
                f"coverage within {tol:.0%}.",
            )
        badge = " · voluntarily available" if s.voluntary else ""
        entries.append(
            RankedCandidate(
                rank=rank,
                rank_without_voluntary=prev,
                movement=movement,
                physician_id=cand.physician_id,
                display_name=cand.state.display_name,
                eligible=True,
                in_plan=s.in_plan,
                voluntary=match,
                voluntary_preference_applied=s.voluntary,
                offer=RankedOffer(
                    start_at=o.start,
                    end_at=o.end,
                    minutes=o.minutes,
                    online_at=o.online_at,
                    hospital_ids=list(o.hospitals),
                ),
                coverage_physician_minutes=s.reduction,
                coverage_share_of_best=round(s.reduction / best, 4) if best > 0 else None,
                minutes_to_come_online=cand.online_minutes,
                hours_worked_trailing_7d=hours,
                remaining_weekly_hours=remaining,
                cost=cost,
                summary=f"#{rank}{badge}: removes {s.reduction:g} physician-min, online "
                f"{fmt_local(o.online_at, tz)}, est. {money(ctx.cfg, cost.amount)}",
                reasons=reasons,
            )
        )
    for cand in sorted(unranked, key=lambda c: natural_key(c.physician_id)):
        match = voluntary_match(ctx, cand, need, option=None)
        if match is not None and cand.eligibility.eligible and match.status == "no_offer_fits":
            match = match.model_copy(
                update={"message": "Eligible elsewhere, but no valid offer for this need."}
            )
        why = (
            cand.eligibility.summary
            if not cand.eligibility.eligible
            else f"{cand.state.display_name} has no valid offer for {names} (e.g. declined it)."
        )
        entries.append(
            RankedCandidate(
                rank=None,
                rank_without_voluntary=None,
                physician_id=cand.physician_id,
                display_name=cand.state.display_name,
                eligible=False,
                in_plan=False,
                voluntary=match,
                minutes_to_come_online=cand.online_minutes,
                hours_worked_trailing_7d=_hours(cand),
                remaining_weekly_hours=cand.eligibility.remaining_weekly_hours,
                summary=f"Not ranked: {why}",
                reasons=[why, *([match.message] if match is not None else [])],
            )
        )
    periods = shortage_periods(ctx, need)
    return NeedRanking(
        hospital_ids=need,
        hospital_names=[ctx.hospital_name(h) for h in need],
        shortage_start=periods[0][0] if periods else None,
        shortage_end=periods[-1][1] if periods else None,
        entries=entries,
        method=[
            "Only physicians who pass every split-shift rule are ranked (credentialed at the "
            "short hospital, opted in, off shift, 10 h rest, ≤ 60 h in 7 days, no clash with "
            "a scheduled shift, offer ≥ 2 h after coming online, offer limits, not declined).",
            "Order: the optimizer's recommended plan first, then deficit removed at "
            f"{names}, then estimated cost, online time, hours worked in the last 7 days.",
            f"Voluntary availability: an offer inside a volunteered window counts as removing "
            f"1/(1 − {tol:g}) of its deficit, so a volunteer ranks first unless another "
            f"physician removes more than {tol:.0%} more of the gap. It never makes anyone "
            "eligible and never assigns a shift.",
            f"Cost: paid offer minutes × {money(ctx.cfg, ctx.cfg.cost.hourly_rate)}/h "
            "(illustrative, same for every physician; volunteering never lowers the rate).",
        ],
    )


__all__ = [
    "cost_estimate",
    "money",
    "paid_minutes",
    "rank_for_need",
    "shortage_periods",
    "voluntary_match",
    "window_overlap",
]
