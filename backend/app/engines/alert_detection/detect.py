"""Risk detection (pure): reconstructed state + forecasts -> unranked alert drafts.

Every alert names the rule that fired, whether that rule is from the brief or a documented
assumption, the evidence, and a recommended intervention *category*. Nothing is executed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.engines.event_processing import normalize_label
from app.engines.rules import RiskConfig, StageStandard
from app.engines.timeline import fmt_local
from app.schemas.alert import (
    AlertCategory,
    AlertEvidence,
    RecommendedAction,
    RuleCode,
    RuleSource,
)
from app.schemas.common import Severity
from app.schemas.consultation import ConsultationState, ConsultStage
from app.schemas.coverage import CoverageReport, HospitalCoverage
from app.schemas.demand import DemandReport
from app.schemas.hospital import Hospital
from app.schemas.physician import Availability, PhysicianState
from app.schemas.state import OperationalState

STAGE_LABELS = {
    ConsultStage.RECEIVED: "Received",
    ConsultStage.TRIAGED: "Triaged",
    ConsultStage.ASSIGNED: "Assigned",
    ConsultStage.PROVIDER_CONTACTED: "Provider contacted",
    ConsultStage.IMAGING_PENDING: "CT/CTA or imaging pending",
    ConsultStage.IMAGING_REVIEW: "Imaging review",
    ConsultStage.VIDEO_IN_PROGRESS: "Video in progress",
    ConsultStage.NOTE_PENDING: "Note pending",
    ConsultStage.DOCUMENTATION: "Documentation",
    ConsultStage.SIGNED_OFF: "Signed off",
}


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes:02d} min"
    return f"{minutes} min {sec:02d} s" if sec else f"{minutes} min"


@dataclass
class AlertDraft:
    alert_id: str
    rule_code: RuleCode
    rule_name: str
    rule_source: RuleSource
    rule_reference: str
    category: AlertCategory
    severity: Severity
    severity_reason: str
    title: str
    summary: str
    action: RecommendedAction
    action_reason: str
    category_rank: int
    category_reason: str
    urgency: float
    urgency_reason: str
    affected: int
    hospital_id: str | None = None
    consult_id: str | None = None
    physician_id: str | None = None
    condition_since: datetime | None = None
    elapsed_seconds: int | None = None
    warning_after_seconds: int | None = None
    critical_after_seconds: int | None = None
    impact_at: datetime | None = None
    minutes_to_impact: float | None = None
    evidence: list[AlertEvidence] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)


@dataclass
class DetectionContext:
    state: OperationalState
    config: RiskConfig
    coverage: CoverageReport
    demand: DemandReport
    hospitals: Mapping[str, Hospital]
    physicians: Mapping[str, PhysicianState]
    coverage_by_hospital: Mapping[str, HospitalCoverage]
    notes: list[str] = field(default_factory=list)

    @property
    def as_of(self) -> datetime:
        return self.state.as_of

    def category(self, consult_type: str | None) -> str | None:
        if not consult_type:
            return None
        label = normalize_label(consult_type)
        for category, labels in self.config.consult_categories.items():
            if label in labels:
                return category
        return None

    def hospital_name(self, hospital_id: str | None) -> str:
        h = self.hospitals.get(hospital_id or "")
        return h.name if h else (hospital_id or "unknown hospital")

    def tz(self, hospital_id: str | None) -> str:
        h = self.hospitals.get(hospital_id or "")
        return h.timezone if h else "UTC"

    def physician_name(self, physician_id: str | None) -> str:
        p = self.physicians.get(physician_id or "")
        return p.display_name if p else (physician_id or "unassigned")


def _severity_for(elapsed: float, std: StageStandard) -> Severity | None:
    if elapsed >= std.critical_minutes * 60:
        return Severity.CRITICAL
    if elapsed >= std.warning_minutes * 60:
        return Severity.WARNING
    return None


def _clock_start(
    c: ConsultationState, std: StageStandard
) -> tuple[datetime, str | None, str | None]:
    """(start, event_id, caveat). Note clock runs from the end of video or call."""
    if std.clock == "stage_entry":
        current = next((h for h in reversed(c.stage_history) if h.stage is c.stage), None)
        return c.stage_entered_at, current.event_id if current else None, None
    pending = [h for h in c.stage_history if h.stage is ConsultStage.NOTE_PENDING]
    if pending:
        return pending[-1].entered_at, pending[-1].event_id, None
    caveat = "no end of video or call was recorded; measured from note start instead"
    docs = [h for h in c.stage_history if h.stage is ConsultStage.DOCUMENTATION]
    if docs:
        return docs[-1].entered_at, docs[-1].event_id, caveat
    return c.stage_entered_at, None, caveat


def _is_stroke(ctx: DetectionContext, c: ConsultationState) -> bool:
    return ctx.category(c.consult_type) == "stroke"


def _consult_evidence(ctx: DetectionContext, c: ConsultationState) -> list[AlertEvidence]:
    tz = ctx.tz(c.hospital_id)
    evidence = [
        AlertEvidence(label="Hospital", value=f"{ctx.hospital_name(c.hospital_id)} ({tz})"),
        AlertEvidence(label="Consult type", value=c.consult_type or "unknown"),
        AlertEvidence(
            label="Current stage",
            value=f"{STAGE_LABELS[c.stage]} since {fmt_local(c.stage_entered_at, tz)}",
            at=c.stage_entered_at,
        ),
    ]
    if c.received_at:
        evidence.append(
            AlertEvidence(label="Received", value=fmt_local(c.received_at, tz), at=c.received_at)
        )
    if c.assigned_physician_id:
        p = ctx.physicians.get(c.assigned_physician_id)
        status = f" — {p.availability.value} ({p.activity.value})" if p else ""
        evidence.append(
            AlertEvidence(
                label="Assigned physician",
                value=f"{ctx.physician_name(c.assigned_physician_id)}{status}",
            )
        )
    else:
        evidence.append(AlertEvidence(label="Assigned physician", value="none"))
    if c.routing_failures:
        evidence.append(
            AlertEvidence(
                label="Routing failures",
                value=f"{c.routing_failures} (last {fmt_local(c.last_routing_failure_at, tz)})",
                at=c.last_routing_failure_at,
            )
        )
    return evidence


def detect_stage_standards(ctx: DetectionContext) -> list[AlertDraft]:
    drafts: list[AlertDraft] = []
    unevaluated: set[str] = set()
    for c in ctx.state.consultations:
        if not c.is_open:
            continue
        category = ctx.category(c.consult_type)
        for std in ctx.config.stage_standards:
            if c.stage not in std.stages:
                continue
            if std.requires_unassigned and c.assigned_physician_id is not None:
                continue
            if "all" not in std.applies_to:
                if category is None:
                    unevaluated.add(c.consult_id)
                    continue
                if category not in std.applies_to:
                    continue
            start, event_id, caveat = _clock_start(c, std)
            elapsed = (ctx.as_of - start).total_seconds()
            severity = _severity_for(elapsed, std)
            if severity is None:
                continue
            warn_s, crit_s = int(std.warning_minutes * 60), int(std.critical_minutes * 60)
            limit = crit_s if severity is Severity.CRITICAL else warn_s
            tz = ctx.tz(c.hospital_id)
            next_at = start + timedelta(seconds=crit_s) if severity is Severity.WARNING else None
            stroke = _is_stroke(ctx, c)
            evidence = _consult_evidence(ctx, c)
            evidence.insert(
                0,
                AlertEvidence(
                    label="Elapsed vs standard",
                    value=(
                        f"{fmt_duration(elapsed)} since {fmt_local(start, tz, seconds=True)}; "
                        f"warning at {std.warning_minutes:g} min, critical at "
                        f"{std.critical_minutes:g} min"
                    ),
                    at=start,
                    source_event_ids=[event_id] if event_id else [],
                ),
            )
            if next_at:
                evidence.append(
                    AlertEvidence(
                        label="Becomes critical at", value=fmt_local(next_at, tz), at=next_at
                    )
                )
            clock_text = (
                "since the end of video or call"
                if std.clock == "end_of_video_or_call"
                else "in this stage"
            )
            drafts.append(
                AlertDraft(
                    alert_id=f"{std.code.value}:consult:{c.consult_id}",
                    rule_code=std.code,
                    rule_name=std.name,
                    rule_source=std.source,
                    rule_reference=std.reference,
                    category=AlertCategory.CONSULT_DELAY,
                    severity=severity,
                    severity_reason=(
                        f"{fmt_duration(elapsed)} {clock_text} ≥ the {limit // 60}-min "
                        f"{severity.value} standard"
                    ),
                    title=f"{c.consult_id}: {std.name.split(' (')[0]} — {fmt_duration(elapsed)}",
                    summary=(
                        f"{c.consult_type or 'Consult'} at {ctx.hospital_name(c.hospital_id)} has "
                        "been "
                        f"{STAGE_LABELS[c.stage].lower()} for {fmt_duration(elapsed)} {clock_text} "
                        f"(warning {std.warning_minutes:g} min, critical {std.critical_minutes:g} "
                        "min)."
                    ),
                    action=std.action_critical
                    if severity is Severity.CRITICAL
                    else std.action_warning,
                    action_reason=f"Mapped from the breached standard ({severity.value}).",
                    category_rank=0 if stroke else 2,
                    category_reason=(
                        "stroke consult delay — highest clinical-urgency class"
                        if stroke
                        else "non-stroke consult delay"
                    ),
                    urgency=elapsed / crit_s,
                    urgency_reason=f"elapsed is {elapsed / crit_s:.2f}× the critical standard",
                    affected=1,
                    hospital_id=c.hospital_id,
                    consult_id=c.consult_id,
                    physician_id=c.assigned_physician_id,
                    condition_since=start + timedelta(seconds=warn_s),
                    elapsed_seconds=int(elapsed),
                    warning_after_seconds=warn_s,
                    critical_after_seconds=crit_s,
                    impact_at=next_at,
                    minutes_to_impact=(next_at - ctx.as_of).total_seconds() / 60
                    if next_at
                    else None,
                    evidence=evidence,
                    event_ids=[event_id] if event_id else [],
                    assumptions=[caveat] if caveat else [],
                )
            )
    if unevaluated:
        ctx.notes.append(
            f"Consult type unknown for {', '.join(sorted(unevaluated))}: type-specific standards "
            "(Stroke / General Neuro) were not evaluated; the 'All' standards still apply."
        )
    return drafts


def detect_open_notes(ctx: DetectionContext) -> list[AlertDraft]:
    rule = ctx.config.open_notes
    drafts: list[AlertDraft] = []
    window = timedelta(minutes=rule.window_minutes)
    for p in ctx.state.physicians:
        if not p.on_shift:
            continue
        notes = [
            c
            for c in ctx.state.consultations
            if c.is_open
            and c.assigned_physician_id == p.physician_id
            and c.stage in rule.note_stages
        ]
        if not notes:
            continue
        if p.scheduled_shift is None:
            ctx.notes.append(
                f"{p.display_name} has open notes but no known shift end; the open-notes-near-"
                "shift-end standard was not evaluated."
            )
            continue
        end = p.scheduled_shift.end
        remaining = end - ctx.as_of
        if not (timedelta(0) < remaining <= window):
            continue
        n = len(notes)
        if n >= rule.critical_min_open_notes:
            severity = Severity.CRITICAL
        elif n >= rule.warning_min_open_notes:
            severity = Severity.WARNING
        else:
            continue
        hospitals = sorted({c.hospital_id for c in notes if c.hospital_id})
        tz = ctx.tz(hospitals[0]) if len(hospitals) == 1 else "UTC"
        minutes = remaining.total_seconds() / 60
        drafts.append(
            AlertDraft(
                alert_id=f"{RuleCode.OPEN_NOTES_NEAR_SHIFT_END.value}:physician:{p.physician_id}",
                rule_code=RuleCode.OPEN_NOTES_NEAR_SHIFT_END,
                rule_name="Open notes within 60 min of the physician's shift end",
                rule_source="challenge_brief",
                rule_reference=rule.reference,
                category=AlertCategory.PHYSICIAN_WORKFLOW,
                severity=severity,
                severity_reason=(
                    f"{n} open note(s) with {fmt_duration(remaining.total_seconds())} left in "
                    "shift "
                    f"(warning: any, critical: {rule.critical_min_open_notes} or more)"
                ),
                title=f"{p.display_name}: {n} open note(s), shift ends {fmt_local(end, tz)}",
                summary=(
                    f"{p.display_name}'s shift ends in {fmt_duration(remaining.total_seconds())} "
                    "with "
                    f"{n} unfinished note(s): {', '.join(c.consult_id for c in notes)}."
                ),
                action=RecommendedAction.CONTACT_PHYSICIAN,
                action_reason=(
                    "Notes can only be finished by the assigned physician before shift end."
                ),
                category_rank=4,
                category_reason="physician workflow risk at shift end",
                urgency=n + (1 - minutes / rule.window_minutes),
                urgency_reason=f"{n} open note(s); {minutes:.0f} min to shift end",
                affected=n,
                hospital_id=hospitals[0] if len(hospitals) == 1 else None,
                physician_id=p.physician_id,
                condition_since=end - window,
                impact_at=end,
                minutes_to_impact=minutes,
                evidence=[
                    AlertEvidence(label="Shift ends", value=fmt_local(end, tz), at=end),
                    *[
                        AlertEvidence(
                            label=f"Open note {c.consult_id}",
                            value=f"{STAGE_LABELS[c.stage]} at {ctx.hospital_name(c.hospital_id)} "
                            f"since {fmt_local(c.stage_entered_at, ctx.tz(c.hospital_id))}",
                            at=c.stage_entered_at,
                        )
                        for c in notes
                    ],
                ],
            )
        )
    return drafts


def detect_assigned_unavailable(ctx: DetectionContext) -> list[AlertDraft]:
    rule = ctx.config.assigned_unavailable
    drafts: list[AlertDraft] = []
    for c in ctx.state.consultations:
        if not c.is_open or not c.assigned_physician_id:
            continue
        p = ctx.physicians.get(c.assigned_physician_id)
        if p is None or p.availability.value not in rule.unavailable_states:
            continue
        category = ctx.category(c.consult_type)
        critical = category in rule.critical_categories and c.stage in rule.critical_stages
        severity = Severity.CRITICAL if critical else rule.default_severity
        tz = ctx.tz(c.hospital_id)
        if p.availability is Availability.OFF_SHIFT and p.scheduled_shift:
            since = p.scheduled_shift.end
            why = f"shift ended at {fmt_local(since, tz)}"
        else:
            since = p.signals.status_since
            why = "self-reported Temporarily Unavailable" + (
                f" since {fmt_local(since, tz)}" if since else ""
            )
        elapsed = (ctx.as_of - since).total_seconds() if since else None
        drafts.append(
            AlertDraft(
                alert_id=f"{RuleCode.ASSIGNED_PHYSICIAN_UNAVAILABLE.value}:consult:{c.consult_id}",
                rule_code=RuleCode.ASSIGNED_PHYSICIAN_UNAVAILABLE,
                rule_name="Assigned physician unavailable",
                rule_source="assumption",
                rule_reference=(
                    "Brief lists 'a physician becomes temporarily unavailable while a stroke "
                    "consult "
                    "is still assigned' as a situation to detect, without a threshold. Severity: "
                    "critical for stroke consults before documentation, else warning (assumption)."
                ),
                category=AlertCategory.CONSULT_DELAY,
                severity=severity,
                severity_reason=(
                    f"{'stroke consult in an active clinical stage' if critical else 'consult'} "
                    f"assigned to a physician who is {p.availability.value.replace('_', ' ')}"
                ),
                title=f"{c.consult_id}: assigned to {p.display_name}, who is "
                f"{p.availability.value.replace('_', ' ')}",
                summary=(
                    f"{c.consult_type or 'Consult'} at {ctx.hospital_name(c.hospital_id)} "
                    f"({STAGE_LABELS[c.stage].lower()}) is assigned to {p.display_name}: {why}."
                ),
                action=RecommendedAction.REASSIGN_CONSULT,
                action_reason="The assigned physician cannot currently progress this consult.",
                category_rank=0 if category == "stroke" else 2,
                category_reason=(
                    "stroke consult at risk — highest clinical-urgency class"
                    if category == "stroke"
                    else "non-stroke consult at risk"
                ),
                urgency=(elapsed or 0) / 600,
                urgency_reason=(
                    f"physician unavailable for {fmt_duration(elapsed)}"
                    if elapsed
                    else "duration unknown"
                ),
                affected=1,
                hospital_id=c.hospital_id,
                consult_id=c.consult_id,
                physician_id=p.physician_id,
                condition_since=since,
                elapsed_seconds=int(elapsed) if elapsed is not None else None,
                evidence=[
                    AlertEvidence(
                        label="Physician availability",
                        value=f"{p.availability.value} — rule {p.decision_rule}",
                        at=since,
                        source_event_ids=p.evidence_event_ids,
                    ),
                    *_consult_evidence(ctx, c),
                ],
                event_ids=p.evidence_event_ids,
                assumptions=[
                    "Severity mapping for this situation is an assumption (not in the brief)."
                ],
            )
        )
    return drafts


def detect_routing_failures(ctx: DetectionContext) -> list[AlertDraft]:
    drafts: list[AlertDraft] = []
    for c in ctx.state.consultations:
        if not c.is_open or c.assigned_physician_id or not c.routing_failures:
            continue
        tz = ctx.tz(c.hospital_id)
        pool = [
            p
            for p in ctx.state.physicians
            if p.on_shift and c.hospital_id in p.credentialed_hospital_ids
        ]
        pool_text = (
            ", ".join(
                f"{p.display_name} ({p.availability.value}, {p.activity.value})" for p in pool
            )
            or "none"
        )
        stroke = _is_stroke(ctx, c)
        # Same scale as the stage alerts: time unassigned / the 'Triaged, not yet assigned'
        # critical standard, so ranking within a category compares like with like.
        triage = next(
            (s for s in ctx.config.stage_standards if s.code is RuleCode.STAGE_TRIAGED_UNASSIGNED),
            None,
        )
        unassigned_for = (ctx.as_of - c.stage_entered_at).total_seconds()
        overrun = (
            unassigned_for / (triage.critical_minutes * 60) if triage else unassigned_for / 600
        )
        drafts.append(
            AlertDraft(
                alert_id=f"{RuleCode.ROUTING_FAILURE.value}:consult:{c.consult_id}",
                rule_code=RuleCode.ROUTING_FAILURE,
                rule_name="Routing failed: no eligible physician",
                rule_source="assumption",
                rule_reference=ctx.config.routing_failure.reference,
                category=AlertCategory.CONSULT_DELAY,
                severity=ctx.config.routing_failure.severity,
                severity_reason=(
                    f"{c.routing_failures} routing attempt(s) failed; consult still unassigned"
                ),
                title=f"{c.consult_id}: routing failed {c.routing_failures}×",
                summary=(
                    f"No eligible physician was found for {c.consult_id} at "
                    f"{ctx.hospital_name(c.hospital_id)} ({c.routing_failures} failed attempts, "
                    "last "
                    f"{fmt_local(c.last_routing_failure_at, tz)}). Credentialed physicians on "
                    "shift now: "
                    f"{pool_text}."
                ),
                action=RecommendedAction.ESCALATE,
                action_reason=(
                    "Automatic routing cannot place this consult; a person must intervene."
                ),
                category_rank=0 if stroke else 2,
                category_reason="stroke consult cannot be routed"
                if stroke
                else "consult cannot be routed",
                urgency=overrun,
                urgency_reason=(
                    f"unassigned for {fmt_duration(unassigned_for)} ({overrun:.2f}× the triage "
                    f"critical standard); {c.routing_failures} failed attempt(s)"
                ),
                affected=1,
                hospital_id=c.hospital_id,
                consult_id=c.consult_id,
                condition_since=c.last_routing_failure_at,
                evidence=[
                    AlertEvidence(label="Credentialed physicians on shift now", value=pool_text),
                    *_consult_evidence(ctx, c),
                ],
            )
        )
    return drafts


def detect_signals(ctx: DetectionContext) -> list[AlertDraft]:
    drafts: list[AlertDraft] = []
    for p in ctx.state.physicians:
        if not p.on_shift:
            continue
        codes = {f.code: f for f in p.flags}
        checks = (
            (
                "external_video_suspected",
                RuleCode.SIGNAL_EXTERNAL_VIDEO,
                ctx.config.external_video,
                "Camera active with no Synapse session",
                p.signals.camera_since,
                RecommendedAction.CONTACT_PHYSICIAN,
                "Confirm whether the physician is on an external call.",
            ),
            (
                "availability_unverified",
                RuleCode.SIGNAL_AGENT_OFFLINE,
                ctx.config.agent_offline,
                "Desktop agent offline — availability unverified",
                p.signals.agent_status_since,
                RecommendedAction.CONTACT_PHYSICIAN,
                "Routing assumes available; confirm before relying on it.",
            ),
        )
        for flag, code, rule, name, since, action, action_reason in checks:
            if flag not in codes:
                continue
            drafts.append(
                AlertDraft(
                    alert_id=f"{code.value}:physician:{p.physician_id}",
                    rule_code=code,
                    rule_name=name,
                    rule_source="challenge_brief",
                    rule_reference=rule.reference,
                    category=AlertCategory.PHYSICIAN_SIGNAL,
                    severity=rule.severity,
                    severity_reason=f"{codes[flag].message} (severity level is an assumption)",
                    title=f"{p.display_name}: {name.lower()}",
                    summary=(
                        f"{p.display_name}: {codes[flag].message} Decided by {p.decision_rule}."
                    ),
                    action=action,
                    action_reason=action_reason,
                    category_rank=6,
                    category_reason="physician signal conflict / uncertainty",
                    urgency=((ctx.as_of - since).total_seconds() / 3600) if since else 0.0,
                    urgency_reason=(
                        f"ongoing for {fmt_duration((ctx.as_of - since).total_seconds())}"
                        if since
                        else "start time unknown"
                    ),
                    affected=len(p.open_consult_ids),
                    physician_id=p.physician_id,
                    condition_since=since,
                    evidence=[
                        AlertEvidence(label="Explanation", value=" ".join(p.explanation)),
                        AlertEvidence(
                            label="Open consults", value=", ".join(p.open_consult_ids) or "none"
                        ),
                    ],
                    event_ids=p.evidence_event_ids,
                )
            )
    return drafts


def detect_demand(ctx: DetectionContext) -> list[AlertDraft]:
    rule = ctx.config.demand
    drafts: list[AlertDraft] = []
    for h in ctx.demand.hospitals:
        d = h.current
        if not d.spike:
            continue
        tz = h.timezone
        ends = (
            f"; ends {fmt_local(h.spike_ends_at, tz)} if no new arrivals" if h.spike_ends_at else ""
        )
        drafts.append(
            AlertDraft(
                alert_id=f"{RuleCode.DEMAND_SPIKE.value}:hospital:{h.hospital_id}",
                rule_code=RuleCode.DEMAND_SPIKE,
                rule_name="Demand spike (trailing 60-minute consults above hourly p90)",
                rule_source="challenge_brief",
                rule_reference=rule.reference,
                category=AlertCategory.DEMAND,
                severity=rule.alert_severity,
                severity_reason=(
                    f"{d.arrivals} arrivals > p90 {d.baseline_p90:g} (alert severity is an "
                    "assumption)"
                ),
                title=f"{h.hospital_name}: demand spike ({d.arrivals} consults in 60 min)",
                summary=(
                    f"The previous 60-minute consultation volume at {h.hospital_name} "
                    f"({d.arrivals}) "
                    f"exceeds its p90 baseline ({d.baseline_p90:g}) for {d.local_hour_label}; the "
                    f"coverage requirement rises by {rule.requirement_increase}{ends}."
                ),
                action=RecommendedAction.MONITOR,
                action_reason=(
                    "The spike raises required coverage; act on any resulting coverage gap."
                ),
                category_rank=5,
                category_reason="demand above baseline",
                urgency=d.arrivals / d.baseline_p90 if d.baseline_p90 else float(d.arrivals),
                urgency_reason=f"{d.arrivals} arrivals vs p90 {d.baseline_p90:g}",
                affected=d.arrivals,
                hospital_id=h.hospital_id,
                condition_since=None,
                evidence=[
                    AlertEvidence(label="Comparison", value=d.comparison),
                    AlertEvidence(label="Consults in window", value=", ".join(d.consult_ids)),
                    AlertEvidence(
                        label="Baseline",
                        value=(
                            f"mean {d.baseline_mean:g}, p90 {d.baseline_p90:g} "
                            f"({d.baseline_day_type or 'any day'})"
                        ),
                    ),
                ],
            )
        )
    return drafts


def _open_consults_at(ctx: DetectionContext, hospital_id: str) -> list[str]:
    return [
        c.consult_id for c in ctx.state.consultations if c.is_open and c.hospital_id == hospital_id
    ]


def detect_coverage(ctx: DetectionContext) -> list[AlertDraft]:
    rule = ctx.config.coverage
    drafts: list[AlertDraft] = []
    horizon = ctx.coverage.horizon_minutes
    for hc in ctx.coverage.hospitals:
        m = hc.metrics
        if not hc.requirement_defined or m.first_shortfall_at is None:
            continue
        tz = hc.timezone
        open_ids = _open_consults_at(ctx, hc.hospital_id)
        counted = [c.display_name for c in hc.contributors if c.status == "counted"]
        excluded = [
            f"{c.display_name}: {c.reasons[0]}" for c in hc.contributors if c.status == "excluded"
        ]
        evidence = [
            AlertEvidence(
                label="Required vs available now",
                value=f"{m.required_now} required, {m.available_now} available",
                at=ctx.as_of,
            ),
            AlertEvidence(
                label="Projected deficit",
                value=(
                    f"{m.deficit_physician_minutes:g} physician-minutes over {horizon} min "
                    f"({m.deficit_physician_minutes_if_uncertain_excluded:g} counting only "
                    "confirmed coverage)"
                ),
            ),
            AlertEvidence(label="Counted now", value=", ".join(counted) or "none"),
            *[AlertEvidence(label="Explanation", value=e) for e in hc.explanations[:6]],
        ]
        if excluded:
            evidence.append(AlertEvidence(label="Excluded", value="; ".join(excluded)))
        if m.deficit_now:
            drafts.append(
                AlertDraft(
                    alert_id=f"{RuleCode.COVERAGE_GAP_NOW.value}:hospital:{hc.hospital_id}",
                    rule_code=RuleCode.COVERAGE_GAP_NOW,
                    rule_name="Coverage below requirement now",
                    rule_source="challenge_brief",
                    rule_reference=rule.reference,
                    category=AlertCategory.COVERAGE,
                    severity=rule.current_gap_severity,
                    severity_reason=(
                        f"deficit of {m.deficit_now} physician(s) now (severity level is an "
                        "assumption)"
                    ),
                    title=(
                        f"{hc.hospital_name}: coverage gap now ({m.available_now}/{m.required_now})"
                    ),
                    summary=hc.explanations[0],
                    action=RecommendedAction.PROPOSE_SPLIT_SHIFT,
                    action_reason="Credentialed capacity is below the required level; the brief's "
                    "intervention for a gap is a split-shift offer (requires clinical lead "
                    "approval).",
                    category_rank=1,
                    category_reason="current coverage deficit",
                    urgency=m.deficit_physician_minutes / horizon,
                    urgency_reason=f"{m.deficit_physician_minutes:g} physician-minutes of deficit",
                    affected=max(1, len(open_ids)),
                    hospital_id=hc.hospital_id,
                    condition_since=ctx.as_of,
                    impact_at=ctx.as_of,
                    minutes_to_impact=0.0,
                    evidence=evidence,
                    assumptions=list(ctx.coverage.assumptions),
                )
            )
        else:
            minutes = m.minutes_until_shortfall or 0.0
            drafts.append(
                AlertDraft(
                    alert_id=f"{RuleCode.COVERAGE_GAP_PROJECTED.value}:hospital:{hc.hospital_id}",
                    rule_code=RuleCode.COVERAGE_GAP_PROJECTED,
                    rule_name="Projected coverage gap",
                    rule_source="challenge_brief",
                    rule_reference=rule.reference,
                    category=AlertCategory.COVERAGE,
                    severity=rule.projected_gap_severity,
                    severity_reason=(
                        f"gap projected at {fmt_local(m.first_shortfall_at, tz)} "
                        "(severity level is an assumption)"
                    ),
                    title=(
                        f"{hc.hospital_name}: coverage gap at {fmt_local(m.first_shortfall_at, tz)}"
                    ),
                    summary=hc.explanations[0],
                    action=RecommendedAction.PROPOSE_SPLIT_SHIFT,
                    action_reason=(
                        "A split-shift offer could fill the projected gap (requires approval)."
                    ),
                    category_rank=3,
                    category_reason="projected coverage deficit",
                    urgency=1 - minutes / horizon,
                    urgency_reason=f"gap starts in {minutes:.0f} min",
                    affected=max(1, len(open_ids)),
                    hospital_id=hc.hospital_id,
                    condition_since=None,
                    impact_at=m.first_shortfall_at,
                    minutes_to_impact=minutes,
                    evidence=evidence,
                    assumptions=list(ctx.coverage.assumptions),
                )
            )
    return drafts


DETECTORS = (
    detect_stage_standards,
    detect_assigned_unavailable,
    detect_routing_failures,
    detect_open_notes,
    detect_signals,
    detect_demand,
    detect_coverage,
)


def detect_all(ctx: DetectionContext) -> list[AlertDraft]:
    drafts: list[AlertDraft] = []
    for detector in DETECTORS:
        drafts.extend(detector(ctx))
    return drafts


def context(
    state: OperationalState,
    config: RiskConfig,
    coverage: CoverageReport,
    demand: DemandReport,
    hospitals: Sequence[Hospital],
) -> DetectionContext:
    return DetectionContext(
        state=state,
        config=config,
        coverage=coverage,
        demand=demand,
        hospitals={h.id: h for h in hospitals},
        physicians={p.physician_id: p for p in state.physicians},
        coverage_by_hospital={h.hospital_id: h for h in coverage.hospitals},
    )
