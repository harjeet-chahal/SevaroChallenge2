"""90-minute coverage forecast: exact piecewise-constant simulation over time boundaries.

For each hospital:

  R(t) = base requirement for the local time block containing t
         + demand-spike adjustment at t (known arrivals only)
  A(t) = number of distinct physicians credentialed at the hospital whose contribution
         window contains t
  deficit(t) = max(0, R(t) - A(t))

Every instant at which R or A can change is collected (shift starts/ends, requirement
block boundaries in local time, local hour boundaries, arrivals leaving the spike
window, UTC-offset transitions). Between consecutive change points both are constant,
so the deficit integral is an exact sum of rectangle areas. Chart samples at regular
intervals are added only for display.

No future event is used: availability comes from state at the simulation time,
schedules come from rosters, and spikes only count arrivals already visible.

Coverage is counted per hospital and non-exclusively, as the brief defines it ("a minimum
number of available, credentialed physicians" per hospital): a physician credentialed
at several hospitals counts toward each. Exclusive allocation is a Phase 4 optimizer
modelling choice, not part of this metric.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from app.engines.demand import HospitalDemandModel
from app.engines.event_processing import normalize_label
from app.engines.rules import CoverageRule
from app.engines.timeline import (
    fmt_local,
    fmt_local_datetime,
    is_weekend,
    local,
    local_time_crossings,
    time_in_block,
    zone_transitions,
)
from app.schemas.coverage import (
    Certainty,
    CoverageAnnotation,
    CoverageContributor,
    CoveragePoint,
    CoverageRequirement,
    CoverageRiskMetrics,
    CoverageSegment,
    HospitalCoverage,
)
from app.schemas.hospital import Hospital
from app.schemas.physician import Availability, PhysicianState

UNCERTAIN_FLAGS = {
    "availability_unverified": "desktop agent offline — availability unverified",
    "agent_online_inferred": "agent online only inferred from a later desktop-agent event",
    "shift_assumed_from_roster": (
        "on shift only by roster next-shift start (no shift_started event)"
    ),
    "not_in_roster": "not in any roster file",
}


@dataclass(frozen=True)
class Window:
    """When one physician counts toward one hospital: [start, end)."""

    physician_id: str
    name: str
    start: datetime
    end: datetime | None
    """None = shift end unknown. Counted through the horizon, never given a made-up end."""
    certainty: Certainty
    reasons: tuple[str, ...]
    on_now: bool
    proposed: bool = False
    """True for a what-if window (e.g. a proposed split shift): projected, never confirmed."""
    pending: bool = False
    """True for an accepted split shift that is not active yet (Phase 5): uncertain."""

    def covers(self, moment: datetime) -> bool:
        return self.start <= moment and (self.end is None or moment < self.end)


def physician_window(
    p: PhysicianState,
    as_of: datetime,
    horizon_end: datetime,
    rule: CoverageRule,
    tz: str = "UTC",
) -> tuple[Window | None, list[str]]:
    """Contribution window for a physician (credentialing is checked by the caller).

    Shift resolution mirrors Phase 2 (engines/physician_state): roster schedule (an earlier
    shift_started extends it), else a shift_started event with no known end, else the
    off-shift roster's next start with no known end. An accepted split shift that is not
    active yet (Phase 5 overlay) gives an uncertain *pending activation* window that never
    covers the current moment.
    """
    temp = p.temporary_shift
    if temp is not None and temp.phase == "preparing":
        online = temp.expected_online_at
        if online <= as_of:
            return None, [
                f"accepted split shift — activation overdue (expected online "
                f"{fmt_local(online, tz)}); not counted until activated"
            ]
        if online >= horizon_end or temp.end_at <= as_of:
            return None, [
                f"accepted split shift — expected online {fmt_local(online, tz)}, after the "
                "forecast horizon"
            ]
        return (
            Window(
                physician_id=p.physician_id,
                name=p.display_name,
                start=online,
                end=temp.end_at,
                certainty="uncertain",
                reasons=(
                    "accepted split shift — not active yet; expected online "
                    f"{fmt_local(online, tz)} (pending activation, not confirmed capacity)",
                ),
                on_now=False,
                pending=True,
            ),
            [],
        )
    if temp is not None and temp.phase == "active" and p.scheduled_shift is not None:
        start, end = p.scheduled_shift.start, p.scheduled_shift.end
        source = (
            f"split shift activated through the approved workflow ({temp.intervention_id}); "
            f"ends {fmt_local(end, tz)}"
        )
    elif p.scheduled_shift is not None:
        start, end = p.scheduled_shift.start, p.scheduled_shift.end
        if p.shift_started_at is not None and p.shift_started_at < end:
            start = min(start, p.shift_started_at)
        source = "on the shift roster (scheduled start and end)"
    elif p.shift_started_at is not None:
        start, end = p.shift_started_at, None
        source = "shift_started event; no scheduled end"
    elif p.next_shift_starts_at is not None:
        start, end = p.next_shift_starts_at, None
        source = "roster next shift start; end not in data"
    else:
        return None, ["no shift on record"]

    if end is not None and end <= as_of:
        return None, [f"shift ended at {fmt_local_datetime(end, tz)}"]
    if start >= horizon_end:
        return None, [
            f"next shift starts {fmt_local_datetime(start, tz)}, after the forecast horizon"
        ]

    on_now = start <= as_of
    reasons = [source]
    uncertain: list[str] = []
    if end is None:
        uncertain.append("shift end unknown — counted through the horizon, not assumed")
    if on_now:
        if p.availability is Availability.UNAVAILABLE and rule.unavailable_persists:
            return None, [
                "self-reported Temporarily Unavailable; assumed to persist (no return time known)"
            ]
        if p.availability is Availability.BUSY:
            if not rule.busy_counts_as_available:
                return None, [f"busy now ({p.activity.value}); busy not counted (configuration)"]
            reasons.append(f"busy now ({p.activity.value}) — on duty, still counted")
        for flag in p.flags:
            if flag.code in UNCERTAIN_FLAGS:
                uncertain.append(UNCERTAIN_FLAGS[flag.code])
    else:
        reasons.append(f"joins at {fmt_local(start, tz)}")
    return (
        Window(
            physician_id=p.physician_id,
            name=p.display_name,
            start=max(start, as_of),
            end=end,
            certainty="uncertain" if uncertain else "confirmed",
            reasons=tuple(reasons + uncertain),
            on_now=on_now,
        ),
        [],
    )


def _rows_for_day(
    rows: Sequence[CoverageRequirement], moment_local: datetime
) -> list[CoverageRequirement]:
    types = {normalize_label(r.day_type) if r.day_type else None for r in rows}
    if len(types) <= 1:
        return list(rows)
    wanted = {"weekend", "weekends"} if is_weekend(moment_local) else {"weekday", "weekdays"}
    chosen = [r for r in rows if r.day_type and normalize_label(r.day_type) in wanted]
    return chosen or [r for r in rows if not r.day_type]


@dataclass
class _Eval:
    required_base: int | None
    block: CoverageRequirement | None
    spike_adjustment: int | None
    required: int | None
    active: list[Window]

    @property
    def confirmed(self) -> list[Window]:
        return [w for w in self.active if w.certainty == "confirmed"]

    @property
    def deficit(self) -> int | None:
        return None if self.required is None else max(0, self.required - len(self.active))

    @property
    def deficit_confirmed(self) -> int | None:
        return None if self.required is None else max(0, self.required - len(self.confirmed))


@dataclass
class HospitalCoverageModel:
    hospital: Hospital
    as_of: datetime
    horizon_end: datetime
    windows: list[Window]
    requirements: list[CoverageRequirement]
    demand: HospitalDemandModel | None
    contributors: list[CoverageContributor] = field(default_factory=list)

    @property
    def tz(self) -> str:
        return self.hospital.timezone

    def requirement_at(self, moment: datetime) -> tuple[int | None, CoverageRequirement | None]:
        moment_local = local(moment, self.tz)
        tod = moment_local.time().replace(tzinfo=None)
        rows = _rows_for_day(self.requirements, moment_local)
        matches = [r for r in rows if time_in_block(tod, r.block_start_local, r.block_end_local)]
        if not matches:
            return None, None
        best = max(matches, key=lambda r: (r.min_available_physicians, r.block_start_local))
        return best.min_available_physicians, best

    def _evaluate(self, moment: datetime, windows: Sequence[Window]) -> _Eval:
        base, block = self.requirement_at(moment)
        adjustment: int | None = 0
        if self.demand is not None:
            adjustment = self.demand.evaluate(moment).requirement_adjustment
        required = None if base is None else base + (adjustment or 0)
        # One physician counts at most once per hospital, even if several windows overlap
        # (e.g. a hypothetical what-if window on top of a scheduled one). Confirmed wins.
        by_physician: dict[str, Window] = {}
        for w in windows:
            if not w.covers(moment):
                continue
            kept = by_physician.get(w.physician_id)
            if kept is None or (kept.certainty == "uncertain" and w.certainty == "confirmed"):
                by_physician[w.physician_id] = w
        active = [by_physician[k] for k in sorted(by_physician)]
        return _Eval(base, block, adjustment, required, active)

    def change_points(self, windows: Sequence[Window]) -> list[datetime]:
        start, end = self.as_of, self.horizon_end
        points = {start, end}
        for w in windows:
            for moment in (w.start, w.end):
                if moment is not None and start < moment < end:
                    points.add(moment)
        times: set[time] = set()
        for r in self.requirements:
            times.update((r.block_start_local, r.block_end_local))
        if len({r.day_type for r in self.requirements}) > 1:
            times.add(time(0))
        points.update(local_time_crossings(self.tz, start, end, times))
        points.update(t for t in zone_transitions(self.tz, start, end) if t < end)
        if self.demand is not None:
            points.update(self.demand.change_points(start, end))
        return sorted(points)

    def evaluations(self, extra: Iterable[Window] = ()) -> list[tuple[datetime, datetime, _Eval]]:
        windows = [*self.windows, *extra]
        cuts = self.change_points(windows)
        return [(a, b, self._evaluate(a, windows)) for a, b in zip(cuts, cuts[1:], strict=False)]

    def deficit_profile(
        self, cuts: Iterable[datetime] = ()
    ) -> list[tuple[datetime, datetime, int]]:
        """(start, end, deficit) for the scheduled windows only, also split at ``cuts``.

        Used by the staffing optimizer: R and A are constant on each piece, so adding a
        proposed window that starts/ends on a cut changes A by a whole piece at a time.
        """
        points = set(self.change_points(self.windows))
        points.update(t for t in cuts if self.as_of < t < self.horizon_end)
        ordered = sorted(points)
        return [
            (a, b, self._evaluate(a, self.windows).deficit or 0)
            for a, b in zip(ordered, ordered[1:], strict=False)
        ]

    def deficit_physician_minutes(self, extra: Iterable[Window] = ()) -> float:
        return sum(
            (e.deficit or 0) * (b - a).total_seconds() / 60 for a, b, e in self.evaluations(extra)
        )


def _segments(evals: list[tuple[datetime, datetime, _Eval]]) -> list[CoverageSegment]:
    segments: list[CoverageSegment] = []
    for a, b, e in evals:
        segment = CoverageSegment(
            start=a,
            end=b,
            required_base=e.required_base,
            spike_adjustment=e.spike_adjustment,
            required=e.required,
            available_confirmed=len(e.confirmed),
            available_uncertain=len(e.active) - len(e.confirmed),
            available=len(e.active),
            deficit=e.deficit,
            deficit_if_uncertain_excluded=e.deficit_confirmed,
            counted_physician_ids=[w.physician_id for w in e.active],
            uncertain_physician_ids=[
                w.physician_id for w in e.active if w.certainty == "uncertain"
            ],
        )
        previous = segments[-1] if segments else None
        if previous and previous.model_dump(exclude={"start", "end"}) == segment.model_dump(
            exclude={"start", "end"}
        ):
            segments[-1] = previous.model_copy(update={"end": b})
        else:
            segments.append(segment)
    return segments


def _join_names(names: list[str]) -> str:
    names = sorted(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def _segment_at(segments: Sequence[CoverageSegment], moment: datetime) -> CoverageSegment:
    for s in segments:
        if s.start <= moment < s.end:
            return s
    return segments[-1]


def build_hospital_coverage(
    model: HospitalCoverageModel, *, step_minutes: int, horizon_minutes: int
) -> HospitalCoverage:
    evals = model.evaluations()
    segments = _segments(evals)
    tz = model.tz
    hospital = model.hospital
    as_of, horizon_end = model.as_of, model.horizon_end

    # --- metrics -----------------------------------------------------------------
    now = segments[0]
    deficit_pm = sum((s.deficit or 0) * (s.end - s.start).total_seconds() / 60 for s in segments)
    deficit_pm_conf = sum(
        (s.deficit_if_uncertain_excluded or 0) * (s.end - s.start).total_seconds() / 60
        for s in segments
    )
    short = [s for s in segments if (s.deficit or 0) > 0]
    first_short = short[0].start if short else None
    requirement_defined = any(s.required is not None for s in segments)
    uncertainty = sorted(
        {
            f"{w.name}: {r}"
            for w in model.windows
            if w.certainty == "uncertain"
            for r in w.reasons
            if r in UNCERTAIN_FLAGS.values() or r.startswith("shift end unknown")
        }
    )
    if any(s.spike_adjustment is None for s in segments):
        uncertainty.append("demand-spike adjustment could not be evaluated (no usable baseline)")
    if not requirement_defined:
        confidence = "unknown"
    elif uncertainty or any(s.available_uncertain for s in segments):
        confidence = "uncertain"
    else:
        confidence = "confirmed"
    metrics = CoverageRiskMetrics(
        required_now=now.required,
        available_now=now.available,
        deficit_now=now.deficit,
        first_shortfall_at=first_short,
        minutes_until_shortfall=(
            (first_short - as_of).total_seconds() / 60 if first_short is not None else None
        ),
        shortfall_minutes=sum((s.end - s.start).total_seconds() / 60 for s in short),
        worst_deficit=max((s.deficit or 0) for s in segments),
        deficit_physician_minutes=round(deficit_pm, 4),
        deficit_physician_minutes_if_uncertain_excluded=round(deficit_pm_conf, 4),
        confidence=confidence,
        uncertainty_reasons=uncertainty,
    )

    # --- chart points ------------------------------------------------------------
    sample_times = {s.start for s in segments}
    step = timedelta(minutes=step_minutes)
    tick = as_of + step
    while tick < horizon_end:
        sample_times.add(tick)
        tick += step
    boundaries = {s.start for s in segments}
    points = []
    for moment in sorted(sample_times):
        s = _segment_at(segments, moment)
        points.append(
            CoveragePoint(
                at=moment,
                kind="now"
                if moment == as_of
                else ("boundary" if moment in boundaries else "interval"),
                required=s.required,
                available_confirmed=s.available_confirmed,
                available_uncertain=s.available_uncertain,
                deficit=s.deficit,
                spike_active=None if s.spike_adjustment is None else s.spike_adjustment > 0,
            )
        )
    last = segments[-1]
    points.append(
        CoveragePoint(
            at=horizon_end,
            kind="horizon_end",
            required=last.required,
            available_confirmed=last.available_confirmed,
            available_uncertain=last.available_uncertain,
            deficit=last.deficit,
            spike_active=None if last.spike_adjustment is None else last.spike_adjustment > 0,
        )
    )

    # --- annotations & explanations ------------------------------------------------
    annotations: list[CoverageAnnotation] = []
    changes: list[tuple[datetime, str]] = []
    ends: dict[datetime, list[Window]] = {}
    starts: dict[datetime, list[Window]] = {}
    for w in model.windows:
        if w.end is not None and as_of < w.end < horizon_end:
            ends.setdefault(w.end, []).append(w)
        if not w.on_now and as_of < w.start < horizon_end:
            starts.setdefault(w.start, []).append(w)
    for moment, group in sorted(ends.items()):
        before = _segment_at(segments, moment - timedelta(microseconds=1)).available
        after = _segment_at(segments, moment).available
        for w in group:
            annotations.append(
                CoverageAnnotation(
                    at=moment,
                    kind="shift_end",
                    label=f"{w.name}'s {'proposed split shift' if w.proposed else 'shift'} "
                    f"ends at {fmt_local(moment, tz)}",
                    physician_id=w.physician_id,
                )
            )
        who = _join_names([w.name + (" (proposed)" if w.proposed else "") for w in group])
        noun = "shift ends" if len(group) == 1 else "shifts end"
        changes.append(
            (
                moment,
                f"{who}'s {noun} at {fmt_local(moment, tz)}, reducing available coverage "
                f"from {before} to {after}.",
            )
        )
    for moment, group in sorted(starts.items()):
        for w in group:
            label = (
                f"{w.name}'s proposed split shift would start at {fmt_local(moment, tz)} "
                "(projected if accepted)"
                if w.proposed
                else f"{w.name} accepted a split shift and is expected online at "
                f"{fmt_local(moment, tz)} (pending activation, not confirmed)"
                if w.pending
                else f"{w.name}'s scheduled shift starts at {fmt_local(moment, tz)}"
            )
            annotations.append(
                CoverageAnnotation(
                    at=moment, kind="shift_start", label=label, physician_id=w.physician_id
                )
            )
            tail = "; end time unknown, so marked uncertain" if w.end is None else ""
            changes.append((moment, f"{label}, adding coverage{tail}."))
    for prev, cur in zip(segments, segments[1:], strict=False):
        if prev.required_base != cur.required_base:
            label = (
                f"Coverage requirement changes from {prev.required_base} to {cur.required_base} "
                f"at {fmt_local(cur.start, tz)} (local time block)"
            )
            annotations.append(
                CoverageAnnotation(at=cur.start, kind="requirement_change", label=label)
            )
            changes.append((cur.start, f"{label}."))
        if (prev.spike_adjustment or 0) != (cur.spike_adjustment or 0):
            ending = (cur.spike_adjustment or 0) < (prev.spike_adjustment or 0)
            kind = "spike_end" if ending else "spike_start"
            label = (
                f"Demand-spike adjustment ends at {fmt_local(cur.start, tz)}: known arrivals leave "
                "the 60-minute window or the hourly baseline changes (no future arrivals assumed)"
                if ending
                else f"Demand-spike adjustment applies from {fmt_local(cur.start, tz)} "
                "(new local hour has a lower p90 baseline)"
            )
            annotations.append(CoverageAnnotation(at=cur.start, kind=kind, label=label))
            changes.append((cur.start, f"{label}."))
    for moment in zone_transitions(tz, as_of, horizon_end):
        if moment < horizon_end:
            label = f"Local clock change (DST) at {fmt_local(moment, tz)}"
            annotations.append(CoverageAnnotation(at=moment, kind="dst_transition", label=label))
            changes.append((moment, f"{label}; local-time rules re-evaluated."))
    annotations.sort(key=lambda a: (a.at, a.kind, a.label))
    changes.sort(key=lambda c: (c[0], c[1]))

    explanations: list[str] = []
    if not requirement_defined:
        explanations.append(
            f"No coverage requirement is defined for {hospital.name} in this horizon; gaps "
            "cannot be evaluated."
        )
    elif now.deficit:
        explanations.append(
            f"Coverage is below requirement now: {now.available} available vs {now.required} "
            f"required ({now.required_base} base"
            f"{f' + {now.spike_adjustment} demand spike' if now.spike_adjustment else ''})."
        )
    elif first_short is not None:
        s = _segment_at(segments, first_short)
        explanations.append(
            f"Coverage falls below requirement at {fmt_local(first_short, tz)}: {s.available} "
            f"available vs {s.required} required, for {metrics.shortfall_minutes:g} of the next "
            f"{horizon_minutes} min ({metrics.deficit_physician_minutes:g} physician-minutes, "
            "modeled)."
        )
    else:
        margin = min(s.available - (s.required or 0) for s in segments if s.required is not None)
        explanations.append(
            f"Requirement met throughout the next {horizon_minutes} min (minimum margin {margin})."
        )
    if model.demand is not None:
        current = model.demand.evaluate(as_of)
        if current.spike:
            explanations.append(
                f"The previous 60-minute consultation volume ({current.arrivals}) exceeds this "
                f"hospital's p90 baseline ({current.baseline_p90:g}) for "
                f"{current.local_hour_label}; "
                "an additional qualified physician is required under the demand-spike rule."
            )
        elif current.spike is None:
            explanations.append(
                f"No usable p90 baseline for {current.local_hour_label} "
                f"({current.baseline_status}); "
                "the demand-spike adjustment cannot be evaluated."
            )
    if not model.windows:
        explanations.append(
            f"No physician credentialed at {hospital.name} is on shift or scheduled within the "
            "horizon."
        )
    explanations.extend(text for _, text in changes)
    for c in model.contributors:
        if c.status == "excluded":
            explanations.append(
                f"{c.display_name} cannot count toward {hospital.name}: {c.reasons[0]}."
            )
    for w in model.windows:
        if w.certainty == "uncertain":
            detail = "; ".join(
                r
                for r in w.reasons
                if r in UNCERTAIN_FLAGS.values()
                or r.startswith("shift end")
                or (w.pending and r.startswith("accepted split shift"))
            )
            explanations.append(
                f"Forecast contains uncertainty: {w.name} — {detail or 'unverified coverage'}."
            )

    return HospitalCoverage(
        hospital_id=hospital.id,
        hospital_name=hospital.name,
        timezone=tz,
        as_of=as_of,
        horizon_end=horizon_end,
        requirement_defined=requirement_defined,
        metrics=metrics,
        segments=segments,
        points=points,
        annotations=annotations,
        contributors=model.contributors,
        explanations=explanations,
    )


def build_hospital_model(
    hospital: Hospital,
    physicians: Sequence[PhysicianState],
    requirements: Sequence[CoverageRequirement],
    demand: HospitalDemandModel | None,
    as_of: datetime,
    horizon_end: datetime,
    rule: CoverageRule,
) -> HospitalCoverageModel:
    windows: list[Window] = []
    contributors: list[CoverageContributor] = []
    for p in sorted(physicians, key=lambda x: x.physician_id):
        credentialed = hospital.id in p.credentialed_hospital_ids
        scope = p.routing_scope_hospital_ids
        if credentialed and scope is not None and hospital.id not in scope:
            contributors.append(
                CoverageContributor(
                    physician_id=p.physician_id,
                    display_name=p.display_name,
                    status="excluded",
                    reasons=[
                        f"credentialed at {hospital.name}, but outside the approved split-shift "
                        f"routing scope ({', '.join(scope)})"
                    ],
                )
            )
            continue
        if not credentialed:
            if p.on_shift:
                contributors.append(
                    CoverageContributor(
                        physician_id=p.physician_id,
                        display_name=p.display_name,
                        status="excluded",
                        reasons=[f"on shift but not credentialed at {hospital.name}"],
                    )
                )
            continue
        window, why_not = physician_window(p, as_of, horizon_end, rule, hospital.timezone)
        if window is None:
            contributors.append(
                CoverageContributor(
                    physician_id=p.physician_id,
                    display_name=p.display_name,
                    status="excluded",
                    reasons=why_not,
                )
            )
            continue
        windows.append(window)
        contributors.append(
            CoverageContributor(
                physician_id=p.physician_id,
                display_name=p.display_name,
                status="counted"
                if window.on_now
                else ("pending_activation" if window.pending else "joins_later"),
                certainty=window.certainty,
                counts_from=window.start,
                counts_until=window.end,
                reasons=list(window.reasons),
            )
        )
    return HospitalCoverageModel(
        hospital=hospital,
        as_of=as_of,
        horizon_end=horizon_end,
        windows=windows,
        requirements=[r for r in requirements if r.hospital_id == hospital.id],
        demand=demand,
        contributors=contributors,
    )


def hypothetical_window(
    physician_id: str, name: str, start: datetime, end: datetime, reason: str
) -> Window:
    """A what-if contribution window (e.g. an off-shift physician coming online)."""
    return Window(
        physician_id=physician_id,
        name=name,
        start=start,
        end=end,
        certainty="uncertain",
        reasons=(reason,),
        on_now=False,
        proposed=True,
    )


__all__ = [
    "HospitalCoverageModel",
    "Window",
    "build_hospital_coverage",
    "build_hospital_model",
    "hypothetical_window",
    "physician_window",
]
