"""Rescue Scarcity Index and Last Safe Moment (pure).

Both read the Phase 4 staffing planner's internals: the planning-window coverage models
(which already include accepted/activated rescue shifts) and every off-shift candidate
evaluated against every split-shift rule. Nothing here relaxes a rule: a candidate who
fails any hard rule is shown with the reasons and never counted as a backup.

Last Safe Moment
  lead (conservative) = approval + full offer life (10 min) + time to come online
  lead (expected)     = approval + expected response + time to come online
  latest initiation   = shortfall start - conservative lead
The offer must also respect the candidate's earliest valid start (rest, overlap ...):
if that start plus the time to come online is after the shortfall start, the candidate
cannot prevent the shortfall, only mitigate it. Eligibility is evaluated at the offered
start (the brief: rest "measured at the offered start time"); send-time rules (open offers,
weekly limit) are evaluated now.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

from app.engines.coverage_prediction import hypothetical_window
from app.engines.intelligence.common import profile
from app.engines.intelligence.config import IntelligenceConfig
from app.engines.optimization.split_shift.candidates import Candidate, PlanningContext
from app.engines.timeline import fmt_local
from app.schemas.intelligence import (
    LastSafeMoment,
    LastSafeMomentReport,
    LeadTime,
    RescueTiming,
    ScarcityEntry,
    ScarcityHospital,
    ScarcityReport,
)

SEND_TIME_RULES = {"notification_limits"}
URGENCY_WEIGHT = {"now": 3.0, "within_90": 2.0, "planning_window": 1.0}

SCARCITY_POLICY = [
    "Scarcity only orders otherwise safe, effective options. It never overrides a hard "
    "eligibility rule or delays escalation of an active critical stroke problem.",
    "A candidate who is the only eligible backup for a hospital is 'sole'. Spending them on "
    "a hospital that has alternatives leaves the sole hospital without a rescue path.",
    "score = Σ over gap hospitals they can help: urgency weight (now 3, ≤ 90 min 2, later 1) "
    "× (3 if sole candidate else 1 / (1 + alternatives)).",
]


def _urgency(first: datetime | None, as_of: datetime) -> str:
    if first is None:
        return "planning_window"
    if first <= as_of:
        return "now"
    return "within_90" if first <= as_of + timedelta(minutes=90) else "planning_window"


def _best_window(c: Candidate, ctx: PlanningContext):
    if c.earliest_start is None or not c.max_minutes:
        return None
    start = c.earliest_start
    end = start + timedelta(minutes=c.max_minutes)
    online = start + timedelta(minutes=c.online_minutes)
    if online >= end:
        return None
    return hypothetical_window(
        c.physician_id, c.state.display_name, online, end, "scarcity: best valid offer"
    )


def scarcity_report(ctx: PlanningContext, candidates: Sequence[Candidate]) -> ScarcityReport:
    as_of = ctx.as_of
    gaps = list(ctx.gap_hospitals)
    profiles_ = {hid: profile(ctx.models[hid]) for hid in gaps}
    eligible = [c for c in candidates if c.eligibility.eligible]
    by_hospital: dict[str, list[str]] = {
        hid: sorted(c.physician_id for c in eligible if hid in c.eligibility.gap_hospital_ids)
        for hid in gaps
    }
    entries: list[ScarcityEntry] = []
    for c in sorted(candidates, key=lambda x: x.physician_id):
        e = c.eligibility
        hospitals: list[ScarcityHospital] = []
        window = _best_window(c, ctx) if e.eligible else None
        for hid in sorted(e.gap_hospital_ids):
            if hid not in ctx.models:
                continue
            pr = profiles_.get(hid) or profile(ctx.models[hid])
            others = [x for x in by_hospital.get(hid, []) if x != c.physician_id]
            reduction = 0.0
            if window is not None:
                after = ctx.models[hid].deficit_physician_minutes([window])
                reduction = round(pr.deficit_pm - after, 4)
            hospitals.append(
                ScarcityHospital(
                    hospital_id=hid,
                    hospital_name=ctx.hospital_name(hid),
                    first_shortfall_at=pr.first_shortfall,
                    deficit_physician_minutes=pr.deficit_pm,
                    urgency=_urgency(pr.first_shortfall, as_of),  # type: ignore[arg-type]
                    alternative_candidate_ids=others,
                    sole_candidate=e.eligible and not others,
                    reduction_if_assigned=reduction,
                )
            )
        dependent = [h for h in hospitals if e.eligible]
        sole = [h for h in dependent if h.sole_candidate]
        score = round(
            sum(
                URGENCY_WEIGHT[h.urgency]
                * (3.0 if h.sole_candidate else 1 / (1 + len(h.alternative_candidate_ids)))
                for h in dependent
            ),
            4,
        )
        if not e.eligible:
            rec = "not_eligible"
            cost = "No opportunity cost: this physician cannot receive an offer."
            text = f"{c.state.display_name} fails: {', '.join(e.failed_rules)}. {e.summary}"
        elif sole and any(not h.sole_candidate for h in dependent):
            rec = "preserve"
            names = ", ".join(h.hospital_name for h in sole)
            cost = (
                f"Only eligible backup for {names}. Committing them to a hospital that has "
                "alternatives would leave that hospital with no rescue path."
            )
            text = f"Preserve {c.state.display_name} for {names}; use alternatives elsewhere."
        elif sole:
            rec = "allocate"
            names = ", ".join(h.hospital_name for h in sole)
            cost = f"Only eligible backup for {names}; no alternative exists."
            text = f"Allocate {c.state.display_name} to {names} (sole eligible backup)."
        elif dependent:
            rec = "allocate_if_needed"
            cost = "Alternatives exist for every hospital this physician could cover."
            text = f"{c.state.display_name} is one of several eligible backups."
        else:
            rec = "allocate_if_needed"
            cost = "Eligible, but no current gap hospital needs them."
            text = f"{c.state.display_name} is eligible but not needed for any gap now."
        entries.append(
            ScarcityEntry(
                physician_id=c.physician_id,
                display_name=c.state.display_name,
                eligible=e.eligible,
                failed_rules=e.failed_rules,
                hospitals=hospitals,
                dependent_hospital_count=len(dependent),
                sole_candidate_hospital_count=len(sole),
                minutes_to_come_online=e.minutes_to_come_online,
                earliest_valid_start=e.earliest_valid_start,
                max_offer_minutes=e.max_offer_minutes,
                scarcity_score=score,
                recommendation=rec,  # type: ignore[arg-type]
                opportunity_cost=cost,
                explanation=text,
            )
        )
    entries.sort(key=lambda x: (-x.scarcity_score, x.physician_id))
    uncovered = sorted(h for h in gaps if not by_hospital.get(h))
    return ScarcityReport(
        as_of=as_of,
        data_version=ctx.analysis.state.data_version,
        planning_horizon_minutes=ctx.horizon_minutes,
        gap_hospital_ids=gaps,
        entries=entries,
        uncovered_hospital_ids=uncovered,
        no_feasible_candidate=bool(gaps) and not eligible,
        escalation_recommended=bool(uncovered),
        policy=SCARCITY_POLICY,
    )


def _phase(remaining: float | None, cfg: IntelligenceConfig) -> str:
    if remaining is None:
        return "no_candidate"
    if remaining < 0:
        return "missed"
    if remaining <= cfg.lead.red_minutes:
        return "red"
    if remaining <= cfg.lead.green_minutes:
        return "amber"
    return "green"


def last_safe_moment_report(
    ctx: PlanningContext,
    candidates: Sequence[Candidate],
    cfg: IntelligenceConfig,
    *,
    rescues_in_progress: Mapping[str, list[str]] | None = None,
) -> LastSafeMomentReport:
    as_of = ctx.as_of
    lead_cfg = cfg.lead
    items: list[LastSafeMoment] = []
    rescues_in_progress = rescues_in_progress or {}
    for hid in sorted(ctx.models):
        model = ctx.models[hid]
        pr = profile(model)
        if pr.first_shortfall is None:
            continue
        tz = model.tz
        shortfall = pr.first_shortfall
        timings: list[RescueTiming] = []
        for c in sorted(candidates, key=lambda x: x.physician_id):
            if hid not in c.state.credentialed_hospital_ids:
                continue
            e = c.eligibility
            online = c.online_minutes
            lead = LeadTime(
                approval_minutes=lead_cfg.approval_minutes,
                response_minutes_expected=lead_cfg.response_minutes_expected,
                response_minutes_conservative=lead_cfg.response_minutes_conservative,
                online_minutes=online,
                expected_total_minutes=lead_cfg.approval_minutes
                + lead_cfg.response_minutes_expected
                + online,
                conservative_total_minutes=lead_cfg.approval_minutes
                + lead_cfg.response_minutes_conservative
                + online,
                online_time_assumed=e.online_time_assumed,
            )
            failed_at_start = [
                ch for ch in e.checks if not ch.passed and ch.code not in SEND_TIME_RULES
            ]
            send_failed = [ch for ch in e.checks if not ch.passed and ch.code in SEND_TIME_RULES]
            blocking = [f"{ch.label}: {ch.message}" for ch in [*failed_at_start, *send_failed]]
            eligible_at_start = not failed_at_start and c.earliest_start is not None
            if hid not in e.gap_hospital_ids:
                blocking.append(f"{ctx.hospital_name(hid)} is not one of their gap hospitals")
                eligible_at_start = False
            earliest = c.earliest_start
            activation = latest_exp = latest_cons = None
            covers = False
            crossing = None
            if eligible_at_start and earliest is not None:
                accept_expected = as_of + timedelta(
                    minutes=lead_cfg.approval_minutes + lead_cfg.response_minutes_expected
                )
                start_expected = max(earliest, accept_expected)
                activation = start_expected + timedelta(minutes=online)
                latest_cons = shortfall - timedelta(minutes=lead.conservative_total_minutes)
                latest_exp = shortfall - timedelta(minutes=lead.expected_total_minutes)
                covers = earliest + timedelta(minutes=online) <= shortfall
                if not covers:
                    latest_cons = latest_exp = None
                    blocking.append(
                        f"earliest valid start {fmt_local(earliest, tz)} + {online} min online "
                        f"is after the shortfall at {fmt_local(shortfall, tz)}: can mitigate, "
                        "not prevent"
                    )
                if earliest > as_of + timedelta(minutes=lead_cfg.approval_minutes):
                    crossing = (
                        f"Not offerable to start before {fmt_local(earliest, tz)} (rest / "
                        "schedule rules measured at the offered start); eligible from then."
                    )
            timings.append(
                RescueTiming(
                    physician_id=c.physician_id,
                    display_name=c.state.display_name,
                    lead=lead,
                    earliest_valid_start=earliest,
                    activation_expected_at=activation,
                    latest_initiation_expected=latest_exp,
                    latest_initiation_conservative=latest_cons,
                    covers_shortfall_start=covers,
                    eligible_at_start=eligible_at_start,
                    sendable_now=not send_failed,
                    eligibility_crossing=crossing,
                    blocking=blocking,
                )
            )
        usable = [
            t
            for t in timings
            if t.covers_shortfall_start and t.sendable_now and t.latest_initiation_conservative
        ]
        best = max(
            usable,
            key=lambda t: (t.latest_initiation_conservative, t.physician_id),
            default=None,
        )
        latest = best.latest_initiation_conservative if best else None
        remaining = (latest - as_of).total_seconds() / 60 if latest else None
        phase = _phase(remaining, cfg)
        if best is None and any(t.eligible_at_start for t in timings):
            phase = "missed"
        mitigation: list[str] = []
        in_progress = rescues_in_progress.get(hid, [])
        if in_progress:
            mitigation.append(
                f"Rescue already in progress for this hospital: {', '.join(in_progress)}."
            )
        if phase in ("missed", "no_candidate"):
            partial = [t for t in timings if t.eligible_at_start and t.activation_expected_at]
            if partial:
                p = min(partial, key=lambda t: (t.activation_expected_at, t.physician_id))
                mitigation.append(
                    f"Proactive window missed. Best mitigation: offer {p.display_name} now — "
                    f"expected online {fmt_local(p.activation_expected_at, tz)}, shortening the "
                    "gap rather than preventing it."
                )
            mitigation.append(
                "Escalate to the clinical lead now; consider reassigning waiting consults to "
                "credentialed physicians at other hospitals' capacity."
            )
        elif phase == "red":
            mitigation.append("Start the rescue now: the opportunity window is about to close.")
        uncertainty = [
            f"Lead time assumes {lead_cfg.approval_minutes} min approval and up to "
            f"{lead_cfg.response_minutes_conservative} min for a reply (the offer's full life).",
            "Time to come online comes from the roster; acceptance is not assumed.",
            "The shortfall time is a forecast from schedules and known arrivals, not an "
            "observation.",
        ]
        if any(t.lead.online_time_assumed for t in timings):
            uncertainty.append("At least one candidate's time to come online is assumed (missing).")
        if latest:
            text = (
                f"{ctx.hospital_name(hid)} is projected short from {fmt_local(shortfall, tz)}. "
                f"Latest recommended start of the rescue workflow: {fmt_local(latest, tz)} "
                f"({remaining:.0f} min from now) using {best.display_name} "
                f"(lead {best.lead.conservative_total_minutes} min conservative)."
            )
        elif phase == "missed":
            text = (
                f"{ctx.hospital_name(hid)} is projected short from {fmt_local(shortfall, tz)}; "
                "no eligible candidate can be online in time. Prevention is no longer possible; "
                "mitigate and escalate."
            )
        else:
            text = (
                f"{ctx.hospital_name(hid)} is projected short from {fmt_local(shortfall, tz)}; "
                "no off-shift physician is eligible to cover it. Escalate."
            )
        items.append(
            LastSafeMoment(
                shortfall_id=f"LSM:{hid}:{shortfall.isoformat()}",
                hospital_id=hid,
                hospital_name=ctx.hospital_name(hid),
                timezone=tz,
                shortfall_at=shortfall,
                shortfall_ends_at=pr.first_shortfall_end,
                minutes_until_shortfall=round((shortfall - as_of).total_seconds() / 60, 2),
                deficit_physician_minutes=pr.deficit_pm,
                worst_deficit=pr.worst_deficit,
                phase=phase,  # type: ignore[arg-type]
                latest_initiation_at=latest,
                remaining_minutes=round(remaining, 2) if remaining is not None else None,
                best_physician_id=best.physician_id if best else None,
                candidates=timings,
                mitigation=mitigation,
                uncertainty=uncertainty,
                explanation=text,
            )
        )
    items.sort(
        key=lambda i: (
            i.latest_initiation_at or i.shortfall_at,
            i.hospital_id,
        )
    )
    deadlines = [i.latest_initiation_at for i in items if i.latest_initiation_at]
    return LastSafeMomentReport(
        as_of=as_of,
        data_version=ctx.analysis.state.data_version,
        planning_horizon_minutes=ctx.horizon_minutes,
        items=items,
        earliest_deadline_at=min(deadlines) if deadlines else None,
        assumptions=[
            f"Approval takes {lead_cfg.approval_minutes} min (assumption).",
            f"Expected reply {lead_cfg.response_minutes_expected} min (assumption); conservative "
            f"reply = full offer life {lead_cfg.response_minutes_conservative} min (brief).",
            "Approval, reply and coming online are sequential and do not overlap.",
            f"Phases: green > {lead_cfg.green_minutes} min remaining, red ≤ "
            f"{lead_cfg.red_minutes} min, amber in between, missed < 0.",
            "Countdowns run on the simulation clock and stop when the scenario is paused.",
        ],
    )
