"""Split-shift candidate eligibility and offer options (pure).

Every off-shift roster physician is evaluated against every rule, even after one fails,
so the coordinator sees the full picture ("who was considered, who was excluded and
why"). Missing data never passes: a rule that needs a missing value fails with
``missing_data=True``.

Rules (BRIEF unless marked):
  opt_in               opted in to split-shift offers
  credentialed_at_gap  credentialed at >= 1 hospital with a gap (elsewhere does not help)
  rest_10h             >= 10 h since last shift ended, measured at the offered start
  weekly_hours         trailing-7-day hours + offered hours <= 60
  no_overlap           the offer ends before any scheduled shift starts
  min_length           offer >= 2 h *after* the time to come online (it counts against the
                       offer's value); judged on the longest offer the other limits allow
  notification_limits  <= 1 open offer and <= 3 offers this week (system offer log)
  not_declined         has not declined an offer for this hospital that is still running
                       (implementation choice: a "no" is not asked again for the same gap)
  off_shift            not currently on shift (structural)

Rolling window (assumption, conservative): the dataset gives hours worked in the trailing
7 days as of the simulation time. For an offer ending at E the true window is (E-7d, E];
work that might age out between now and E is unknown, so it is NOT subtracted (this can
only over-count hours, never under-count). Hours of proposals not yet accepted are not
added; accepted split shifts are, and a split shift already worked also sets the last
shift end for the rest rule (Phase 5 workflow overlay updates the profile).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.engines.analysis import OperationalAnalysis
from app.engines.coverage_prediction import (
    HospitalCoverageModel,
    Window,
    build_coverage_models,
    hypothetical_window,
)
from app.engines.optimization.config import OptimizationConfig
from app.engines.optimization.ordering import natural_key
from app.engines.timeline import fmt_local, fmt_local_datetime
from app.schemas.dispatch import RuleCheck
from app.schemas.physician import Physician, PhysicianState
from app.schemas.staffing import CandidateEligibility


@dataclass(frozen=True)
class Decline:
    """A declined split-shift offer, from the Phase 5 offer log. Until the offer would have
    ended, its hospitals are not offered to that physician again: the same gap, same "no"."""

    offer_id: str
    hospital_ids: tuple[str, ...]
    declined_at: datetime
    until: datetime


@dataclass(frozen=True)
class AvailabilityWindow:
    """A window an off-shift physician volunteered for an extra shift (off-shift portal).
    A preference only: it never changes eligibility and never assigns a shift."""

    availability_id: str
    physician_id: str
    start: datetime
    end: datetime


@dataclass
class PlanningContext:
    analysis: OperationalAnalysis
    cfg: OptimizationConfig
    as_of: datetime
    plan_end: datetime
    horizon_minutes: int
    models: dict[str, HospitalCoverageModel]
    gap_hospitals: list[str]
    """Hospitals short within ``lookahead_minutes``: the only ones a split shift may target."""
    base_deficit: dict[str, float]
    tz: str
    lookahead_minutes: int = 90
    later_gaps: dict[str, datetime] = field(default_factory=dict)
    """Hospitals whose first gap starts after the look-ahead but inside the planning window
    (not acted on yet; re-checked as the clock moves), with that start time."""
    offer_log: dict[str, tuple[int, int]] = field(default_factory=dict)
    """physician_id -> (open offers or committed split shifts, offers sent in the rolling
    7 days), from the Phase 5 workflow tables (see app.services.workflow)."""
    declines: dict[str, list[Decline]] = field(default_factory=dict)
    """physician_id -> declined offers in the current dataset (Phase 5 offer log)."""
    availability: dict[str, list[AvailabilityWindow]] = field(default_factory=dict)
    """physician_id -> active voluntary availability windows (off-shift portal)."""

    def window_for(
        self, physician_id: str, start: datetime, end: datetime
    ) -> AvailabilityWindow | None:
        """The volunteered window that contains the whole offer [start, end), if any (and
        voluntary availability is enabled)."""
        if not self.cfg.voluntary.enabled:
            return None
        for w in sorted(self.availability.get(physician_id, []), key=lambda w: w.start):
            if w.start <= start and end <= w.end:
                return w
        return None

    def declined_hospitals(self, physician_id: str) -> dict[str, Decline]:
        """Hospitals this physician declined an offer for that is still running at ``as_of``
        (latest decline per hospital)."""
        blocked: dict[str, Decline] = {}
        for d in sorted(self.declines.get(physician_id, []), key=lambda d: d.declined_at):
            if d.declined_at <= self.as_of < d.until:
                for hid in d.hospital_ids:
                    blocked[hid] = d
        return blocked

    def tz_for(self, hospitals) -> str:
        """Time zone of the first listed hospital (explanations use hospital-local time)."""
        for hid in sorted(hospitals):
            if hid in self.models:
                return self.models[hid].tz
        return self.tz

    def hospital_name(self, hid: str) -> str:
        model = self.models.get(hid)
        return model.hospital.name if model else hid


def build_planning_context(
    analysis: OperationalAnalysis, cfg: OptimizationConfig
) -> PlanningContext:
    """Phase 3 coverage engine re-run over the (longer) staffing planning window.

    A hospital is short (a split-shift target) only if its first gap starts within the
    shortage look-ahead; gaps later in the planning window are reported, not acted on.
    """
    state = analysis.state
    lookahead = cfg.staffing.shortage_lookahead_minutes or analysis.coverage.horizon_minutes
    horizon = max(cfg.staffing.planning_horizon_minutes, lookahead)
    models = build_coverage_models(
        state, analysis.reference, analysis.demand_models, analysis.config.coverage, horizon
    )
    base = {hid: round(m.deficit_physician_minutes(), 4) for hid, m in models.items()}
    lookahead_end = state.as_of + timedelta(minutes=lookahead)
    first_gap = {
        hid: min(a for a, _, d in m.deficit_profile() if d > 0)
        for hid, m in models.items()
        if base[hid] > 0
    }
    gaps = sorted(hid for hid, start in first_gap.items() if start < lookahead_end)
    later = {
        hid: start
        for hid, start in sorted(first_gap.items(), key=lambda kv: (kv[1], kv[0]))
        if hid not in gaps
    }
    tz = models[gaps[0]].tz if gaps else (state.hospitals[0].timezone if state.hospitals else "UTC")
    return PlanningContext(
        analysis=analysis,
        cfg=cfg,
        as_of=state.as_of,
        plan_end=state.as_of + timedelta(minutes=horizon),
        horizon_minutes=horizon,
        models=models,
        gap_hospitals=gaps,
        base_deficit=base,
        tz=tz,
        lookahead_minutes=lookahead,
        later_gaps=later,
    )


@dataclass
class Candidate:
    state: PhysicianState
    profile: Physician | None
    eligibility: CandidateEligibility
    scope: tuple[str, ...]
    earliest_start: datetime | None
    latest_end: datetime | None
    max_minutes: int | None
    online_minutes: int

    @property
    def physician_id(self) -> str:
        return self.state.physician_id


def _ceil_minute(moment: datetime) -> datetime:
    if moment.second or moment.microsecond:
        return moment.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return moment


def _hours(value: float) -> str:
    return f"{value:.1f} h" if value != int(value) else f"{int(value)} h"


def min_length_check(
    minutes: int,
    online_minutes: int,
    online_assumed: bool,
    min_minutes: int,
    limited_by: str | None = None,
) -> tuple:
    """BRIEF: an offer is at least 2 h long and the time to come online counts against what
    it is worth, so the *useful* part (offer minus time to come online) must be >= 2 h."""
    effective = minutes - online_minutes
    passed = minutes >= min_minutes and effective >= min_minutes
    online = f"{online_minutes} min to come online{' (assumed)' if online_assumed else ''}"
    longest = f"longest allowed offer ({limited_by}) " if limited_by else ""
    if passed:
        message = f"{longest}{minutes} min offer gives {effective} min of coverage after {online}"
    elif minutes < min_minutes:
        message = f"{longest}{minutes} min is below the {min_minutes}-minute minimum"
    else:
        message = (
            f"{longest}{minutes} min offer is worth only {max(0, effective)} min after {online} "
            f"(needs ≥ {min_minutes} min of coverage)"
        )
    return (
        "min_length",
        "Offer ≥ 2 h after time to come online",
        passed,
        f"{minutes} min offer, {max(0, effective)} min after {online}",
        f"≥ {min_minutes} min of coverage",
        message,
    )


def offer_checks(
    p: PhysicianState,
    profile: Physician | None,
    start: datetime,
    minutes: int,
    scope: tuple[str, ...],
    ctx: PlanningContext,
    online_minutes: int,
    online_assumed: bool,
) -> list[RuleCheck]:
    """Every split-shift rule evaluated for one concrete offer [start, start + minutes)."""
    st = ctx.cfg.staffing
    tz = ctx.tz_for(scope or p.credentialed_hospital_ids)
    schedule = profile.schedule if profile else None
    end = start + timedelta(minutes=minutes)
    checks: list[RuleCheck] = []

    def add(code, label, passed, value, threshold, message, source="brief", missing=False):
        checks.append(
            RuleCheck(
                code=code,
                label=label,
                passed=passed,
                value=value,
                threshold=threshold,
                message=message,
                source=source,
                missing_data=missing,
            )
        )

    opt_in = profile.split_shift_opt_in if profile else None
    add(
        "opt_in",
        "Opted in to split-shift offers",
        opt_in is True,
        "missing" if opt_in is None else ("yes" if opt_in else "no"),
        "yes",
        "opted in"
        if opt_in
        else ("opt-in not recorded — treated as not opted in" if opt_in is None else "opted out"),
        missing=opt_in is None,
    )

    creds = sorted(p.credentialed_hospital_ids)
    gap_creds = [h for h in creds if h in ctx.gap_hospitals]
    off_scope = [h for h in scope if h not in creds]
    ok = bool(scope) and not off_scope and any(h in ctx.gap_hospitals for h in scope)
    if not ctx.gap_hospitals:
        msg = f"no hospital is short in the next {ctx.lookahead_minutes} min"
    elif off_scope:
        msg = f"not credentialed at {', '.join(off_scope)}"
    elif not gap_creds:
        msg = (
            f"credentialed only at {', '.join(creds) or 'no hospital'}; none has a gap "
            f"(gaps: {', '.join(ctx.gap_hospitals)})"
        )
    else:
        msg = f"credentialed at gap hospital(s) {', '.join(gap_creds)}"
    add(
        "credentialed_at_gap",
        "Credentialed at a gap hospital",
        ok,
        ", ".join(creds) or "none",
        f"any of {', '.join(ctx.gap_hospitals) or '—'}",
        msg,
    )

    off = not p.on_shift
    add(
        "off_shift",
        "Currently off shift",
        off,
        "off shift" if off else "on shift",
        "off shift",
        "off shift" if off else "already on shift — not a split-shift candidate",
        source="implementation_choice",
    )

    last_end = schedule.last_shift_ended_at if schedule else None
    if last_end is None:
        add(
            "rest_10h",
            "≥ 10 h rest at offered start",
            False,
            "missing",
            f"≥ {_hours(st.rest_hours)}",
            "last shift end not recorded — rest cannot be verified",
            missing=True,
        )
    else:
        rest = (start - last_end).total_seconds() / 3600
        rested_at = last_end + timedelta(hours=st.rest_hours)
        passed = rest >= st.rest_hours
        add(
            "rest_10h",
            "≥ 10 h rest at offered start",
            passed,
            f"{rest:.2f} h at {fmt_local(start, tz)} (last shift ended "
            f"{fmt_local_datetime(last_end, tz)})",
            f"≥ {_hours(st.rest_hours)}",
            f"{rest:.1f} h of rest at the offered start"
            if passed
            else f"only {rest:.1f} h of rest at {fmt_local(start, tz)}; 10 h reached at "
            f"{fmt_local_datetime(rested_at, tz)}",
        )

    hours = schedule.hours_worked_trailing_7d if schedule else None
    if hours is None:
        add(
            "weekly_hours",
            "Trailing 7-day hours + offer ≤ 60",
            False,
            "missing",
            f"≤ {_hours(st.weekly_hour_limit)}",
            "hours worked in the trailing 7 days not recorded — limit cannot be verified",
            missing=True,
        )
    else:
        total = hours + minutes / 60
        passed = total <= st.weekly_hour_limit + 1e-9
        add(
            "weekly_hours",
            "Trailing 7-day hours + offer ≤ 60",
            passed,
            f"{_hours(hours)} + {_hours(minutes / 60)} = {_hours(total)}",
            f"≤ {_hours(st.weekly_hour_limit)}",
            f"{_hours(total)} including this offer"
            if passed
            else f"{_hours(hours)} worked + {_hours(minutes / 60)} offered exceeds "
            f"{_hours(st.weekly_hour_limit)}",
        )

    nxt = schedule.next_shift_starts_at if schedule else None
    if nxt is None:
        add(
            "no_overlap",
            "No overlap with a scheduled shift",
            False,
            "missing",
            "offer ends before next shift",
            "next scheduled shift not recorded — overlap cannot be ruled out",
            missing=True,
        )
    else:
        passed = end <= nxt
        add(
            "no_overlap",
            "No overlap with a scheduled shift",
            passed,
            f"offer {fmt_local(start, tz)}–{fmt_local(end, tz)}; next shift "
            f"{fmt_local_datetime(nxt, tz)}",
            "offer ends before next shift",
            "ends before the next scheduled shift"
            if passed
            else f"overlaps the scheduled shift starting {fmt_local_datetime(nxt, tz)} "
            "(a scheduled shift is not a split-shift offer)",
        )

    add(*min_length_check(minutes, online_minutes, online_assumed, st.min_offer_minutes))

    open_offers, week = ctx.offer_log.get(p.physician_id, (0, 0))
    passed = (
        open_offers < st.max_open_offers_per_physician
        and week < st.max_offers_per_physician_per_week
    )
    add(
        "notification_limits",
        "≤ 1 open offer, ≤ 3 offers / week",
        passed,
        f"{open_offers} open, {week} in 7 days (system offer log)",
        f"< {st.max_open_offers_per_physician} open, < {st.max_offers_per_physician_per_week}/week",
        "within notification limits"
        if passed
        else (
            f"already has {open_offers} open offer or committed split shift (limit "
            f"{st.max_open_offers_per_physician})"
            if open_offers >= st.max_open_offers_per_physician
            else f"already sent {week} offers in the rolling 7 days (limit "
            f"{st.max_offers_per_physician_per_week})"
        ),
    )

    blocked = ctx.declined_hospitals(p.physician_id)
    hit = sorted(h for h in scope if h in blocked and h in ctx.gap_hospitals)
    if hit:
        d = blocked[hit[0]]
        message = (
            f"declined an offer for {', '.join(ctx.hospital_name(h) for h in hit)} at "
            f"{fmt_local(d.declined_at, tz)} ({d.offer_id}); not asked again for it before "
            f"{fmt_local(d.until, tz)}"
        )
    else:
        message = "has not declined an offer for this gap"
    add(
        "not_declined",
        "Has not declined this gap",
        not hit,
        ", ".join(f"declined {h} until {fmt_local(blocked[h].until, tz)}" for h in hit) or "none",
        "no declined offer still running for these hospitals",
        message,
        source="implementation_choice",
    )
    return checks


def evaluate_candidate(
    p: PhysicianState, profile: Physician | None, ctx: PlanningContext
) -> Candidate:
    st = ctx.cfg.staffing
    schedule = profile.schedule if profile else None
    online = schedule.minutes_to_come_online if schedule else None
    online_assumed = online is None
    online_minutes = st.assumed_online_minutes_if_missing if online is None else online
    if not st.online_time_counts_against_value:
        online_minutes = 0
    creds = sorted(p.credentialed_hospital_ids)
    # A hospital whose offer this physician declined (still running) is left out; if no gap
    # hospital is left, the not_declined rule fails below.
    blocked = ctx.declined_hospitals(p.physician_id)
    scope = tuple(h for h in creds if h in ctx.gap_hospitals and h not in blocked)
    if not ctx.cfg.trap.restrict_scope_to_gap_hospitals:
        scope = tuple(h for h in creds if h not in blocked) if scope else ()

    last_end = schedule.last_shift_ended_at if schedule else None
    nxt = schedule.next_shift_starts_at if schedule else None
    hours = schedule.hours_worked_trailing_7d if schedule else None
    earliest = ctx.as_of
    if last_end is not None:
        earliest = max(earliest, _ceil_minute(last_end + timedelta(hours=st.rest_hours)))
    in_window = earliest + timedelta(minutes=online_minutes) < ctx.plan_end
    eval_start = earliest if in_window else ctx.as_of
    max_by_hours = (
        math.floor((st.weekly_hour_limit - hours) * 60 + 1e-9) if hours is not None else None
    )
    until_next = int((nxt - eval_start).total_seconds() // 60) if nxt is not None else None
    limits = [v for v in (max_by_hours, until_next) if v is not None]
    max_minutes = (
        max(0, min(*limits, max(st.duration_options_minutes))) if len(limits) == 2 else None
    )

    checks = offer_checks(
        p,
        profile,
        eval_start,
        st.min_offer_minutes,
        scope or tuple(creds),
        ctx,
        online_minutes,
        online_assumed,
    )
    # min_length is judged on the longest offer the other limits allow (weekly hours, next
    # shift, longest offer option): time to come online disqualifies only when that offer is
    # at least 2 h but worth less than 2 h. If a limit is already below 2 h, that limit's rule
    # fails (checked above at a 2 h offer) and min_length is judged on its own: the offer
    # that gives exactly 2 h of coverage.
    caps = {
        "weekly hours": max_by_hours,
        "next scheduled shift": until_next,
        "longest offer option": max(st.duration_options_minutes),
    }
    known = {k: v for k, v in caps.items() if v is not None}
    best_label = min(known, key=lambda k: (known[k], k))
    best = max(0, known[best_label])
    for i, c in enumerate(checks):
        if c.code == "min_length":
            if best >= st.min_offer_minutes:
                judged = min_length_check(
                    best, online_minutes, online_assumed, st.min_offer_minutes, best_label
                )
            else:
                judged = min_length_check(
                    st.min_offer_minutes + online_minutes,
                    online_minutes,
                    online_assumed,
                    st.min_offer_minutes,
                )
            _, label, passed, value, threshold, message = judged
            checks[i] = c.model_copy(
                update={
                    "passed": passed,
                    "value": value,
                    "threshold": threshold,
                    "message": message,
                    "label": label,
                }
            )
    if not in_window and earliest <= ctx.as_of:
        # Rested already: it is the time to come online that leaves nothing in the window.
        for i, c in enumerate(checks):
            if c.code == "min_length" and c.passed:
                checks[i] = c.model_copy(
                    update={
                        "passed": False,
                        "message": f"needs {online_minutes} min to come online, so no coverage "
                        f"would fall inside the {ctx.horizon_minutes}-min planning window",
                    }
                )
    elif not in_window and last_end is not None:
        for i, c in enumerate(checks):
            if c.code == "rest_10h" and c.passed:
                checks[i] = c.model_copy(
                    update={
                        "passed": False,
                        "message": "10 h of rest only at "
                        f"{fmt_local_datetime(earliest, ctx.tz_for(scope or creds))}, "
                        "too late to come online inside the planning window",
                    }
                )
    failed = [c.code for c in checks if not c.passed]
    missing = [c.code for c in checks if c.missing_data]
    if online_assumed:
        missing.append("minutes_to_come_online (assumed)")
    eligible = not failed
    name = p.display_name
    if eligible:
        summary = (
            f"{name} is eligible: can start {fmt_local(eval_start, ctx.tz_for(scope))}, online "
            f"{online_minutes} min later, up to {max_minutes} min, at "
            f"{', '.join(scope)}."
        )
    else:
        first = next(c for c in checks if not c.passed)
        summary = (
            f"{name} is not eligible: {first.message}"
            + (f" (+{len(failed) - 1} more)" if len(failed) > 1 else "")
            + "."
        )
    return Candidate(
        state=p,
        profile=profile,
        eligibility=CandidateEligibility(
            physician_id=p.physician_id,
            display_name=name,
            roster_role=p.roster_role,
            eligible=eligible,
            failed_rules=failed,
            checks=checks,
            gap_hospital_ids=list(scope) if scope else [],
            earliest_valid_start=eval_start if (in_window or last_end is None) else earliest,
            latest_valid_end=nxt,
            max_offer_minutes=max_minutes,
            remaining_weekly_hours=(
                round(st.weekly_hour_limit - hours, 2) if hours is not None else None
            ),
            minutes_to_come_online=online_minutes,
            online_time_assumed=online_assumed,
            missing_data=missing,
            summary=summary,
        ),
        scope=scope,
        earliest_start=eval_start if eligible else None,
        latest_end=nxt,
        max_minutes=max_minutes,
        online_minutes=online_minutes,
    )


def evaluate_candidates(ctx: PlanningContext) -> list[Candidate]:
    profiles = {x.id: x for x in ctx.analysis.reference.physicians}
    return [
        evaluate_candidate(p, profiles.get(p.physician_id), ctx)
        for p in sorted(ctx.analysis.state.physicians, key=lambda x: natural_key(x.physician_id))
        if p.roster == "off_shift"
    ]


@dataclass(frozen=True)
class Option:
    index: int
    physician_id: str
    name: str
    start: datetime
    minutes: int
    online_at: datetime
    end: datetime
    hospitals: tuple[str, ...]

    @property
    def effective_end(self) -> datetime:
        return self.end


def generate_options(candidates: list[Candidate], ctx: PlanningContext) -> list[Option]:
    """Finite start/length choices per eligible candidate. Every option is re-checked
    against every rule, so the optimizer can only pick offers that pass all of them."""
    st = ctx.cfg.staffing
    options: list[Option] = []
    for cand in candidates:
        if not cand.eligibility.eligible or cand.earliest_start is None:
            continue
        online = timedelta(minutes=cand.online_minutes)
        lead = online + timedelta(minutes=st.login_buffer_minutes)
        starts = {cand.earliest_start}
        gap_ends: set[datetime] = set()
        for hid in cand.scope:
            profile = ctx.models[hid].deficit_profile()
            previous = 0
            for k, (a, b, deficit) in enumerate(profile):
                deepens, previous = deficit > previous, deficit
                if deficit <= 0:
                    continue
                if k + 1 == len(profile) or profile[k + 1][2] <= 0:
                    gap_ends.add(b)  # the deficit stops here (or the window ends)
                if not deepens:
                    continue
                # Just in time: online a few minutes before this deficit begins (or deepens).
                s = max(a - lead, cand.earliest_start)
                if s > cand.earliest_start and s + online < ctx.plan_end:
                    starts.add(s)
        shortest = st.min_offer_minutes + cand.online_minutes
        for start in sorted(starts)[: max(1, st.max_start_options)]:
            lengths = set(st.duration_options_minutes)
            if st.fit_lengths_to_gap:
                lengths.add(shortest)
                for end in gap_ends:
                    fit = math.ceil((end - start).total_seconds() / 60)
                    if fit > shortest:
                        lengths.add(fit)  # end exactly when this gap ends
            if cand.latest_end is not None:
                until_next = int((cand.latest_end - start).total_seconds() // 60)
                if until_next <= max(st.duration_options_minutes):
                    lengths.add(until_next)  # fill exactly up to the scheduled shift
            remaining = cand.eligibility.remaining_weekly_hours
            if remaining is not None:
                by_hours = math.floor(remaining * 60 + 1e-9)
                if by_hours < max(st.duration_options_minutes):
                    lengths.add(by_hours)  # use exactly the hours left this week
            for minutes in sorted(lengths):
                if minutes < st.min_offer_minutes:
                    continue
                checks = offer_checks(
                    cand.state,
                    cand.profile,
                    start,
                    minutes,
                    cand.scope,
                    ctx,
                    cand.online_minutes,
                    cand.eligibility.online_time_assumed,
                )
                if not all(c.passed for c in checks):
                    continue
                options.append(
                    Option(
                        index=len(options),
                        physician_id=cand.physician_id,
                        name=cand.state.display_name,
                        start=start,
                        minutes=minutes,
                        online_at=start + online,
                        end=start + timedelta(minutes=minutes),
                        hospitals=cand.scope,
                    )
                )
    if ctx.cfg.voluntary.enabled and ctx.cfg.voluntary.fit_offers_to_window:
        options.extend(window_options(candidates, ctx, options))
    return options


def window_options(
    candidates: list[Candidate], ctx: PlanningContext, existing: list[Option]
) -> list[Option]:
    """Offers that start and end inside a physician's volunteered window, so a volunteer can
    be asked for exactly the time they offered. Only eligible candidates get them, and every
    option is re-checked against every rule like any other."""
    st = ctx.cfg.staffing
    seen = {(o.physician_id, o.start, o.minutes) for o in existing}
    longest = max(st.duration_options_minutes)
    added: list[Option] = []
    for cand in candidates:
        windows = ctx.availability.get(cand.physician_id)
        if not windows or not cand.eligibility.eligible or cand.earliest_start is None:
            continue
        online = timedelta(minutes=cand.online_minutes)
        lead = online + timedelta(minutes=st.login_buffer_minutes)
        shortest = st.min_offer_minutes + cand.online_minutes
        for w in sorted(windows, key=lambda w: w.start):
            first = max(w.start, cand.earliest_start)
            if first >= w.end or first + online >= ctx.plan_end:
                continue
            starts = {_ceil_minute(first)}
            for hid in cand.scope:
                for a, _, deficit in ctx.models[hid].deficit_profile():
                    s = _ceil_minute(a - lead)
                    if deficit > 0 and first < s < w.end and s + online < ctx.plan_end:
                        starts.add(s)
            for start in sorted(starts)[: max(1, st.max_start_options)]:
                room = int((w.end - start).total_seconds() // 60)
                lengths = {m for m in st.duration_options_minutes if m <= room}
                lengths |= {min(room, longest), shortest}
                for minutes in sorted(lengths):
                    if minutes < st.min_offer_minutes or minutes > room:
                        continue
                    key = (cand.physician_id, start, minutes)
                    if key in seen:
                        continue
                    checks = offer_checks(
                        cand.state,
                        cand.profile,
                        start,
                        minutes,
                        cand.scope,
                        ctx,
                        cand.online_minutes,
                        cand.eligibility.online_time_assumed,
                    )
                    if not all(c.passed for c in checks):
                        continue
                    seen.add(key)
                    added.append(
                        Option(
                            index=len(existing) + len(added),
                            physician_id=cand.physician_id,
                            name=cand.state.display_name,
                            start=start,
                            minutes=minutes,
                            online_at=start + online,
                            end=start + timedelta(minutes=minutes),
                            hospitals=cand.scope,
                        )
                    )
    return added


PROPOSED_REASON = "proposed split shift — projected if accepted, not confirmed"


def proposed_window(option: Option) -> Window:
    return hypothetical_window(
        option.physician_id, option.name, option.online_at, option.end, PROPOSED_REASON
    )
