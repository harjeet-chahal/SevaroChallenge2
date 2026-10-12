"""Build the consult-dispatch problem from the Phase 3 analysis (pure).

Hard constraints (an edge consult -> physician exists only if all hold):

  BRIEF rule 1   physician is on shift and credentialed at the consult's hospital
  BRIEF rule 2   not busy (Synapse call/video, suspected external video), phone not
                 ringing for another call, last call ended >= 2 minutes ago
  BRIEF avail.   not Temporarily Unavailable
  scope          hospital inside the physician's routing scope (split-shift protection),
                 except an overdue consult at another credentialed hospital: an "overflow"
                 edge that costs more than any regular edge, so it is used only when no
                 one else can take the consult
  state          the consult is open, has no working assignee (we never move a consult
                 silently) and is in a routable stage
  capacity       at most ``sync_capacity`` new synchronous consults per physician per round;
                 open asynchronous consults (imaging, notes) never consume it

Soft preferences become bounded integer edge costs (see ``DispatchWeights``).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from app.engines.analysis import OperationalAnalysis
from app.engines.event_processing import normalize_label
from app.engines.optimization.config import OptimizationConfig
from app.engines.timeline import fmt_local, local
from app.schemas.common import Severity
from app.schemas.consultation import ConsultationState, ConsultStage
from app.schemas.dispatch import CostComponent, Exclusion, RuleCheck
from app.schemas.hospital import Hospital
from app.schemas.physician import Availability, PhysicianState

ASYNC_STAGES = {
    ConsultStage.IMAGING_PENDING,
    ConsultStage.IMAGING_REVIEW,
    ConsultStage.NOTE_PENDING,
    ConsultStage.DOCUMENTATION,
}
SEVERITY_LEVEL = {Severity.CRITICAL: 2, Severity.WARNING: 1, Severity.INFO: 0}
TIER_LABELS = {
    5: "critical alert · stroke",
    4: "critical alert",
    3: "warning alert · stroke",
    2: "warning alert",
    1: "stroke · within standard",
    0: "within standard",
}


@dataclass(frozen=True)
class PhysicianView:
    physician_id: str
    name: str
    availability: str
    activity: str
    on_shift: bool | None
    credentialed: tuple[str, ...]
    scope: tuple[str, ...]
    consults_this_shift: int
    """Count used for routing (may be seeded for a joining physician)."""
    actual_consults_this_shift: int
    open_consults: int
    open_async: int
    low_volume: bool
    low_volume_known: bool
    threshold: int
    minutes_since_last_call: float | None
    last_call_ended_at: datetime | None
    minutes_to_shift_end: int | None
    eligible: bool
    capacity: int
    ringing_consult_ids: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    """Reasons the physician cannot take a new consult (empty when eligible)."""
    checks: tuple[RuleCheck, ...]
    uncertainty: tuple[str, ...]
    agent_unverified: bool
    agent_inferred: bool
    counts_for_coverage: bool
    coverage_hospitals: tuple[str, ...]


@dataclass(frozen=True)
class ConsultView:
    consult_id: str
    hospital_id: str | None
    hospital_name: str | None
    timezone: str
    consult_type: str | None
    category: str | None
    stage: str
    kind: str  # assign | reassign | confirm_ringing
    current_physician_id: str | None
    tier: int
    severity: str | None
    waiting_minutes: float | None
    wait_key: int
    queue_key: tuple
    """FIFO order used by the least-loaded baseline (arrival order)."""
    pinned_physician_id: str | None
    next_threshold_at: datetime | None
    reason: str


@dataclass(frozen=True)
class Edge:
    consult_id: str
    physician_id: str
    cost: int
    components: tuple[CostComponent, ...]
    overflow: bool = False
    """Outside the physician's split-shift routing scope: a last resort for an overdue
    consult (costs more than any regular edge)."""


@dataclass
class DispatchProblem:
    as_of: datetime
    data_version: int
    physicians: dict[str, PhysicianView]
    consults: list[ConsultView]
    edges: dict[tuple[str, str], Edge]
    exclusions: dict[str, list[Exclusion]]
    credentialed_on_shift: dict[str, list[str]]
    skipped: list[tuple[str, str, str | None, str]]
    config: OptimizationConfig
    max_edge_cost: int
    notes: list[str] = field(default_factory=list)

    def recency_key(self, physician_id: str) -> tuple:
        """Tie-break for equal costs: answered longest ago first (never answered first), then
        physician id (brief rule 4)."""
        ended = self.physicians[physician_id].last_call_ended_at
        return (ended is not None, ended or datetime.min, physician_id)

    def edges_for(self, consult_id: str) -> list[Edge]:
        return sorted(
            (e for (c, _), e in self.edges.items() if c == consult_id),
            key=lambda e: (e.cost, self.recency_key(e.physician_id)),
        )


def _category(consult_type: str | None, categories: Mapping[str, list[str]]) -> str | None:
    if not consult_type:
        return None
    label = normalize_label(consult_type)
    return next((cat for cat, labels in categories.items() if label in labels), None)


def network_timezone(hospitals: Sequence[Hospital]) -> str:
    """The zone most hospitals use (ties: alphabetical); shift times are read in it."""
    zones = Counter(h.timezone for h in hospitals)
    return min(zones, key=lambda z: (-zones[z], z)) if zones else "UTC"


def role_threshold(
    role: str | None,
    cfg: OptimizationConfig,
    *,
    shift_start: datetime | None = None,
    tz: str = "UTC",
) -> tuple[int, bool]:
    """(low-volume threshold, decided) from the roster role, else from the shift start."""
    r = cfg.routing
    label = normalize_label(role) if role else ""
    if label in {normalize_label(x) for x in r.night_role_labels}:
        return r.low_volume_night_max, True
    if label in {normalize_label(x) for x in r.day_role_labels}:
        return r.low_volume_day_max, True
    if shift_start is not None:
        return (
            r.low_volume_night_max if is_night_start(shift_start, tz, cfg) else r.low_volume_day_max
        ), True
    return r.low_volume_day_max, False


def is_night_start(start: datetime, tz: str, cfg: OptimizationConfig) -> bool:
    hour = local(start, tz).hour
    r = cfg.routing
    if r.night_shift_from_hour > r.night_shift_until_hour:
        return hour >= r.night_shift_from_hour or hour < r.night_shift_until_hour
    return r.night_shift_from_hour <= hour < r.night_shift_until_hour


def shift_start_of(p: PhysicianState) -> datetime | None:
    if p.temporary_shift is not None:
        return p.temporary_shift.start_at
    if p.scheduled_shift is not None:
        return p.scheduled_shift.start
    return p.shift_started_at or p.next_shift_starts_at


def max_edge_cost(cfg: OptimizationConfig) -> int:
    w = cfg.weights
    return (
        w.consult_load_cap
        + w.open_load_cap
        + w.not_low_volume
        + w.recency_window_minutes
        + max(w.shift_ending_minutes * w.per_minute_near_shift_end, w.unknown_shift_end)
        + w.unverified_availability
        + w.reassignment_disruption
        + max(0, cfg.routing.sync_capacity - 1) * w.per_additional_sync_consult
    )


def physician_view(
    p: PhysicianState,
    analysis: OperationalAnalysis,
    cfg: OptimizationConfig,
    *,
    scope: frozenset[str] | None = None,
    seeded_count: int | None = None,
) -> PhysicianView:
    as_of = analysis.state.as_of
    r = cfg.routing
    consults = {c.consult_id: c for c in analysis.state.consultations}
    open_ids = [cid for cid in p.open_consult_ids if cid in consults]
    open_async = sum(consults[cid].stage in ASYNC_STAGES for cid in open_ids)
    tz = network_timezone(analysis.state.hospitals)
    start = shift_start_of(p)
    threshold, role_known = role_threshold(p.roster_role, cfg, shift_start=start, tz=tz)
    label = normalize_label(p.roster_role) if p.roster_role else ""
    labelled = label in {normalize_label(x) for x in [*r.night_role_labels, *r.day_role_labels]}
    count = p.consults_this_shift if seeded_count is None else seeded_count
    since_call = (
        (as_of - p.signals.last_call_ended_at).total_seconds() / 60
        if p.signals.last_call_ended_at is not None
        else None
    )
    ringing = tuple(sorted({s.consult_id or s.event_id for s in p.signals.ringing}))
    checks: list[RuleCheck] = []
    blocking: list[str] = []

    def check(code: str, label: str, ok: bool, value: str, message: str, source: str) -> None:
        checks.append(
            RuleCheck(
                code=code, label=label, passed=ok, value=value, message=message, source=source
            )
        )
        if not ok:
            blocking.append(message)

    on = bool(p.on_shift) and (p.minutes_to_shift_end is None or p.minutes_to_shift_end > 0)
    check(
        "on_shift",
        "On shift (rule 1)",
        on,
        "on shift" if on else "not on shift",
        "on shift" if on else "not on shift",
        "brief",
    )
    busy = p.availability is Availability.BUSY
    check(
        "not_busy",
        "Not busy (rule 2)",
        not busy,
        p.activity.value,
        f"busy ({p.activity.value.replace('_', ' ')})" if busy else "not on a call or video",
        "brief",
    )
    tu = p.availability is Availability.UNAVAILABLE
    check(
        "not_unavailable",
        "Not Temporarily Unavailable",
        not tu,
        p.signals.self_reported_status.value,
        "self-reported Temporarily Unavailable" if tu else "not Temporarily Unavailable",
        "brief",
    )
    if r.exclude_ringing_for_other_call:
        check(
            "not_ringing",
            "Phone not ringing for another call (rule 2)",
            not ringing,
            ", ".join(ringing) if ringing else "not ringing",
            f"phone ringing for {', '.join(ringing)}" if ringing else "phone not ringing",
            "brief",
        )
    cooled = since_call is None or since_call * 60 >= r.call_cooldown_seconds
    check(
        "call_cooldown",
        "Last call ended ≥ 2 min ago (rule 2)",
        cooled,
        "no call this shift" if since_call is None else f"{since_call:.1f} min ago",
        "no recent call"
        if since_call is None
        else (
            f"last call ended {since_call:.1f} min ago (≥ {r.call_cooldown_seconds // 60} min)"
            if cooled
            else f"ended a call {since_call:.1f} min ago (< {r.call_cooldown_seconds // 60} min)"
        ),
        "brief",
    )

    uncertainty: list[str] = []
    flag_codes = {f.code for f in p.flags}
    unverified = "availability_unverified" in flag_codes
    inferred = "agent_online_inferred" in flag_codes
    if unverified:
        uncertainty.append(
            "desktop agent offline — availability unverified (routing assumes available)"
        )
    if inferred:
        uncertainty.append("agent online only inferred from a later desktop-agent event")
    if not role_known:
        uncertainty.append(
            f"roster role '{p.roster_role or 'unknown'}' is not day/night; day low-volume "
            f"threshold ({threshold}) used"
        )
    elif not labelled and start is not None:
        night = threshold == r.low_volume_night_max
        uncertainty.append(
            f"no day/night roster role: {'night' if night else 'day'} low-volume threshold "
            f"({threshold}) from the shift start ({fmt_local(start, tz)})"
        )
    if seeded_count is not None:
        uncertainty.append(
            f"routing count seeded to {seeded_count} (split-shift protection), actual "
            f"{p.consults_this_shift}"
        )

    credentialed = tuple(sorted(p.credentialed_hospital_ids))
    in_scope = tuple(h for h in credentialed if scope is None or h in scope)
    coverage_hospitals = tuple(
        sorted(
            hid
            for hid, model in analysis.coverage_models.items()
            if any(w.physician_id == p.physician_id and w.covers(as_of) for w in model.windows)
        )
    )
    eligible = not blocking
    return PhysicianView(
        physician_id=p.physician_id,
        name=p.display_name,
        availability=p.availability.value,
        activity=p.activity.value,
        on_shift=p.on_shift,
        credentialed=credentialed,
        scope=in_scope,
        consults_this_shift=count,
        actual_consults_this_shift=p.consults_this_shift,
        open_consults=len(open_ids),
        open_async=open_async,
        low_volume=count <= threshold,
        low_volume_known=role_known,
        threshold=threshold,
        minutes_since_last_call=since_call,
        last_call_ended_at=p.signals.last_call_ended_at,
        minutes_to_shift_end=p.minutes_to_shift_end,
        eligible=eligible,
        capacity=r.sync_capacity if eligible else 0,
        ringing_consult_ids=ringing,
        blocking_reasons=tuple(blocking),
        checks=tuple(checks),
        uncertainty=tuple(uncertainty),
        agent_unverified=unverified,
        agent_inferred=inferred,
        counts_for_coverage=bool(coverage_hospitals),
        coverage_hospitals=coverage_hospitals,
    )


def edge_cost(
    p: PhysicianView, kind: str, cfg: OptimizationConfig
) -> tuple[int, tuple[CostComponent, ...]]:
    """Bounded integer cost of sending one consult to ``p`` (lower is better)."""
    w = cfg.weights
    parts: list[CostComponent] = []

    def add(name: str, value: int, detail: str) -> None:
        if value:
            parts.append(CostComponent(name=name, value=value, detail=detail))

    add(
        "workload",
        min(w.consult_load_cap, w.per_consult_this_shift * p.consults_this_shift),
        f"{p.consults_this_shift} consults this shift × {w.per_consult_this_shift}",
    )
    add(
        "open_consults",
        min(w.open_load_cap, w.per_open_consult * p.open_consults),
        f"{p.open_consults} open consults ({p.open_async} async) × {w.per_open_consult}",
    )
    add(
        "rule3_not_low_volume",
        0 if p.low_volume else w.not_low_volume,
        f"above the low-volume threshold ({p.consults_this_shift} > {p.threshold})",
    )
    if p.minutes_since_last_call is not None:
        add(
            "rule4_recently_answered",
            max(0, w.recency_window_minutes - int(p.minutes_since_last_call)),
            f"last call ended {p.minutes_since_last_call:.0f} min ago "
            f"(prefers least recently answered)",
        )
    if p.minutes_to_shift_end is None:
        add("shift_end_unknown", w.unknown_shift_end, "shift end unknown")
    elif p.minutes_to_shift_end < w.shift_ending_minutes:
        add(
            "shift_ending",
            (w.shift_ending_minutes - p.minutes_to_shift_end) * w.per_minute_near_shift_end,
            f"shift ends in {p.minutes_to_shift_end} min",
        )
    if p.agent_unverified:
        add("availability_unverified", w.unverified_availability, "desktop agent offline")
    elif p.agent_inferred:
        add("agent_inferred", w.inferred_agent, "agent online only inferred")
    if kind == "reassign":
        add("reassignment_disruption", w.reassignment_disruption, "moves an existing consult")
    return sum(c.value for c in parts), tuple(parts)


def _waiting(c: ConsultationState) -> float | None:
    seconds = c.seconds_since_received if c.seconds_since_received is not None else None
    return None if seconds is None else seconds / 60


def build_dispatch_problem(
    analysis: OperationalAnalysis,
    cfg: OptimizationConfig,
    *,
    scopes: Mapping[str, frozenset[str]] | None = None,
    seeded_counts: Mapping[str, int] | None = None,
) -> DispatchProblem:
    state = analysis.state
    as_of = state.as_of
    scopes = scopes or {}
    seeded_counts = seeded_counts or {}
    r = cfg.routing
    hospitals = {h.id: h for h in state.hospitals}

    roster = [p for p in state.physicians if p.on_shift or p.roster == "on_shift"]

    def scope_of(p: PhysicianState) -> frozenset[str] | None:
        if p.physician_id in scopes:
            return scopes[p.physician_id]
        # Phase 5: an activated split shift routes only inside its approved scope.
        if p.routing_scope_hospital_ids is not None:
            return frozenset(p.routing_scope_hospital_ids)
        return None

    def seed_of(p: PhysicianState) -> int | None:
        if p.physician_id in seeded_counts:
            return seeded_counts[p.physician_id]
        temp = p.temporary_shift
        if temp is not None and temp.phase == "active":
            # Trap protection: seeded count plus the consults actually taken since joining.
            return temp.seeded_consult_count + p.consults_this_shift
        return None

    views = {
        p.physician_id: physician_view(
            p,
            analysis,
            cfg,
            scope=scope_of(p),
            seeded_count=seed_of(p),
        )
        for p in sorted(roster, key=lambda x: x.physician_id)
    }
    severity: dict[str, Severity] = {}
    for a in analysis.alerts.alerts:
        if a.consult_id and SEVERITY_LEVEL[a.severity] > SEVERITY_LEVEL.get(
            severity.get(a.consult_id, Severity.INFO), 0
        ):
            severity[a.consult_id] = a.severity
    next_threshold: dict[str, datetime] = {}
    for a in analysis.alerts.alerts:
        if a.consult_id and a.impact_at is not None and a.impact_at > as_of:
            prev = next_threshold.get(a.consult_id)
            next_threshold[a.consult_id] = a.impact_at if prev is None else min(prev, a.impact_at)

    ringing_by_consult: dict[str, list[str]] = {}
    for v in views.values():
        for cid in v.ringing_consult_ids:
            ringing_by_consult.setdefault(cid, []).append(v.physician_id)
    by_id = {p.physician_id: p for p in state.physicians}

    consults: list[ConsultView] = []
    skipped: list[tuple[str, str, str | None, str]] = []
    for c in sorted(state.consultations, key=lambda x: x.consult_id):
        if not c.is_open:
            continue
        kind: str | None = None
        reason = ""
        assignee = by_id.get(c.assigned_physician_id or "")
        if c.assigned_physician_id is None:
            if c.stage in r.routable_unassigned_stages:
                kind, reason = "assign", f"unassigned ({c.stage.value.replace('_', ' ')})"
            elif c.routing_started_at is not None:
                # Routing evidently started (a ring or a failed attempt) without a triage event.
                kind, reason = "assign", "unassigned; routing started without a recorded triage"
            else:
                skipped.append(
                    (
                        c.consult_id,
                        c.stage.value,
                        None,
                        f"unassigned in stage '{c.stage.value}', not a routable stage "
                        "(routing starts after triage — assumption)",
                    )
                )
                continue
        else:
            unavailable = assignee is not None and (
                assignee.availability is Availability.UNAVAILABLE or not assignee.on_shift
            )
            sev_now = severity.get(c.consult_id)
            stalled = (
                r.reassign_stalled_assignment
                and not unavailable
                and assignee is not None
                and assignee.availability is Availability.BUSY
                and c.stage is ConsultStage.ASSIGNED
                and sev_now is not None
                and SEVERITY_LEVEL[sev_now] >= SEVERITY_LEVEL[Severity(r.stalled_min_severity)]
            )
            if stalled:
                kind = "reassign"
                busy_with = assignee.activity.value.replace("_", " ")
                reason = (
                    f"assigned to {assignee.display_name} {c.seconds_in_stage // 60} min ago, "
                    f"hospital not yet contacted ({sev_now.value} alert), and "
                    f"{assignee.display_name} is now busy ({busy_with})"
                )
            elif (
                unavailable and r.reassign_unavailable_assignee and c.stage in r.reassignable_stages
            ):
                kind = "reassign"
                state_txt = (
                    "Temporarily Unavailable"
                    if assignee.availability is Availability.UNAVAILABLE
                    else "off shift"
                )
                reason = f"assigned physician {assignee.display_name} is {state_txt}"
            else:
                who = assignee.display_name if assignee else c.assigned_physician_id
                if not unavailable:
                    detail = " — never reassigned silently"
                elif c.stage in (ConsultStage.NOTE_PENDING, ConsultStage.DOCUMENTATION):
                    detail = " (unavailable, but notes stay with their author)"
                elif c.stage is ConsultStage.VIDEO_IN_PROGRESS:
                    detail = " (a video visit is in progress; not moved mid-visit)"
                else:
                    detail = f" (unavailable; stage '{c.stage.value}' is not reassigned)"
                why = f"assigned to {who}{detail}"
                skipped.append((c.consult_id, c.stage.value, c.assigned_physician_id, why))
                continue

        pinned = None
        ringers = ringing_by_consult.get(c.consult_id, [])
        if kind == "assign" and len(ringers) == 1:
            p = views[ringers[0]]
            other_blocks = [chk for chk in p.checks if not chk.passed and chk.code != "not_ringing"]
            if not other_blocks and c.hospital_id in p.scope:
                pinned, kind = p.physician_id, "confirm_ringing"
                reason = f"call already ringing to {p.name}"

        sev = severity.get(c.consult_id)
        category = _category(c.consult_type, analysis.config.consult_categories)
        tier = 2 * (SEVERITY_LEVEL[sev] if sev else 0) + (1 if category == "stroke" else 0)
        waiting = _waiting(c)
        wait_key = min(cfg.weights.wait_cap_minutes, int(waiting or 0))
        hospital = hospitals.get(c.hospital_id or "")
        consults.append(
            ConsultView(
                consult_id=c.consult_id,
                hospital_id=c.hospital_id,
                hospital_name=hospital.name if hospital else c.hospital_name,
                timezone=hospital.timezone if hospital else "UTC",
                consult_type=c.consult_type,
                category=category,
                stage=c.stage.value,
                kind=kind,
                current_physician_id=c.assigned_physician_id,
                tier=tier,
                severity=sev.value if sev else None,
                waiting_minutes=round(waiting, 2) if waiting is not None else None,
                wait_key=wait_key,
                queue_key=(c.received_at or c.stage_entered_at, c.consult_id),
                pinned_physician_id=pinned,
                next_threshold_at=next_threshold.get(c.consult_id),
                reason=reason,
            )
        )

    edges: dict[tuple[str, str], Edge] = {}
    exclusions: dict[str, list[Exclusion]] = {}
    credentialed_on_shift: dict[str, list[str]] = {}
    regular_max = max_edge_cost(cfg)
    overflow_level = SEVERITY_LEVEL[Severity(cfg.trap.overflow_min_severity)]
    for c in consults:
        excluded: list[Exclusion] = []
        overdue = c.severity is not None and SEVERITY_LEVEL[Severity(c.severity)] >= overflow_level
        pool = sorted(
            v.physician_id
            for v in views.values()
            if c.hospital_id is not None and c.hospital_id in v.credentialed and v.on_shift
        )
        credentialed_on_shift[c.consult_id] = pool
        for pid in pool:
            v = views[pid]
            reasons: list[str] = []
            if c.pinned_physician_id is not None and pid != c.pinned_physician_id:
                reasons.append(f"call already ringing to {views[c.pinned_physician_id].name}")
            if pid == c.current_physician_id:
                reasons.append("currently assigned (the consult is being moved away)")
            overflow = c.hospital_id not in v.scope and cfg.trap.overflow_outside_scope and overdue
            if c.hospital_id not in v.scope and not overflow:
                reasons.append("outside routing scope (split-shift protection)")
            blocks = [
                b
                for chk, b in zip(
                    [x for x in v.checks if not x.passed], v.blocking_reasons, strict=True
                )
                if not (chk.code == "not_ringing" and v.ringing_consult_ids == (c.consult_id,))
            ]
            reasons.extend(blocks)
            if reasons:
                excluded.append(Exclusion(physician_id=pid, display_name=v.name, reasons=reasons))
                continue
            cost, parts = edge_cost(v, "reassign" if c.kind == "reassign" else c.kind, cfg)
            if overflow:
                extra = CostComponent(
                    name="split_shift_overflow",
                    value=regular_max + 1,
                    detail=f"outside {v.name}'s split-shift hospitals "
                    f"({', '.join(v.scope) or 'none'}); a last resort for an overdue consult, "
                    "costed above any regular option",
                )
                cost, parts = cost + extra.value, (*parts, extra)
            edges[(c.consult_id, pid)] = Edge(c.consult_id, pid, cost, parts, overflow=overflow)
        exclusions[c.consult_id] = excluded

    notes = [
        "No hospital-level priority is applied: the brief documents none "
        "(coverage tier semantics are not defined).",
        "Least recently answered is approximated by the most recent call end "
        "(the event stream has no separate 'answered' timestamp after a call ends).",
    ]
    return DispatchProblem(
        as_of=as_of,
        data_version=state.data_version,
        physicians=views,
        consults=consults,
        edges=edges,
        exclusions=exclusions,
        credentialed_on_shift=credentialed_on_shift,
        skipped=skipped,
        config=cfg,
        max_edge_cost=(
            2 * regular_max + 1 if any(e.overflow for e in edges.values()) else regular_max
        ),
        notes=notes,
    )


def describe_eligibility(p: PhysicianView, c: ConsultView) -> list[str]:
    evidence = [f"on shift and credentialed at {c.hospital_name or c.hospital_id} (rule 1)"]
    for chk in p.checks:
        if chk.code == "on_shift":
            continue
        if chk.code == "not_ringing" and not chk.passed:
            evidence.append(f"phone is ringing for this consult ({c.consult_id})")
            continue
        evidence.append(chk.message)
    if p.minutes_to_shift_end is not None:
        evidence.append(f"{p.minutes_to_shift_end} min left in shift")
    if c.next_threshold_at is not None:
        evidence.append(f"next standard threshold at {fmt_local(c.next_threshold_at, c.timezone)}")
    return evidence
