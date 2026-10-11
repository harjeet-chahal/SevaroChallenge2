"""Phase 5 workflow: Detect -> Decide -> Act, with a person approving every offer.

The backend is authoritative for workflow state. Every mutation:

1. checks the simulated caller role (``X-Demo-Role`` — a demo stand-in, **not**
   production authentication);
2. runs inside one serialized write transaction (a process lock plus SQLite
   ``BEGIN IMMEDIATE``), so two requests can never both see "still open" and both act;
3. first applies everything that became due on the simulation clock (offer expiry,
   activation, shift end), so an expired offer can never be accepted;
4. re-derives and re-validates against the *current* data (eligibility, offer limits,
   remaining coverage need) instead of trusting what a client saw earlier;
5. moves state only through the validated state machine and writes an audit record for
   every transition, rejected attempt and conflict.

All times are simulation times from the existing simulation clock. Wall-clock time is
recorded alongside (``recorded_at``) for audit only.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError, PermissionDeniedError
from app.core.time import utc_now
from app.db.models import ApprovalRecord, InterventionRecord, OfferRecord, OfferResponseRecord
from app.engines.analysis import OperationalAnalysis
from app.engines.coverage_prediction import HospitalCoverageModel, Window
from app.engines.event_processing import normalize_event
from app.engines.interventions import (
    INITIAL_STATUS,
    WorkflowPolicy,
    can_transition,
    find_disallowed,
    offer_reason,
    split_shift_status_from_offers,
)
from app.engines.optimization import ForecastConfig, simulate_intervention
from app.engines.optimization.routing.problem import network_timezone
from app.engines.optimization.split_shift import (
    Candidate,
    Option,
    PlanningContext,
    StaffingInternals,
    build_planning_context,
    describe_option,
    offer_checks,
    proposed_window,
    protection_for,
    seed_count,
    seed_peers,
    staffing_baseline,
    trap_analysis,
)
from app.engines.optimization.split_shift.ranking import cost_estimate, money, paid_minutes
from app.engines.timeline import fmt_local
from app.repositories import EventRepository, ReferenceRepository, SystemRepository
from app.repositories.workflow import WorkflowRepository
from app.schemas.alert import Alert, RuleCode
from app.schemas.audit import AuditEntry, AuditPage
from app.schemas.common import ActorRef, UserRole
from app.schemas.event import EventSource, KnownEventType
from app.schemas.hospital import Hospital, HospitalRef
from app.schemas.intervention import (
    TERMINAL_STATUSES,
    AlternativeAction,
    ApprovalView,
    CancelRequest,
    CoverageImpact,
    DecisionRequest,
    EscalationDetail,
    HospitalImpact,
    Intervention,
    InterventionCreate,
    InterventionImpact,
    InterventionPage,
    InterventionPreview,
    InterventionRecommendation,
    InterventionStatus,
    InterventionType,
    OfferPlanItem,
    ProblemSnapshot,
    ReassignmentPlan,
    ResolveRequest,
    WorkflowSummary,
)
from app.schemas.offer import (
    ExpireResult,
    OfferPage,
    OfferRecipient,
    OfferResponseRequest,
    OfferResponseResult,
    OfferStatus,
    PhysicianOfferView,
    ShiftOffer,
)
from app.schemas.offer import OfferResponseRecord as ResponseView
from app.schemas.staffing import CostComparison, CostEstimate, NeedRanking, PlanCost, TrapAnalysis
from app.schemas.whatif import AssignConsultAction
from app.services.analysis import AnalysisCache, AnalysisService
from app.services.optimization import OptimizationService
from app.services.simulation import SimulationService
from app.services.workflow_records import (
    SYSTEM_ACTOR,
    bump_data_version,
    data_version,
    transition_intervention,
    transition_offer,
    write_audit,
)

S = InterventionStatus
T = InterventionType
O = OfferStatus  # noqa: E741

_WRITE_LOCK = threading.RLock()
"""Serializes workflow writes in this process (FastAPI runs sync routes in threads)."""

DEMO_AUTH_NOTE = (
    "Simulated demo roles (X-Demo-Role / X-Demo-Actor-Id headers). This is not production "
    "authentication."
)

STATUS_LABELS = {
    O.SENT: "Awaiting your reply",
    O.ACCEPTED: "Accepted — preparing to come online",
    O.ACTIVE: "Online — split shift in progress",
    O.COMPLETED: "Completed",
    O.DECLINED: "Declined",
    O.EXPIRED: "Expired — no reply in time",
    O.WITHDRAWN: "Withdrawn",
    O.REDUNDANT: "Not needed — coverage already secured",
    O.CANCELLED: "Cancelled",
}


def require_role(actor: ActorRef, *roles: UserRole, action: str) -> None:
    if actor.role not in roles:
        raise PermissionDeniedError(
            f"Role '{actor.role.value}' may not {action}.",
            details={"allowed_roles": [r.value for r in roles], "note": DEMO_AUTH_NOTE},
        )


def with_default_identity(actor: ActorRef) -> ActorRef:
    if actor.actor_id:
        return actor
    default = {
        UserRole.COORDINATOR: "demo-coordinator",
        UserRole.CLINICAL_LEAD: "demo-clinical-lead",
    }.get(actor.role)
    return actor.model_copy(update={"actor_id": default}) if default else actor


GAP_RULES = {RuleCode.COVERAGE_GAP_NOW.value, RuleCode.COVERAGE_GAP_PROJECTED.value}


MAX_SWEEP_PASSES = 5
"""An offer moves at most sent -> accepted -> active -> completed, so a few passes suffice."""


def same_problem(a: str, b: str) -> bool:
    """Alert ids that name the same problem: identical, or a hospital's projected and
    current coverage-gap alerts (the id changes when the projected gap begins)."""
    if a == b:
        return True
    rule_a, _, entity_a = a.partition(":")
    rule_b, _, entity_b = b.partition(":")
    return rule_a in GAP_RULES and rule_b in GAP_RULES and entity_a == entity_b


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def slide_to_now(item: dict[str, Any], now: datetime) -> tuple[dict[str, Any], str | None]:
    """A planned offer whose start has passed (approval or sending came later) starts now
    instead and still ends as planned; every rule is re-checked on the result. Returns the
    item unchanged (and no note) when its start has not passed."""
    start = datetime.fromisoformat(item["start_at"])
    if start >= now:
        return item, None
    end = datetime.fromisoformat(item["end_at"])
    minutes = max(0, int((end - now).total_seconds() // 60))
    moved = end - timedelta(minutes=minutes)  # whole minutes, still ending as planned
    online = moved + timedelta(minutes=item["minutes_to_online"])
    note = (
        f"{item['display_name']}'s offer was to start {_iso(start)}, which has passed: it now "
        f"starts {_iso(moved)} ({minutes} min) and still ends {_iso(end)}."
    )
    return {
        **item,
        "start_at": _iso(moved),
        "duration_minutes": minutes,
        "expected_online_at": _iso(online),
        "coverage_minutes": minutes - item["minutes_to_online"],
    }, note


def offer_window(o: OfferRecord, now: datetime) -> tuple[datetime, datetime]:
    """When an offer's physician would be (or is) counted: from going online to the end."""
    online = o.activated_at or o.expected_online_at
    if online is None:
        online = max(o.start_at, now) + timedelta(minutes=o.minutes_to_online)
    return online, o.end_at


def deficit_between(model: HospitalCoverageModel, start: datetime, end: datetime) -> float:
    """Deficit physician-minutes the model forecasts inside [start, end)."""
    total = 0.0
    for a, b, e in model.evaluations():
        lo, hi = max(a, start), min(b, end)
        if hi > lo:
            total += (e.deficit or 0) * (hi - lo).total_seconds() / 60
    return round(total, 4)


@dataclass
class _Draft:
    fields: dict[str, Any]
    blocking: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class WorkflowService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        analysis_cache: AnalysisCache,
        optimization_cache: AnalysisCache,
    ) -> None:
        self.session = session
        self.settings = settings
        self.analysis_cache = analysis_cache
        self.optimization_cache = optimization_cache
        self.repo = WorkflowRepository(session)
        self.system = SystemRepository(session)
        self.sim = SimulationService(session, settings)
        self.analyses = AnalysisService(session, settings, analysis_cache)
        self.optimizer = OptimizationService(session, settings, analysis_cache, optimization_cache)
        self.policy = WorkflowPolicy()
        self._hospital_cache: dict[str, Hospital] | None = None

    # ------------------------------------------------------------------ plumbing --

    @contextmanager
    def _write(self) -> Iterator[None]:
        with _WRITE_LOCK:
            self.session.rollback()
            connection = self.session.connection()
            if connection.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            try:
                yield
                self.session.commit()
            except BaseException:
                self.session.rollback()
                # Results computed from uncommitted state must never be served later.
                self.analysis_cache.clear()
                self.optimization_cache.clear()
                raise

    def _now(self) -> datetime:
        return self.sim.require_current_time()

    def _import_id(self) -> str | None:
        state = self.system.get_simulation_state()
        return state.active_import_id if state else None

    def _record(self, intervention_id: str) -> InterventionRecord:
        rec = self.repo.get_intervention(intervention_id)
        if rec is None:
            raise NotFoundError(f"Intervention {intervention_id} not found")
        return rec

    def _offer(self, offer_id: str) -> OfferRecord:
        offer = self.repo.get_offer(offer_id)
        if offer is None:
            raise NotFoundError(f"Offer {offer_id} not found")
        return offer

    def _analysis(self) -> OperationalAnalysis:
        return self.analyses.analysis()

    def _hospitals(self) -> dict[str, Hospital]:
        if self._hospital_cache is None:
            reference = ReferenceRepository(self.session).load()
            self._hospital_cache = {h.id: h for h in reference.hospitals}
        return self._hospital_cache

    def _hospital_zone(self, analysis: OperationalAnalysis, hospital_ids: Sequence[str]) -> str:
        zones = {h.id: h.timezone for h in analysis.state.hospitals}
        for hid in hospital_ids:
            if hid in zones:
                return zones[hid]
        return analysis.state.hospitals[0].timezone if analysis.state.hospitals else "UTC"

    # ---------------------------------------------------------------- the clock --

    def sweep(self) -> ExpireResult:
        """Apply everything due on the simulation clock: offer expiry (10 min after
        sending), automatic activation at the expected online time, and shift end."""
        if not self.sim.dataset_loaded():
            return ExpireResult(
                simulation_time=utc_now(),
                expired_offer_ids=[],
                activated_offer_ids=[],
                completed_offer_ids=[],
            )
        now = self._now()
        if not self._due(now):
            return ExpireResult(
                simulation_time=now,
                expired_offer_ids=[],
                activated_offer_ids=[],
                completed_offer_ids=[],
            )
        with self._write():
            return self._sweep_locked()

    def _due(self, now: datetime) -> list[tuple[datetime, str, OfferRecord]]:
        due: list[tuple[datetime, str, OfferRecord]] = []
        for o in self.repo.offers_with_status([O.SENT, O.ACCEPTED, O.ACTIVE]):
            status = O(o.status)
            if status is O.SENT and o.expires_at <= now:
                due.append((o.expires_at, "expire", o))
            elif status is O.ACCEPTED and o.expected_online_at is not None:
                if self.policy.auto_activate_at_expected_online and o.expected_online_at <= now:
                    due.append((max(o.expected_online_at, o.start_at), "activate", o))
                elif o.end_at <= now:
                    due.append((o.end_at, "lapse", o))
            elif status is O.ACTIVE and o.end_at <= now:
                due.append((o.end_at, "complete", o))
        return sorted(due, key=lambda x: (x[0], x[2].id))

    def _sweep_locked(self) -> ExpireResult:
        now = self._now()
        result = ExpireResult(
            simulation_time=now,
            expired_offer_ids=[],
            activated_offer_ids=[],
            completed_offer_ids=[],
        )
        touched: set[str] = set()
        # Several steps can fall inside one clock move (e.g. activation, then the shift's
        # end): apply them pass by pass, each at its own simulated time, until none is due.
        for _ in range(MAX_SWEEP_PASSES):
            due = self._due(now)
            if not due:
                break
            self._apply_due(due, result, touched)
            for iid in sorted(touched):
                rec = self.repo.get_intervention(iid)
                if rec is not None:
                    self._sync_split_status(rec, now, SYSTEM_ACTOR)
        return result

    def _apply_due(
        self,
        due: list[tuple[datetime, str, OfferRecord]],
        result: ExpireResult,
        touched: set[str],
    ) -> None:
        for at, kind, offer in due:
            touched.add(offer.intervention_id)
            if kind == "expire":
                transition_offer(
                    self.session,
                    offer,
                    O.EXPIRED,
                    at=at,
                    actor=SYSTEM_ACTOR,
                    action="offer_expired",
                    summary=(
                        f"Offer {offer.id} to {offer.display_name} expired at "
                        f"{at.isoformat()}: no reply within {self.policy.offer_ttl_minutes} "
                        "simulated minutes."
                    ),
                    reason="no reply before the offer expired",
                    details={"sent_at": offer.sent_at, "expires_at": offer.expires_at},
                )
                result.expired_offer_ids.append(offer.id)
            elif kind == "activate":
                self._activate(offer, at=at, actor=SYSTEM_ACTOR, source="simulation_policy")
                result.activated_offer_ids.append(offer.id)
            elif kind == "lapse":
                offer.ended_at = at
                transition_offer(
                    self.session,
                    offer,
                    O.CANCELLED,
                    at=at,
                    actor=SYSTEM_ACTOR,
                    action="split_shift_lapsed",
                    summary=f"Offer {offer.id}: the shift ended before {offer.display_name} "
                    "was activated.",
                    reason="never activated before the shift ended",
                )
                bump_data_version(self.session)
            else:
                offer.ended_at = at
                transition_offer(
                    self.session,
                    offer,
                    O.COMPLETED,
                    at=at,
                    actor=SYSTEM_ACTOR,
                    action="split_shift_completed",
                    summary=f"{offer.display_name}'s split shift ({offer.id}) ended at "
                    f"{at.isoformat()}; back off shift.",
                )
                bump_data_version(self.session)
                result.completed_offer_ids.append(offer.id)

    # ------------------------------------------------------------- proposals --

    def preview(self, body: InterventionCreate, actor: ActorRef) -> InterventionPreview:
        require_role(actor, UserRole.COORDINATOR, action="propose interventions")
        actor = with_default_identity(actor)
        self.sweep()
        draft = self._draft(body, actor)
        rec = InterventionRecord(**draft.fields)
        return InterventionPreview(
            valid=not draft.blocking,
            blocking_reasons=draft.blocking,
            warnings=draft.warnings,
            data_version=data_version(self.session),
            intervention=self._to_schema(rec, actor, offers=[]),
        )

    def propose(self, body: InterventionCreate, actor: ActorRef) -> Intervention:
        require_role(actor, UserRole.COORDINATOR, action="propose interventions")
        actor = with_default_identity(actor)
        with self._write():
            self._sweep_locked()
            draft = self._draft(body, actor)
            if draft.blocking:
                raise AppError(
                    "The proposal does not pass validation against the current data; "
                    "nothing was stored.",
                    code="proposal_invalid",
                    status_code=422,
                    details={
                        "blocking_reasons": draft.blocking,
                        "warnings": draft.warnings,
                        "data_version": data_version(self.session),
                    },
                )
            fields = {**draft.fields, "id": self.repo.next_intervention_id()}
            rec = InterventionRecord(**fields)
            self.session.add(rec)
            self.session.flush()
            kind = T(rec.type)
            details: dict[str, Any] = {
                "alert_id": rec.alert_id,
                "rationale": rec.rationale,
                "algorithm": rec.recommendation.get("algorithm"),
                "policy_version": rec.recommendation.get("policy_version"),
                "warnings": draft.warnings,
                "data_version": rec.created_data_version,
            }
            if kind is T.SPLIT_SHIFT:
                details["candidates_evaluated"] = [
                    {
                        "physician_id": c["physician_id"],
                        "eligible": c["eligible"],
                        "failed_rules": c["failed_rules"],
                        "summary": c["summary"],
                    }
                    for c in rec.candidates
                ]
                details["offer_plan"] = [
                    {
                        "physician_id": i["physician_id"],
                        "role": i["role"],
                        "start_at": i["start_at"],
                        "end_at": i["end_at"],
                        "hospital_ids": i["hospital_ids"],
                    }
                    for i in rec.offer_plan
                ]
                details["projected_impact"] = rec.impact
            elif kind is T.REASSIGN_CONSULT:
                details["reassignment"] = rec.reassignment
            else:
                details["escalation"] = rec.escalation
            write_audit(
                self.session,
                at=rec.proposed_at,
                actor=actor,
                action="intervention_proposed",
                summary=f"{actor.role.value} {actor.actor_id} proposed {rec.id}: {rec.title}.",
                entity_type="intervention",
                entity_id=rec.id,
                intervention_id=rec.id,
                to_status=rec.status,
                details=details,
            )
            if rec.status == S.PENDING_APPROVAL.value:
                write_audit(
                    self.session,
                    at=rec.proposed_at,
                    actor=actor,
                    action="approval_requested",
                    summary=f"{rec.id} is waiting for clinical-lead approval. No physician has "
                    "been contacted.",
                    entity_type="intervention",
                    entity_id=rec.id,
                    intervention_id=rec.id,
                    to_status=rec.status,
                )
            new_id = rec.id
        return self.get(new_id, actor)

    def _draft(self, body: InterventionCreate, actor: ActorRef) -> _Draft:
        analysis = self._analysis()
        now = analysis.state.as_of
        version = analysis.state.data_version
        warnings: list[str] = []
        if body.expected_data_version is not None and body.expected_data_version != version:
            warnings.append(
                f"The data changed since this view was loaded (version "
                f"{body.expected_data_version} → {version}); everything was re-validated "
                "against the current data."
            )
        alert = None
        if body.alert_id:
            alert = next((a for a in analysis.alerts.alerts if a.alert_id == body.alert_id), None)
            if alert is None:
                warnings.append(
                    f"Alert {body.alert_id} is no longer active at this simulation time."
                )
        base = {
            "type": body.type.value,
            "status": INITIAL_STATUS[body.type].value,
            "rationale": body.rationale,
            "dataset_import_id": self._import_id(),
            "alert_id": body.alert_id,
            "required_physicians": 1,
            "proposed_by_role": actor.role.value,
            "proposed_by_id": actor.actor_id,
            "proposed_at": now,
            "updated_at": now,
            "recorded_at": utc_now(),
            "created_data_version": version,
            "version": 1,
            "candidates": [],
            "offer_plan": [],
            "id": "PREVIEW",
        }
        if body.type is T.SPLIT_SHIFT:
            draft = self._draft_split_shift(body, analysis, alert)
        elif body.type is T.REASSIGN_CONSULT:
            draft = self._draft_reassignment(body, analysis, alert)
        else:
            draft = self._draft_escalation(body, analysis, alert)
        draft.fields = {**base, **draft.fields}
        draft.warnings = warnings + draft.warnings
        if alert is not None:
            for rec in self.repo.list_interventions(
                import_id=self._import_id(), types=[body.type.value]
            ):
                if (
                    rec.alert_id
                    and same_problem(rec.alert_id, alert.alert_id)
                    and S(rec.status) not in TERMINAL_STATUSES
                ):
                    draft.blocking.append(
                        f"This alert already has an open {body.type.value.replace('_', ' ')} "
                        f"({rec.id}, {rec.status.replace('_', ' ')})."
                    )
        return draft

    def _problem(
        self,
        analysis: OperationalAnalysis,
        alert: Alert | None,
        *,
        hospital_ids: Sequence[str] = (),
        consult_id: str | None = None,
        title: str | None = None,
        summary: str | None = None,
    ) -> ProblemSnapshot:
        state = analysis.state
        names = {h.id: h.name for h in state.hospitals}
        if alert is not None:
            hids = [alert.hospital_id] if alert.hospital_id else list(hospital_ids)
            consult = next(
                (c for c in state.consultations if c.consult_id == alert.consult_id), None
            )
            return ProblemSnapshot(
                alert_id=alert.alert_id,
                rule_code=alert.rule_code.value,
                title=alert.title,
                summary=alert.summary,
                severity=alert.severity,
                priority=alert.priority,
                hospital_ids=hids,
                hospital_names=[names.get(h, h) for h in hids],
                hospital_timezone=alert.hospital_timezone,
                consult_id=alert.consult_id,
                consult_type=consult.consult_type if consult else None,
                physician_id=alert.physician_id,
                physician_name=alert.physician_name,
                elapsed_seconds=alert.elapsed_seconds,
                warning_after_seconds=alert.warning_after_seconds,
                critical_after_seconds=alert.critical_after_seconds,
                impact_at=alert.impact_at,
                captured_at=state.as_of,
                data_version=state.data_version,
            )
        hids = list(hospital_ids)
        coverage = {h.hospital_id: h for h in analysis.coverage.hospitals}
        lines = []
        first = None
        for hid in hids:
            hc = coverage.get(hid)
            if hc is None:
                continue
            m = hc.metrics
            if m.first_shortfall_at is not None:
                first = m.first_shortfall_at if first is None else min(first, m.first_shortfall_at)
            lines.append(
                f"{hc.hospital_name}: {m.deficit_physician_minutes:g} deficit physician-minutes "
                f"in the next {analysis.coverage.horizon_minutes} min"
            )
        consult = next((c for c in state.consultations if c.consult_id == consult_id), None)
        return ProblemSnapshot(
            title=title or f"Coverage gap at {', '.join(names.get(h, h) for h in hids)}",
            summary=summary or ("; ".join(lines) or "Coordinator-identified problem."),
            hospital_ids=hids,
            hospital_names=[names.get(h, h) for h in hids],
            hospital_timezone=self._hospital_zone(analysis, hids) if hids else None,
            consult_id=consult_id,
            consult_type=consult.consult_type if consult else None,
            impact_at=first,
            captured_at=state.as_of,
            data_version=state.data_version,
        )

    def _coverage_impact(
        self,
        analysis: OperationalAnalysis,
        hospital_ids: Sequence[str],
        label: str,
        *,
        extra: Sequence[Window] = (),
        after: OperationalAnalysis | None = None,
        notes: Sequence[str] = (),
    ) -> CoverageImpact:
        """Deficit before/after over the dashboard horizon. ``extra`` = projected windows on
        the same model; ``after`` = a second analysis (e.g. after activation)."""
        rows: list[HospitalImpact] = []
        for hid in dict.fromkeys(hospital_ids):
            model = analysis.coverage_models.get(hid)
            if model is None:
                continue
            after_model = after.coverage_models.get(hid) if after is not None else model
            if after_model is None:
                continue
            before_evals = model.evaluations()
            after_evals = after_model.evaluations(extra if after is None else ())
            rows.append(
                HospitalImpact(
                    hospital_id=hid,
                    hospital_name=model.hospital.name,
                    deficit_before=round(model.deficit_physician_minutes(), 4),
                    deficit_after=round(
                        after_model.deficit_physician_minutes(extra if after is None else ()), 4
                    ),
                    shortfall_now_before=(before_evals[0][2].deficit or 0) if before_evals else 0,
                    shortfall_now_after=(after_evals[0][2].deficit or 0) if after_evals else 0,
                    first_shortfall_before=next(
                        (a for a, _, e in before_evals if (e.deficit or 0) > 0), None
                    ),
                    first_shortfall_after=next(
                        (a for a, _, e in after_evals if (e.deficit or 0) > 0), None
                    ),
                )
            )
        state = (after or analysis).state
        return CoverageImpact(
            label=label,
            horizon_minutes=analysis.coverage.horizon_minutes,
            hospitals=rows,
            total_before=round(sum(r.deficit_before for r in rows), 4),
            total_after=round(sum(r.deficit_after for r in rows), 4),
            computed_at=state.as_of,
            data_version=state.data_version,
            notes=list(notes),
        )

    def _option_for(
        self,
        cand: Candidate,
        ctx: PlanningContext,
        options: Sequence[Option],
        need: Sequence[str],
        recommended: dict[str, Any],
        *,
        start: datetime | None = None,
        minutes: int | None = None,
    ) -> tuple[Option | None, list[str]]:
        pid = cand.physician_id
        if start is not None or minutes is not None:
            rec = recommended.get(pid)
            start = start or cand.earliest_start or ctx.as_of
            minutes = minutes or (rec.offer_minutes if rec else None) or 240
            online = timedelta(minutes=cand.online_minutes)
            option = Option(
                index=-1,
                physician_id=pid,
                name=cand.state.display_name,
                start=start,
                minutes=minutes,
                online_at=start + online,
                end=start + timedelta(minutes=minutes),
                hospitals=cand.scope,
            )
            problems = [] if start >= ctx.as_of else ["the requested start is in the past"]
            return option, problems
        rec = recommended.get(pid)
        if rec is not None:
            for o in options:
                if (
                    o.physician_id == pid
                    and o.start == rec.offer_start
                    and o.minutes == (rec.offer_minutes)
                ):
                    return o, []
        mine = [o for o in options if o.physician_id == pid]
        if not mine:
            return None, ["no offer length/start passes every rule"]

        def score(o: Option) -> tuple:
            reduction = 0.0
            for hid in need:
                if hid in o.hospitals and hid in ctx.models:
                    reduction += ctx.base_deficit[hid] - ctx.models[hid].deficit_physician_minutes(
                        [proposed_window(o)]
                    )
            return (round(reduction, 4), -o.online_at.timestamp(), -o.minutes)

        return max(mine, key=score), []

    def _draft_split_shift(
        self, body: InterventionCreate, analysis: OperationalAnalysis, alert: Alert | None
    ) -> _Draft:
        staffing, internals = self.optimizer.staffing_with_internals(analysis)
        ctx = internals.ctx
        cands = {c.physician_id: c for c in internals.candidates}
        recommended = {r.physician_id: r for r in staffing.recommendations}
        names = {h.id: h.name for h in analysis.state.hospitals}
        blocking: list[str] = []
        warnings: list[str] = []

        requested = list(dict.fromkeys(body.physician_ids))
        need = list(dict.fromkeys(body.hospital_ids))
        if not need and alert is not None and alert.hospital_id:
            need = [alert.hospital_id]
        if not need and requested and requested[0] in recommended:
            need = list(recommended[requested[0]].hospital_ids)
        if not need and staffing.recommendations:
            need = list(staffing.recommendations[0].hospital_ids)
        if not need:
            need = list(staffing.gap_hospital_ids)
        unknown = [h for h in need if h not in names]
        if unknown:
            blocking.append(f"Unknown hospital(s): {', '.join(unknown)}.")
        gap_need = [h for h in need if h in ctx.gap_hospitals]
        if not gap_need:
            blocking.append(
                f"No coverage gap at {', '.join(names.get(h, h) for h in need) or 'any hospital'} "
                f"in the next {ctx.lookahead_minutes} min (counting accepted shifts): a split "
                "shift is not needed. Monitor, or escalate if the problem is not about staffing."
            )

        if not requested:
            primary = next(
                (
                    r.physician_id
                    for r in staffing.recommendations
                    if set(r.hospital_ids) & set(need)
                ),
                None,
            )
            if primary is None:
                eligible = [
                    c
                    for c in internals.candidates
                    if c.eligibility.eligible and set(c.scope) & set(need)
                ]
                primary = eligible[0].physician_id if eligible else None
            if primary is None and gap_need:
                reasons = [
                    f"{c.state.display_name}: {c.eligibility.summary}"
                    for c in internals.candidates
                    if set(c.state.credentialed_hospital_ids) & set(need)
                ] or ["no off-shift physician is credentialed at these hospitals"]
                blocking.append(
                    "No off-shift physician can be asked under the rules — escalate instead of "
                    "bending a rule. " + " ".join(reasons)
                )
            elif primary is not None:
                requested = [primary]
        if len(requested) - 1 > self.policy.max_backup_offers:
            blocking.append(f"At most {self.policy.max_backup_offers} backup physicians.")

        plan: list[OfferPlanItem] = []
        primary_option: Option | None = None
        primary_cand: Candidate | None = None
        for index, pid in enumerate(requested):
            cand = cands.get(pid)
            if cand is None:
                blocking.append(f"{pid} is not on the off-shift roster.")
                continue
            name = cand.state.display_name
            if not cand.eligibility.eligible:
                failed = [c for c in cand.eligibility.checks if not c.passed]
                blocking.append(
                    f"{name} cannot be asked: "
                    + "; ".join(f"{c.label}: {c.message}" for c in failed)
                )
                continue
            if not set(cand.scope) & set(need):
                blocking.append(
                    f"{name} is not credentialed at {', '.join(names.get(h, h) for h in need)}."
                )
                continue
            option, problems = self._option_for(
                cand,
                ctx,
                internals.options,
                need,
                recommended,
                start=body.start_at if index == 0 else None,
                minutes=body.duration_minutes if index == 0 else None,
            )
            if option is None:
                blocking.append(f"{name}: " + "; ".join(problems))
                continue
            checks = offer_checks(
                cand.state,
                cand.profile,
                option.start,
                option.minutes,
                option.hospitals,
                ctx,
                cand.online_minutes,
                cand.eligibility.online_time_assumed,
            )
            failed = [c for c in checks if not c.passed]
            if failed or problems:
                blocking.append(
                    f"{name}'s offer {fmt_local(option.start, ctx.tz_for(option.hospitals))} "
                    f"({option.minutes} min) fails: "
                    + "; ".join([*problems, *(f"{c.label}: {c.message}" for c in failed)])
                )
            described = describe_option(ctx, cand, option, option.hospitals)
            plan.append(
                OfferPlanItem(
                    physician_id=pid,
                    display_name=name,
                    role="primary" if index == 0 else "backup",
                    hospital_ids=list(option.hospitals),
                    hospital_names=[names.get(h, h) for h in option.hospitals],
                    start_at=option.start,
                    end_at=option.end,
                    duration_minutes=option.minutes,
                    minutes_to_online=cand.online_minutes,
                    online_time_assumed=cand.eligibility.online_time_assumed,
                    expected_online_at=option.online_at,
                    coverage_minutes=option.minutes - cand.online_minutes,
                    routing_scope_hospital_ids=described.protection.routing_scope_hospital_ids,
                    excluded_credentialed_hospital_ids=(
                        described.protection.excluded_credentialed_hospital_ids
                    ),
                    seeded_consult_count=described.protection.seeded_consult_count,
                    protection_rationale=described.protection.rationale,
                    eligible=not failed and not problems,
                    checks=checks,
                    projected_effects=described.effects,
                    voluntary=described.voluntary,
                    cost=described.cost,
                )
            )
            if index == 0:
                primary_option, primary_cand = option, cand

        if primary_option is not None and primary_cand is not None and gap_need:
            remaining = self._need_during(
                primary_option.hospitals,
                primary_option.start,
                primary_option.end,
                ctx.as_of,
                primary_cand.online_minutes,
            )
            if remaining <= 0:
                accepted = [
                    o
                    for o in self.repo.offers_with_status([O.ACCEPTED, O.ACTIVE])
                    if set(o.routing_scope or o.hospital_ids) & set(primary_option.hospitals)
                ]
                who = ", ".join(o.display_name for o in accepted)
                blocking.append(
                    f"Coverage at {', '.join(names.get(h, h) for h in primary_option.hospitals)} "
                    "during this shift is already secured"
                    + (f" by accepted split shift(s) ({who})" if who else "")
                    + ": it would not cover any remaining deficit."
                )

        open_plans = [
            rec
            for rec in self.repo.list_interventions(
                import_id=self._import_id(), types=[T.SPLIT_SHIFT.value]
            )
            if S(rec.status) not in TERMINAL_STATUSES
        ]
        for rec in open_plans:
            planned = {i["physician_id"] for i in rec.offer_plan}
            clash = [p.display_name for p in plan if p.physician_id in planned]
            if clash:
                blocking.append(
                    f"{', '.join(clash)} already in open staffing request {rec.id} "
                    f"({rec.status.replace('_', ' ')})."
                )
            elif set(rec.hospital_ids) & set(need):
                warnings.append(
                    f"Open staffing request {rec.id} also targets "
                    f"{', '.join(names.get(h, h) for h in set(rec.hospital_ids) & set(need))}; "
                    "acceptances are reconciled against the remaining need."
                )

        primary_desc = None
        trap: TrapAnalysis | None = None
        impact = None
        if primary_option is not None and primary_cand is not None:
            primary_desc = describe_option(
                ctx, primary_cand, primary_option, primary_option.hospitals
            )
            trap = (
                staffing.trap
                if staffing.trap is not None
                and staffing.trap.physician_id == primary_cand.physician_id
                else trap_analysis(ctx, primary_option, primary_desc.protection)
            )
            impact = self._coverage_impact(
                analysis,
                list(dict.fromkeys([*need, *primary_option.hospitals])),
                "Projected if the primary physician accepts — not confirmed coverage",
                extra=[proposed_window(primary_option)],
                notes=[
                    f"Modeled from schedules, credentials and signals over the next "
                    f"{analysis.coverage.horizon_minutes} min; coverage starts after the time to "
                    "come online.",
                    "Wait-time effects are not modeled.",
                ],
            )

        ranking = internals.rank(need)
        primary_entry = next(
            (e for e in ranking.entries if plan and e.physician_id == plan[0].physician_id), None
        )
        why: list[str] = []
        if primary_entry is not None and primary_entry.rank is not None:
            why.append(
                f"Ranked #{primary_entry.rank} of "
                f"{sum(e.rank is not None for e in ranking.entries)} eligible for this need"
                + (
                    f" (#{primary_entry.rank_without_voluntary} without voluntary availability)."
                    if primary_entry.movement
                    else "."
                )
            )
        if primary_desc is not None:
            why.extend(primary_desc.explanation)
        why.extend(staffing.explanations)
        backups = [p.display_name for p in plan if p.role == "backup"]
        if backups:
            why.append(
                f"Backup offer(s) to {', '.join(backups)}: offers go out together; the first "
                "binding acceptance fills the need and the others are withdrawn."
            )
        other_eligible = [
            c.state.display_name
            for c in internals.candidates
            if c.eligibility.eligible and c.physician_id not in requested
        ]
        tz = ctx.tz_for(primary_option.hospitals) if primary_option else ctx.tz
        uncertainty = [
            "Coverage figures are modeled, not measured.",
            *(
                [f"{primary_cand.state.display_name}'s time to come online is assumed."]
                if primary_cand and primary_cand.eligibility.online_time_assumed
                else []
            ),
            "The physician may decline or not reply; the offer expires 10 min after sending.",
        ]
        restrictions = [
            "Needs clinical-lead approval before any physician is contacted.",
            "At most one open offer per physician and 3 offers per rolling 7 days.",
            "Offers expire 10 simulated minutes after sending.",
        ]
        if primary_desc is not None:
            restrictions.append(
                "Routing restricted to "
                f"{', '.join(primary_desc.protection.routing_scope_hospital_ids)} while on the "
                "split shift (trap protection)."
            )
        alternatives = [
            AlternativeAction(
                type=T.ESCALATION,
                label="Escalate to the clinical lead",
                available=True,
                reason="If no offer is accepted in time, or a decision outside the rules is "
                "needed.",
            ),
            AlternativeAction(
                type=T.REASSIGN_CONSULT,
                label="Reassign a waiting consult",
                available=bool(alert and alert.consult_id),
                reason="Moves one consult; does not add coverage."
                if alert and alert.consult_id
                else "This is a staffing gap, not a single consult.",
            ),
            AlternativeAction(
                type="monitor",
                label="Monitor",
                available=True,
                reason="Only if the gap is short or uncertain; the forecast is re-run on every "
                "new event.",
            ),
        ]
        if other_eligible:
            alternatives.append(
                AlternativeAction(
                    type=T.SPLIT_SHIFT,
                    label=f"Offer to another eligible physician ({', '.join(other_eligible)})",
                    available=True,
                    reason="Eligible, but ranked lower for this need (coverage, voluntary "
                    "availability, cost, online time; see the ranking); can be added as a backup.",
                )
            )
        in_plan = primary_cand is not None and primary_cand.physician_id in recommended
        recommendation = InterventionRecommendation(
            summary=(
                f"Offer {primary_option.name} a split shift {fmt_local(primary_option.start, tz)}–"
                f"{fmt_local(primary_option.end, tz)} for "
                f"{', '.join(names.get(h, h) for h in primary_option.hospitals)}"
                if primary_option
                else "No valid split-shift offer for this need"
            ),
            why=why,
            algorithm=(
                f"OR-Tools CP-SAT split-shift staffing ({staffing.solver.status}); every rule "
                "re-checked for this exact offer"
                if in_plan
                else "Coordinator-selected eligible physician; best valid offer option for this "
                "need; every rule re-checked for this exact offer"
            ),
            policy_version=f"{staffing.policy_version} / {self.policy.policy_version}",
            solver_status=staffing.solver.status,
            alternatives=alternatives,
            uncertainty=uncertainty,
            restrictions=restrictions,
            approver_role="clinical_lead",
            ranking=ranking,
            cost=self._need_cost(ctx, internals, ranking, plan, need),
        )
        title = (
            f"Split shift: {plan[0].display_name} for {', '.join(names.get(h, h) for h in need)}"
            if plan
            else f"Split shift for {', '.join(names.get(h, h) for h in need)}"
        )
        peaks = [
            max((d for _, _, d in ctx.models[h].deficit_profile()), default=0)
            for h in need
            if h in ctx.models
        ]
        required = max(1, min(max(peaks, default=1), self.policy.max_backup_offers + 1))
        return _Draft(
            fields={
                "title": title,
                "hospital_ids": need,
                "required_physicians": required,
                "problem": self._problem(analysis, alert, hospital_ids=need).model_dump(
                    mode="json"
                ),
                "recommendation": recommendation.model_dump(mode="json"),
                "candidates": [c.model_dump(mode="json") for c in staffing.candidates],
                "offer_plan": [p.model_dump(mode="json") for p in plan],
                "impact": impact.model_dump(mode="json") if impact else None,
                "trap": trap.model_dump(mode="json") if trap else None,
            },
            blocking=blocking,
            warnings=warnings,
        )

    def _need_cost(
        self,
        ctx: PlanningContext,
        internals: StaffingInternals,
        ranking: NeedRanking,
        plan: list[OfferPlanItem],
        need: Sequence[str],
    ) -> PlanCost | None:
        """Estimated cost of the primary offer vs the other ranked physicians and the manual
        heuristic for this need, with one cost model (simulated, projected if accepted)."""
        primary = plan[0] if plan else None
        if primary is None or primary.cost is None:
            return None
        cfg = ctx.cfg
        recommended = primary.cost
        base = round(sum(ctx.base_deficit.get(h, 0.0) for h in need), 4)
        comparisons: list[CostComparison] = []

        def verdict(saving: float, delta: int) -> str:
            if saving > 0:
                return f"simulated saving {money(cfg, saving)} ({delta} fewer paid minutes)"
            if saving < 0:
                return f"the proposal costs {money(cfg, -saving)} more ({-delta} more paid minutes)"
            return "same paid time, no simulated saving"

        for entry in ranking.entries:
            if entry.rank is None or entry.cost is None:
                continue
            if entry.physician_id == primary.physician_id or len(comparisons) >= 3:
                continue
            saving = round(entry.cost.amount - recommended.amount, 2)
            delta = entry.cost.paid_minutes - recommended.paid_minutes
            label = f"#{entry.rank} {entry.display_name}"
            if entry.rank_without_voluntary == 1 and entry.movement < 0:
                label += " (first choice without voluntary availability)"
            comparisons.append(
                CostComparison(
                    label=label,
                    physician_names=[entry.display_name],
                    cost=entry.cost,
                    deficit_after=round(base - entry.coverage_physician_minutes, 4),
                    saving=saving,
                    explanation=f"{money(cfg, entry.cost.amount)} vs "
                    f"{money(cfg, recommended.amount)}: {verdict(saving, delta)}. Removes "
                    f"{entry.coverage_physician_minutes:g} vs "
                    f"{recommended.covered_physician_minutes:g} deficit physician-minutes.",
                )
            )
        options = [o for o in internals.options if set(o.hospitals) & set(need)]
        manual = staffing_baseline(ctx, options)[:1]
        if manual:
            o = manual[0]
            cand = next(c for c in internals.candidates if c.physician_id == o.physician_id)
            covered = round(
                sum(
                    ctx.base_deficit[h]
                    - ctx.models[h].deficit_physician_minutes([proposed_window(o)])
                    for h in need
                    if h in o.hospitals and h in ctx.models
                ),
                4,
            )
            cost = cost_estimate(cfg, paid_minutes(cfg, o.minutes, cand.online_minutes), covered)
            saving = round(cost.amount - recommended.amount, 2)
            comparisons.append(
                CostComparison(
                    label="Manual heuristic (earliest online, longest valid offer)",
                    physician_names=[o.name],
                    cost=cost,
                    deficit_after=round(base - covered, 4),
                    saving=saving,
                    explanation=f"{o.name} for {o.minutes} min: {money(cfg, cost.amount)} vs "
                    f"{money(cfg, recommended.amount)}: "
                    f"{verdict(saving, cost.paid_minutes - recommended.paid_minutes)}.",
                )
            )
        return PlanCost(
            recommended=recommended,
            comparisons=comparisons,
            assumptions=[
                f"Cost = paid offer minutes × {money(cfg, cfg.cost.hourly_rate)}/h, an "
                "illustrative rate; the same for every physician (volunteers are not assumed "
                "to cost less).",
                "Backup offers cost nothing unless accepted; only one acceptance binds per "
                "physician needed.",
                "Simulated until the shift is completed; the confirmed cost then appears on "
                "this intervention.",
            ],
        )

    def _confirmed_cost(
        self, rec: InterventionRecord, offers: list[OfferRecord]
    ) -> tuple[CostEstimate | None, list[CostComparison]]:
        """Cost from split shifts actually worked under this intervention (completed, or
        cancelled after going online), against each alternative's projected cost."""
        if rec.type != T.SPLIT_SHIFT.value:
            return None, []
        worked = [
            o
            for o in offers
            if o.ended_at is not None
            and o.activated_at is not None
            and o.status in (O.COMPLETED.value, O.CANCELLED.value)
        ]
        if not worked:
            return None, []
        cfg = self.optimizer.config()
        paid = sum(
            paid_minutes(
                cfg,
                max(0, int((o.ended_at - o.start_at).total_seconds() // 60)),  # type: ignore[operator]
                o.minutes_to_online,
            )
            for o in worked
        )
        plan = {i["physician_id"]: i for i in rec.offer_plan or []}
        covered = sum(
            (plan.get(o.physician_id, {}).get("cost") or {}).get("covered_physician_minutes", 0.0)
            for o in worked
        )
        confirmed = cost_estimate(
            cfg,
            paid,
            covered,
            basis="confirmed",
            note=f"{paid} paid min worked × {money(cfg, cfg.cost.hourly_rate)}/h from the "
            "completed shift (coverage figure as projected at proposal).",
        )
        stored = (rec.recommendation or {}).get("cost") or {}
        savings = []
        for c in stored.get("comparisons", []):
            alt = CostComparison.model_validate(c)
            saving = round(alt.cost.amount - confirmed.amount, 2)
            savings.append(
                alt.model_copy(
                    update={
                        "saving": saving,
                        "basis": "confirmed",
                        "explanation": f"Confirmed cost {money(cfg, confirmed.amount)} (completed "
                        f"shift) vs the projected {money(cfg, alt.cost.amount)} of {alt.label}: "
                        + (
                            f"saved {money(cfg, saving)}."
                            if saving > 0
                            else f"cost {money(cfg, -saving)} more."
                            if saving < 0
                            else "no difference."
                        ),
                    }
                )
            )
        return confirmed, savings

    def _draft_reassignment(
        self, body: InterventionCreate, analysis: OperationalAnalysis, alert: Alert | None
    ) -> _Draft:
        blocking: list[str] = []
        state = analysis.state
        names = {h.id: h.name for h in state.hospitals}
        people = {p.physician_id: p for p in state.physicians}
        consult_id = body.consult_id or (alert.consult_id if alert else None)
        consult = next((c for c in state.consultations if c.consult_id == consult_id), None)
        if consult_id is None:
            blocking.append("Choose the consult to reassign.")
        elif consult is None or not consult.is_open:
            blocking.append(f"{consult_id} is not an open consult at this simulation time.")
        dispatch = self.optimizer.dispatch_for(analysis)
        rec = next((r for r in dispatch.plan.recommendations if r.consult_id == consult_id), None)
        unassigned = next((u for u in dispatch.plan.unassigned if u.consult_id == consult_id), None)
        skipped = next((s for s in dispatch.skipped if s.consult_id == consult_id), None)
        target = body.target_physician_id or (rec.physician_id if rec else None)
        if rec is not None and rec.kind == "confirm_ringing" and target == rec.physician_id:
            blocking.append(
                f"The call is already ringing to {rec.physician_name}; nothing to move."
            )
        if target is None and consult is not None:
            why = (
                " ".join(unassigned.explanation)
                if unassigned
                else (skipped.reason if skipped else "no eligible physician")
            )
            blocking.append(
                f"No eligible on-shift physician can take {consult_id} now ({why}). Escalate to "
                "the clinical lead or request split-shift coverage."
            )
        checks = []
        allowed = False
        workload_note = None
        if target is not None and consult is not None:
            whatif = simulate_intervention(
                analysis,
                AssignConsultAction(consult_id=consult.consult_id, physician_id=target),
                ForecastConfig(self.optimizer.config()),
            )
            allowed = whatif.allowed
            if not allowed:
                blocking.extend(
                    f"{people[target].display_name if target in people else target}: {v.message}"
                    for v in whatif.violations
                )
            row = next((p for p in dispatch.physicians if p.physician_id == target), None)
            checks = row.checks if row else list(whatif.violations)
            if whatif.workload:
                w = whatif.workload
                workload_note = (
                    f"Consults this shift {w.consults_this_shift_before} → "
                    f"{w.consults_this_shift_after}; open {w.open_consults_before} → "
                    f"{w.open_consults_after}."
                )
        excluded = rec.excluded if rec else (unassigned.excluded if unassigned else [])
        current = consult.assigned_physician_id if consult else None
        plan = (
            ReassignmentPlan(
                consult_id=consult.consult_id,
                hospital_id=consult.hospital_id,
                hospital_name=names.get(consult.hospital_id or "", consult.hospital_id),
                consult_type=consult.consult_type,
                stage=consult.stage.value,
                current_physician_id=current,
                current_physician_name=people[current].display_name if current in people else None,
                target_physician_id=target,
                target_physician_name=people[target].display_name if target in people else target,
                eligible=allowed,
                checks=checks,
                excluded=excluded,
                alternatives=rec.alternatives if rec else [],
                workload_note=workload_note,
            )
            if consult is not None and target is not None
            else None
        )
        hospital_ids = [consult.hospital_id] if consult and consult.hospital_id else []
        why = list(rec.explanation) if rec and rec.physician_id == target else []
        if plan is not None and not why:
            why.append(
                f"Coordinator-selected physician; brief routing rules 1–2 checked for "
                f"{plan.target_physician_name}."
            )
        recommendation = InterventionRecommendation(
            summary=(
                f"Reassign {consult_id} from {plan.current_physician_name or 'unassigned'} to "
                f"{plan.target_physician_name}"
                if plan
                else f"Reassign {consult_id}"
            ),
            why=why,
            algorithm=(
                "OR-Tools min-cost flow dispatch (brief routing rules as hard constraints)"
                if rec and rec.physician_id == target
                else "Coordinator choice, checked against brief routing rules 1–2"
            ),
            policy_version=f"{dispatch.policy_version} / {self.policy.policy_version}",
            solver_status=dispatch.solver.status,
            alternatives=[
                AlternativeAction(
                    type=T.ESCALATION,
                    label="Escalate to the clinical lead",
                    available=True,
                    reason="If nobody eligible can take it, or it needs a clinical decision.",
                )
            ],
            uncertainty=list(rec.uncertainty) if rec else [],
            restrictions=[
                "Applied by the coordinator (no clinical approval needed for routing).",
                "Applying records a simulated Synapse assignment event; it does not change "
                "Sevaro's production routing.",
            ],
            approver_role="coordinator",
        )
        return _Draft(
            fields={
                "title": f"Reassign {consult_id} to {plan.target_physician_name}"
                if plan
                else f"Reassign {consult_id}",
                "consult_id": consult_id,
                "hospital_ids": hospital_ids,
                "problem": self._problem(
                    analysis,
                    alert,
                    hospital_ids=hospital_ids,
                    consult_id=consult_id,
                    title=f"{consult_id} needs a physician",
                    summary=(
                        f"{consult.consult_type or 'Consult'} at "
                        f"{names.get(consult.hospital_id or '', consult.hospital_id)}, stage "
                        f"{consult.stage.value.replace('_', ' ')}"
                        if consult
                        else None
                    ),
                ).model_dump(mode="json"),
                "recommendation": recommendation.model_dump(mode="json"),
                "reassignment": plan.model_dump(mode="json") if plan else None,
            },
            blocking=blocking,
        )

    def _draft_escalation(
        self, body: InterventionCreate, analysis: OperationalAnalysis, alert: Alert | None
    ) -> _Draft:
        blocking: list[str] = []
        names = {h.id: h.name for h in analysis.state.hospitals}
        consult_id = body.consult_id or (alert.consult_id if alert else None)
        hospital_ids = (
            [alert.hospital_id]
            if alert and alert.hospital_id
            else ([body.hospital_id] if body.hospital_id else [])
        )
        if alert is None and consult_id is None and not hospital_ids:
            blocking.append("Choose the alert, consult or hospital to escalate.")
        unknown = [h for h in hospital_ids if h not in names]
        if unknown:
            blocking.append(f"Unknown hospital(s): {', '.join(unknown)}.")
        if consult_id and not any(c.consult_id == consult_id for c in analysis.state.consultations):
            blocking.append(f"Unknown consult {consult_id}.")
        facts: list[str] = []
        if alert is not None:
            facts.append(alert.recommended_action_reason)
        if consult_id:
            dispatch = self.optimizer.dispatch_for(analysis)
            unassigned = next(
                (u for u in dispatch.plan.unassigned if u.consult_id == consult_id), None
            )
            if unassigned is not None:
                facts.extend(unassigned.explanation)
        if hospital_ids:
            staffing, internals = self.optimizer.staffing_with_internals(analysis)
            for line in staffing.infeasibility:
                if any(names.get(h, h) in line for h in hospital_ids):
                    facts.append(line)
            eligible = [
                c.state.display_name
                for c in internals.candidates
                if c.eligibility.eligible and set(c.scope) & set(hospital_ids)
            ]
            facts.append(
                "Eligible off-shift physicians for "
                f"{', '.join(names.get(h, h) for h in hospital_ids)}: "
                + (", ".join(eligible) if eligible else "none")
                + "."
            )
        where = ", ".join(names.get(h, h) for h in hospital_ids) or "the network"
        requested = (
            f"Decide how {consult_id} at {where} is covered now: authorize an exception to normal "
            "routing or direct clinical contact."
            if consult_id
            else f"Authorize emergency coverage for {where}: the normal fixes are not available."
        )
        detail = EscalationDetail(
            reason=body.reason
            or (alert.recommended_action_reason if alert else "Coordinator requests review."),
            requested_decision=requested,
            blocking_facts=[f for f in dict.fromkeys(facts) if f],
        )
        recommendation = InterventionRecommendation(
            summary=f"Escalate to the clinical lead: {alert.title if alert else where}",
            why=detail.blocking_facts or [detail.reason],
            algorithm=(
                f"Alert rule {alert.rule_code.value} → escalation (normal fix unavailable)"
                if alert
                else "Coordinator escalation"
            ),
            policy_version=self.policy.policy_version,
            alternatives=[
                AlternativeAction(
                    type=T.SPLIT_SHIFT,
                    label="Request split-shift coverage",
                    available=bool(hospital_ids),
                    reason="Only if an off-shift physician passes every rule.",
                ),
                AlternativeAction(
                    type=T.REASSIGN_CONSULT,
                    label="Reassign the consult",
                    available=bool(consult_id),
                    reason="Only if an eligible on-shift physician exists.",
                ),
            ],
            restrictions=["The clinical lead authorizes or rejects; the decision is audited."],
            approver_role="clinical_lead",
        )
        return _Draft(
            fields={
                "title": f"Escalation: {alert.title if alert else (consult_id or where)}",
                "consult_id": consult_id,
                "hospital_ids": hospital_ids,
                "problem": self._problem(
                    analysis, alert, hospital_ids=hospital_ids, consult_id=consult_id
                ).model_dump(mode="json"),
                "recommendation": recommendation.model_dump(mode="json"),
                "escalation": detail.model_dump(mode="json"),
            },
            blocking=blocking,
        )

    # -------------------------------------------------------------- decisions --

    def decide(self, intervention_id: str, body: DecisionRequest, actor: ActorRef) -> Intervention:
        require_role(actor, UserRole.CLINICAL_LEAD, action="approve or reject interventions")
        actor = with_default_identity(actor)
        deferred: AppError | None = None
        with self._write():
            self._sweep_locked()
            rec = self._record(intervention_id)
            kind, status = T(rec.type), S(rec.status)
            if kind is T.REASSIGN_CONSULT:
                raise ConflictError(
                    "Reassignments are applied by the coordinator; there is nothing to approve.",
                    code="approval_not_applicable",
                )
            if body.expected_version is not None and body.expected_version != rec.version:
                raise ConflictError(
                    f"{rec.id} changed since it was loaded (version {body.expected_version} → "
                    f"{rec.version}). Reload and decide again.",
                    code="stale_version",
                    details={"current_status": rec.status, "current_version": rec.version},
                )
            if status is not S.PENDING_APPROVAL:
                previous = self.repo.approval_for(rec.id)
                raise ConflictError(
                    f"{rec.id} is already {status.value.replace('_', ' ')}"
                    + (
                        f" ({previous.decision}d by {previous.actor_id})"
                        if previous is not None
                        else ""
                    )
                    + "; it cannot be decided again.",
                    code="already_decided" if previous is not None else "invalid_transition",
                    details={"current_status": status.value},
                )
            now = self._now()
            if body.decision == "reject":
                self._store_approval(rec, "reject", actor, now, body.note, [])
                transition_intervention(
                    self.session,
                    rec,
                    S.REJECTED,
                    at=now,
                    actor=actor,
                    action="intervention_rejected",
                    summary=f"{actor.actor_id} rejected {rec.id}"
                    + (f": {body.note}" if body.note else "."),
                    reason=body.note,
                    details={"note": body.note},
                )
            else:
                lines, problems, need_gone, plan = self._revalidate(rec, now)
                if need_gone:
                    transition_intervention(
                        self.session,
                        rec,
                        S.NO_LONGER_REQUIRED,
                        at=now,
                        actor=actor,
                        action="intervention_no_longer_required",
                        summary=f"{rec.id} is no longer required: {need_gone}",
                        reason=need_gone,
                        details={"revalidation": lines},
                    )
                    deferred = ConflictError(
                        f"Not approved: {need_gone} The request was closed as no longer required.",
                        code="no_longer_required",
                        details={"revalidation": lines},
                    )
                elif problems:
                    write_audit(
                        self.session,
                        at=now,
                        actor=actor,
                        action="approval_blocked",
                        summary=f"Approval of {rec.id} blocked by revalidation: "
                        + "; ".join(problems),
                        entity_type="intervention",
                        entity_id=rec.id,
                        intervention_id=rec.id,
                        from_status=rec.status,
                        to_status=rec.status,
                        details={"problems": problems, "revalidation": lines},
                    )
                    deferred = ConflictError(
                        "Not approved: the proposal no longer passes the rules at the current "
                        "data. Reject it and ask the coordinator to re-propose.",
                        code="revalidation_failed",
                        details={"problems": problems, "revalidation": lines},
                    )
                else:
                    if plan != rec.offer_plan:
                        rec.offer_plan = plan  # starts that had passed now start now
                    self._store_approval(rec, "approve", actor, now, body.note, lines)
                    transition_intervention(
                        self.session,
                        rec,
                        S.APPROVED,
                        at=now,
                        actor=actor,
                        action="intervention_approved",
                        summary=f"{actor.actor_id} approved {rec.id}"
                        + (
                            ". Offers can now be sent (simulated)."
                            if kind is T.SPLIT_SHIFT
                            else " (escalation authorized)."
                        ),
                        details={"note": body.note, "revalidation": lines},
                    )
        if deferred is not None:
            raise deferred
        return self.get(intervention_id, actor)

    def _store_approval(
        self,
        rec: InterventionRecord,
        decision: str,
        actor: ActorRef,
        now: datetime,
        note: str | None,
        lines: list[str],
    ) -> None:
        self.session.add(
            ApprovalRecord(
                intervention_id=rec.id,
                decision=decision,
                actor_role=actor.role.value,
                actor_id=actor.actor_id,
                decided_at=now,
                recorded_at=utc_now(),
                note=note,
                data_version=data_version(self.session),
                revalidation=lines,
            )
        )
        try:
            self.session.flush()
        except IntegrityError as exc:  # unique(intervention_id): a decision already exists
            raise ConflictError(
                f"{rec.id} has already been decided.", code="already_decided"
            ) from exc

    def _revalidate(
        self, rec: InterventionRecord, now: datetime
    ) -> tuple[list[str], list[str], str | None, list[dict[str, Any]]]:
        """(what was checked, blocking problems, reason the need disappeared, the offer plan
        as it would be approved: a start that has passed moves to now)."""
        plan = list(rec.offer_plan or [])
        analysis = self._analysis()
        lines = [
            f"Re-checked at simulation time {now.isoformat()} against data version "
            f"{analysis.state.data_version}."
        ]
        kind = T(rec.type)
        if kind is T.ESCALATION:
            if rec.alert_id and not any(
                same_problem(a.alert_id, rec.alert_id) for a in analysis.alerts.alerts
            ):
                return lines, [], f"alert {rec.alert_id} is no longer active.", plan
            lines.append("The escalated problem is still active.")
            return lines, [], None, plan
        staffing, internals = self.optimizer.staffing_with_internals(analysis)
        ctx = internals.ctx
        cands = {c.physician_id: c for c in internals.candidates}
        names = {h.id: h.name for h in analysis.state.hospitals}
        need = rec.hospital_ids
        if not [h for h in need if h in ctx.gap_hospitals]:
            return (
                lines,
                [],
                f"no coverage gap remains at {', '.join(names.get(h, h) for h in need)} in the "
                f"next {ctx.lookahead_minutes} min (counting accepted shifts).",
                plan,
            )
        lines.append(
            f"Coverage need still present at "
            f"{', '.join(names.get(h, h) for h in need if h in ctx.gap_hospitals)}."
        )
        if rec.offer_plan and all(self._plan_need(i, now) <= 0 for i in rec.offer_plan):
            holders = ", ".join(o.display_name for o in self._binding_for_need(rec))
            return (
                lines,
                [],
                "the planned shift(s) would no longer cover any deficit: coverage during that "
                f"time is already secured{f' ({holders})' if holders else ''}.",
                plan,
            )
        problems: list[str] = []
        for index, original in enumerate(rec.offer_plan):
            item, moved = slide_to_now(original, now)
            plan[index] = item
            if moved:
                lines.append(moved)
            pid, name = item["physician_id"], item["display_name"]
            start = datetime.fromisoformat(item["start_at"])
            cand = cands.get(pid)
            if cand is None:
                problems.append(f"{name} is no longer on the off-shift roster.")
                continue
            checks = offer_checks(
                cand.state,
                cand.profile,
                start,
                item["duration_minutes"],
                tuple(item["hospital_ids"]),
                ctx,
                cand.online_minutes,
                cand.eligibility.online_time_assumed,
            )
            failed = [c for c in checks if not c.passed]
            if failed:
                problems.append(f"{name}: " + "; ".join(f"{c.label}: {c.message}" for c in failed))
            else:
                lines.append(
                    f"{name}: all {len(checks)} split-shift rules pass for this offer "
                    "(including ≤ 1 open offer and ≤ 3 per rolling 7 days from the offer log)."
                )
            # Voluntary availability is a preference, never a rule: a change since the
            # proposal is reported for the approver, it does not block the approval.
            volunteered = (item.get("voluntary") or {}).get("status") == "applied"
            window = ctx.window_for(pid, start, datetime.fromisoformat(item["end_at"]))
            if volunteered and window is None:
                lines.append(
                    f"{name} is no longer voluntarily available for this offer (availability "
                    "withdrawn or changed since the proposal); the offer is still valid under "
                    "the rules, but ask whether to re-rank."
                )
            elif window is not None:
                lines.append(f"{name} is voluntarily available for this whole offer.")
        return lines, problems, None, plan

    # ------------------------------------------------------------------ offers --

    def send_offers(self, intervention_id: str, actor: ActorRef) -> Intervention:
        require_role(
            actor, UserRole.COORDINATOR, UserRole.CLINICAL_LEAD, action="send approved offers"
        )
        actor = with_default_identity(actor)
        deferred: AppError | None = None
        with self._write():
            self._sweep_locked()
            rec = self._record(intervention_id)
            if T(rec.type) is not T.SPLIT_SHIFT:
                raise ConflictError("Only split-shift requests send offers.", code="not_applicable")
            status = S(rec.status)
            if status is S.PENDING_APPROVAL:
                raise ConflictError(
                    f"{rec.id} has not been approved. No split-shift offer may be sent before "
                    "clinical-lead approval.",
                    code="approval_required",
                    details={"current_status": status.value},
                )
            if status is not S.APPROVED:
                raise ConflictError(
                    f"{rec.id} is {status.value.replace('_', ' ')}; offers can only be sent "
                    "once, right after approval.",
                    code="invalid_transition",
                    details={"current_status": status.value},
                )
            approval = self.repo.approval_for(rec.id)
            if approval is None or approval.decision != "approve":
                raise ConflictError(
                    "No approval on record.", code="approval_required"
                )  # pragma: no cover - guarded by status
            now = self._now()
            analysis = self._analysis()
            staffing, internals = self.optimizer.staffing_with_internals(analysis)
            ctx = internals.ctx
            shared = ctx.availability
            cands = {c.physician_id: c for c in internals.candidates}
            hospitals = {h.id: h for h in analysis.state.hospitals}
            consult_ids = [c.consult_id for c in analysis.state.consultations]
            reference = {p.id: p for p in analysis.reference.physicians}
            surge = any(
                bool(h.current.spike)
                for h in analysis.demand.hospitals
                if h.hospital_id in rec.hospital_ids
            )
            sent: list[OfferRecord] = []
            skipped: list[str] = []
            unneeded = 0
            plan = list(rec.offer_plan)
            for index, original in enumerate(rec.offer_plan):
                item, moved = slide_to_now(original, now)
                if moved:
                    plan[index] = item
                    write_audit(
                        self.session,
                        at=now,
                        actor=actor,
                        action="offer_start_moved",
                        summary=moved,
                        entity_type="intervention",
                        entity_id=rec.id,
                        intervention_id=rec.id,
                        details={"physician_id": item["physician_id"]},
                    )
                pid, name = item["physician_id"], item["display_name"]
                start = datetime.fromisoformat(item["start_at"])
                end = datetime.fromisoformat(item["end_at"])
                problems = []
                if self._plan_need(item, now) <= 0:
                    # Stop asking once the gap is filled, also for offers not sent yet.
                    unneeded += 1
                    problems.append(
                        "coverage during this shift is already secured (no remaining deficit "
                        "while it would run)"
                    )
                open_, committed, week = self.repo.offer_counts(
                    pid, now, self.policy.week_window, self._import_id()
                )
                if open_ >= self.policy.max_open_offers_per_physician:
                    problems.append("already has an open offer (limit 1)")
                if committed:
                    problems.append("already committed to an accepted split shift")
                if week >= self.policy.max_offers_per_physician_per_week:
                    problems.append(
                        f"already received {week} offers in the rolling 7 days (limit "
                        f"{self.policy.max_offers_per_physician_per_week})"
                    )
                online = timedelta(minutes=item["minutes_to_online"])
                useful = (end - (max(start, now) + online)).total_seconds() / 60
                if useful < ctx.cfg.staffing.min_offer_minutes:
                    problems.append(
                        f"now worth only {useful:.0f} min of coverage (needs ≥ "
                        f"{ctx.cfg.staffing.min_offer_minutes})"
                    )
                cand = cands.get(pid)
                if cand is None:
                    problems.append("no longer on the off-shift roster")
                else:
                    checks = offer_checks(
                        cand.state,
                        cand.profile,
                        start,
                        item["duration_minutes"],
                        tuple(item["hospital_ids"]),
                        ctx,
                        cand.online_minutes,
                        cand.eligibility.online_time_assumed,
                    )
                    problems.extend(
                        f"{c.label}: {c.message}"
                        for c in checks
                        if not c.passed and c.code != "notification_limits"
                    )
                if problems:
                    skipped.append(f"{name}: " + "; ".join(problems))
                    write_audit(
                        self.session,
                        at=now,
                        actor=actor,
                        action="offer_not_sent",
                        summary=f"Offer to {name} not sent: " + "; ".join(problems),
                        entity_type="intervention",
                        entity_id=rec.id,
                        intervention_id=rec.id,
                        details={"physician_id": pid, "problems": problems},
                    )
                    continue
                shortfall = next(
                    (
                        h.metrics.first_shortfall_at
                        for h in analysis.coverage.hospitals
                        if h.hospital_id in item["hospital_ids"] and h.metrics.first_shortfall_at
                    ),
                    None,
                )
                zone = self._hospital_zone(analysis, item["hospital_ids"])
                volunteered = any(
                    w.start <= datetime.fromisoformat(item["start_at"])
                    and datetime.fromisoformat(item["end_at"]) <= w.end
                    for w in shared.get(pid, [])
                )
                reason = offer_reason(
                    [hospitals[h].name for h in item["hospital_ids"] if h in hospitals],
                    shortfall,
                    zone,
                    surge,
                    volunteered,
                )
                if find_disallowed([reason], consult_ids):  # defensive: never leak IDs
                    reason = "Short-term coverage gap at hospitals where you are credentialed."
                offer = OfferRecord(
                    id=self.repo.next_offer_id(),
                    intervention_id=rec.id,
                    physician_id=pid,
                    display_name=name,
                    plan_role=item["role"],
                    status=O.SENT.value,
                    hospital_ids=list(item["hospital_ids"]),
                    routing_scope=list(item["routing_scope_hospital_ids"]),
                    seeded_consult_count=item["seeded_consult_count"],
                    start_at=start,
                    end_at=end,
                    duration_minutes=item["duration_minutes"],
                    minutes_to_online=item["minutes_to_online"],
                    reason=reason,
                    channel=reference[pid].notification_channel if pid in reference else None,
                    approved_by_role=approval.actor_role,
                    approved_by_id=approval.actor_id,
                    sent_by_role=actor.role.value,
                    sent_by_id=actor.actor_id,
                    sent_at=now,
                    expires_at=now + self.policy.offer_ttl,
                    recorded_at=utc_now(),
                )
                self.session.add(offer)
                try:
                    self.session.flush()
                except IntegrityError as exc:  # one open offer per physician (DB index)
                    raise ConflictError(
                        f"{name} already has an open offer.", code="offer_limit_reached"
                    ) from exc
                write_audit(
                    self.session,
                    at=now,
                    actor=actor,
                    action="offer_sent",
                    summary=f"Offer {offer.id} sent to {name} (simulated "
                    f"{offer.channel or 'app'} message; nothing leaves the system). Expires "
                    f"{offer.expires_at.isoformat()}.",
                    entity_type="offer",
                    entity_id=offer.id,
                    intervention_id=rec.id,
                    offer_id=offer.id,
                    to_status=O.SENT.value,
                    details={
                        "physician_id": pid,
                        "approved_by": approval.actor_id,
                        "message": reason,
                        "hospital_ids": offer.hospital_ids,
                        "start_at": start,
                        "end_at": end,
                        "expires_at": offer.expires_at,
                        "offers_in_7_days_before": week,
                    },
                )
                sent.append(offer)
            if plan != rec.offer_plan:
                rec.offer_plan = plan
            if sent:
                transition_intervention(
                    self.session,
                    rec,
                    S.OFFER_SENT,
                    at=now,
                    actor=actor,
                    action="offers_sent",
                    summary=f"{len(sent)} offer(s) sent for {rec.id}"
                    + (f"; not sent: {'; '.join(skipped)}" if skipped else "."),
                    details={"offer_ids": [o.id for o in sent], "not_sent": skipped},
                )
            elif rec.offer_plan and unneeded == len(rec.offer_plan):
                why = "coverage during the planned shift(s) is already secured"
                transition_intervention(
                    self.session,
                    rec,
                    S.NO_LONGER_REQUIRED,
                    at=now,
                    actor=actor,
                    action="intervention_no_longer_required",
                    summary=f"{rec.id} is no longer required: {why}. No offer was sent.",
                    reason=why,
                    details={"not_sent": skipped},
                )
                deferred = ConflictError(
                    f"No offer sent: {why}. The request was closed as no longer required.",
                    code="no_longer_required",
                    details={"problems": skipped},
                )
            else:
                deferred = ConflictError(
                    "No offer could be sent: " + " ".join(skipped),
                    code="send_blocked",
                    details={"problems": skipped},
                )
        if deferred is not None:
            raise deferred
        return self.get(intervention_id, actor)

    def _need_during(
        self,
        hospitals: Sequence[str],
        start: datetime,
        end: datetime,
        now: datetime,
        minutes_to_online: int,
    ) -> float:
        """Forecast deficit physician-minutes at ``hospitals`` during the time a shift
        [start, end) would cover once online, counting every accepted or active split shift
        (workflow overlay)."""
        analysis = self._analysis()
        ctx = build_planning_context(analysis, self.optimizer.config())
        begin = max(start, now) + timedelta(minutes=minutes_to_online)
        total = 0.0
        for hid in hospitals:
            model = ctx.models.get(hid)
            if model is not None:
                total += deficit_between(model, begin, end)
        return round(total, 4)

    def _remaining_need(self, offer: OfferRecord, now: datetime) -> float:
        return self._need_during(
            offer.routing_scope or offer.hospital_ids,
            offer.start_at,
            offer.end_at,
            now,
            offer.minutes_to_online,
        )

    def _plan_need(self, item: dict[str, Any], now: datetime) -> float:
        """Remaining need during one planned (not yet sent) offer."""
        return self._need_during(
            item.get("routing_scope_hospital_ids") or item["hospital_ids"],
            datetime.fromisoformat(item["start_at"]),
            datetime.fromisoformat(item["end_at"]),
            now,
            item["minutes_to_online"],
        )

    def respond(
        self, offer_id: str, body: OfferResponseRequest, actor: ActorRef
    ) -> OfferResponseResult:
        require_role(actor, UserRole.PHYSICIAN, action="respond to split-shift offers")
        if not actor.actor_id:
            raise AppError(
                "X-Demo-Actor-Id (the physician's ID) is required.",
                code="actor_required",
                status_code=401,
            )
        deferred: AppError | None = None
        outcome, message, replay = "", "", False
        with self._write():
            self._sweep_locked()
            offer = self.repo.get_offer(offer_id)
            if offer is None or offer.physician_id != actor.actor_id:
                raise NotFoundError(f"Offer {offer_id} not found")
            now = self._now()
            status = O(offer.status)
            if now < offer.sent_at:
                # The clock was moved back (Reset / Set time) to before the offer was sent: at
                # this simulated time it does not exist yet, so it cannot be answered.
                raise ConflictError(
                    f"At the current simulation time ({now.isoformat()}) offer {offer.id} has "
                    f"not been sent yet (sent {offer.sent_at.isoformat()}). Move the clock "
                    "forward to answer it.",
                    code="offer_not_sent_yet",
                    details={"sent_at": offer.sent_at, "simulation_time": now},
                )
            seconds = int((now - offer.sent_at).total_seconds())

            def record(result: str, detail: str | None = None) -> None:
                self.session.add(
                    OfferResponseRecord(
                        offer_id=offer.id,
                        physician_id=offer.physician_id,
                        response=body.response,
                        outcome=result,
                        received_at=now,
                        recorded_at=utc_now(),
                        response_seconds=seconds,
                        detail=detail,
                    )
                )
                self.session.flush()

            def audit_attempt(action: str, summary: str, details: dict | None = None) -> None:
                write_audit(
                    self.session,
                    at=now,
                    actor=actor,
                    action=action,
                    summary=summary,
                    entity_type="offer",
                    entity_id=offer.id,
                    intervention_id=offer.intervention_id,
                    offer_id=offer.id,
                    from_status=status.value,
                    to_status=offer.status,
                    details={
                        "response": body.response,
                        "response_seconds": seconds,
                        **(details or {}),
                    },
                )

            if body.response == "accept":
                if status in (O.ACCEPTED, O.ACTIVE, O.COMPLETED, O.REDUNDANT):
                    record("duplicate_ignored")
                    audit_attempt(
                        "duplicate_response_ignored",
                        f"Repeated acceptance of {offer.id} by {offer.display_name} ignored "
                        "(already recorded).",
                    )
                    outcome, replay = "duplicate_ignored", True
                    message = "Your acceptance was already recorded. Nothing changed."
                elif status is O.SENT:
                    outcome, message = self._accept(offer, now, actor, seconds, record)
                else:
                    detail = offer.status_reason
                    code = {
                        O.DECLINED: "offer_declined",
                        O.EXPIRED: "offer_expired",
                        O.WITHDRAWN: "offer_withdrawn",
                        O.CANCELLED: "offer_cancelled",
                    }.get(status, "offer_closed")
                    text = {
                        O.DECLINED: "You declined this offer; a declined offer cannot be "
                        "accepted later.",
                        O.EXPIRED: f"This offer expired at {offer.expires_at.isoformat()} "
                        "(10 minutes after it was sent) and can no longer be accepted.",
                        O.WITHDRAWN: f"This offer was withdrawn: {detail}. Your acceptance was "
                        "recorded; you are not needed for this shift.",
                        O.CANCELLED: "This offer was cancelled and can no longer be accepted.",
                    }.get(status, "This offer is closed.")
                    record(f"rejected_{status.value}", detail)
                    action = (
                        "redundant_acceptance_recorded"
                        if status is O.WITHDRAWN
                        and offer.status_reason
                        and "secured" in offer.status_reason
                        else "response_rejected"
                    )
                    audit_attempt(
                        action,
                        f"Acceptance of {offer.id} by {offer.display_name} refused: offer is "
                        f"{status.value}." + (f" ({detail})" if detail else ""),
                        {"code": code},
                    )
                    if action == "redundant_acceptance_recorded":
                        write_audit(
                            self.session,
                            at=now,
                            actor=SYSTEM_ACTOR,
                            action="conflict_resolved",
                            summary=f"Late acceptance by {offer.display_name} after coverage was "
                            "secured: recorded, not activated; physician released and told so.",
                            entity_type="offer",
                            entity_id=offer.id,
                            intervention_id=offer.intervention_id,
                            offer_id=offer.id,
                            details={"policy": "first binding acceptance wins"},
                        )
                    deferred = ConflictError(
                        text, code=code, details={"offer_status": status.value}
                    )
            else:
                if status is O.DECLINED:
                    record("duplicate_ignored")
                    audit_attempt(
                        "duplicate_response_ignored",
                        f"Repeated decline of {offer.id} by {offer.display_name} ignored.",
                    )
                    outcome, replay = "duplicate_ignored", True
                    message = "Your decline was already recorded."
                elif status is O.SENT:
                    offer.responded_at = now
                    transition_offer(
                        self.session,
                        offer,
                        O.DECLINED,
                        at=now,
                        actor=actor,
                        action="offer_declined",
                        summary=f"{offer.display_name} declined {offer.id} after {seconds} s.",
                        details={"response_seconds": seconds},
                    )
                    record("declined")
                    rec = self._record(offer.intervention_id)
                    self._sync_split_status(rec, now, actor)
                    outcome = "declined"
                    message = "Declined. Thank you — the coordinator has been informed."
                else:
                    record(f"rejected_{status.value}", offer.status_reason)
                    audit_attempt(
                        "response_rejected",
                        f"Decline of {offer.id} refused: offer is {status.value}.",
                    )
                    deferred = ConflictError(
                        "You already accepted this shift; ask the coordinator to cancel it."
                        if status in (O.ACCEPTED, O.ACTIVE)
                        else f"This offer is {status.value} and can no longer be declined.",
                        code=f"offer_{status.value}",
                        details={"offer_status": status.value},
                    )
        if deferred is not None:
            raise deferred
        view = self._physician_view(self._offer(offer_id), self._now(), self._hospitals())
        return OfferResponseResult(
            offer=view, outcome=outcome, idempotent_replay=replay, message=message
        )

    def _accept(self, offer, now, actor, seconds, record) -> tuple[str, str]:
        rec = self._record(offer.intervention_id)
        binding = self._binding_for_need(
            rec, exclude_offer_id=offer.id, window=offer_window(offer, now)
        )
        quota_full = len(binding) >= rec.required_physicians
        remaining = None
        if not quota_full and self.policy.require_remaining_need_on_accept:
            remaining = self._remaining_need(offer, now)
        if quota_full or (remaining is not None and remaining <= 0):
            holder = ", ".join(o.display_name for o in binding) or "other accepted coverage"
            why = (
                f"this need already has {len(binding)} binding acceptance(s) ({holder}) of "
                f"{rec.required_physicians} required"
                if quota_full
                else "the forecast shows no remaining deficit at these hospitals during this "
                "shift (coverage already secured)"
            )
            offer.responded_at = now
            transition_offer(
                self.session,
                offer,
                O.REDUNDANT,
                at=now,
                actor=actor,
                action="offer_accepted_redundant",
                summary=f"{offer.display_name} accepted {offer.id} after {seconds} s, but {why}.",
                reason=f"coverage already secured — {why}",
                details={"response_seconds": seconds, "remaining_need_minutes": remaining},
            )
            record("accepted_redundant", why)
            write_audit(
                self.session,
                at=now,
                actor=SYSTEM_ACTOR,
                action="conflict_detected",
                summary=f"Conflicting acceptance for {rec.id}: {offer.display_name} accepted "
                f"after the need was met ({why}).",
                entity_type="intervention",
                entity_id=rec.id,
                intervention_id=rec.id,
                offer_id=offer.id,
                details={
                    "redundant_offer_id": offer.id,
                    "binding_offer_ids": [o.id for o in binding],
                    "remaining_need_minutes": remaining,
                },
            )
            write_audit(
                self.session,
                at=now,
                actor=SYSTEM_ACTOR,
                action="conflict_resolved",
                summary=f"Policy 'first binding acceptance wins': {offer.display_name}'s "
                "acceptance recorded as redundant; not activated; physician released and told "
                "so.",
                entity_type="intervention",
                entity_id=rec.id,
                intervention_id=rec.id,
                offer_id=offer.id,
                details={"policy": "first binding acceptance wins"},
            )
            self._sync_split_status(rec, now, actor)
            return (
                "redundant",
                "Thank you — your acceptance was recorded, but coverage had already been "
                "secured. You are not needed for this shift; no further action.",
            )
        offer.responded_at = now
        offer.accepted_at = now
        offer.expected_online_at = max(offer.start_at, now) + timedelta(
            minutes=offer.minutes_to_online
        )
        transition_offer(
            self.session,
            offer,
            O.ACCEPTED,
            at=now,
            actor=actor,
            action="offer_accepted",
            summary=f"{offer.display_name} accepted {offer.id} after {seconds} s (binding). "
            f"Expected online {offer.expected_online_at.isoformat()}; not active capacity yet.",
            details={
                "response_seconds": seconds,
                "binding": True,
                "remaining_need_minutes_before": remaining,
                "expected_online_at": offer.expected_online_at,
            },
        )
        record("accepted")
        bump_data_version(self.session)
        self._sync_split_status(rec, now, actor)
        self._withdraw_unneeded(now, secured_by=offer)
        return (
            "accepted",
            "Accepted. Please come online by "
            f"{offer.expected_online_at.isoformat()}. You are counted as active capacity only "
            "once you are online.",
        )

    def _binding_for_need(
        self,
        rec: InterventionRecord,
        *,
        exclude_offer_id: str | None = None,
        window: tuple[datetime, datetime] | None = None,
    ) -> list[OfferRecord]:
        """Accepted or active split shifts that already serve this request's need: its own,
        and those of other open requests for overlapping hospitals (the same shortage can be
        targeted by two requests; it must not be filled twice). With ``window``, only shifts
        that cover at least half of it count: a shift ending soon (or a short handover) does
        not fill a later gap."""
        need = set(rec.hospital_ids)
        now = self._now()
        found: list[OfferRecord] = []
        for other in self.repo.list_interventions(
            import_id=rec.dataset_import_id, types=[T.SPLIT_SHIFT.value]
        ):
            if other.id != rec.id and not set(other.hospital_ids) & need:
                continue
            for o in self.repo.offers_for(other.id):
                if (
                    o.id != exclude_offer_id
                    and O(o.status) in (O.ACCEPTED, O.ACTIVE)
                    and set(o.routing_scope or o.hospital_ids) & need
                ):
                    if window is not None:
                        start, end = offer_window(o, now)
                        overlap = min(end, window[1]) - max(start, window[0])
                        if overlap * 2 < window[1] - window[0]:
                            continue
                    found.append(o)
        return found

    def _withdraw_unneeded(self, now: datetime, *, secured_by: OfferRecord) -> None:
        """Stop asking once the gap is filled: withdraw every sent offer whose need now has
        enough binding acceptances, or whose hospitals no longer show any deficit during the
        time it would cover."""
        for offer in self.repo.offers_with_status([O.SENT]):
            rec = self.repo.get_intervention(offer.intervention_id)
            if rec is None or rec.dataset_import_id != self._import_id():
                continue
            binding = self._binding_for_need(rec, window=offer_window(offer, now))
            if len(binding) >= rec.required_physicians:
                same = offer.intervention_id == secured_by.intervention_id
                reason = (
                    "coverage was secured by another physician; this offer is no longer needed"
                    if same
                    else "coverage for this shortage was secured through "
                    f"{secured_by.intervention_id}; this offer is no longer needed"
                )
                summary = (
                    f"Offer {offer.id} to {offer.display_name} withdrawn: {len(binding)} of "
                    f"{rec.required_physicians} required physician(s) secured "
                    f"({', '.join(o.display_name for o in binding)})."
                )
            elif self._remaining_need(offer, now) <= 0:
                reason = "coverage at these hospitals was secured; this offer is no longer needed"
                summary = (
                    f"Offer {offer.id} to {offer.display_name} withdrawn: the forecast shows no "
                    "remaining deficit at its hospitals during that shift."
                )
            else:
                continue
            transition_offer(
                self.session,
                offer,
                O.WITHDRAWN,
                at=now,
                actor=SYSTEM_ACTOR,
                action="offer_withdrawn",
                summary=summary,
                reason=reason,
                details={
                    "policy": "stop asking once the gap is filled",
                    "secured_by_offer_id": secured_by.id,
                },
            )
            self._sync_split_status(rec, now, SYSTEM_ACTOR)
        # Requests for the same hospitals that were proposed or approved but not sent yet:
        # close them if none of their planned shifts would still cover a deficit.
        secured = set(secured_by.routing_scope or secured_by.hospital_ids)
        for other in self.repo.list_interventions(
            import_id=self._import_id(), types=[T.SPLIT_SHIFT.value]
        ):
            if S(other.status) not in (S.PENDING_APPROVAL, S.APPROVED):
                continue
            if not set(other.hospital_ids) & secured or not other.offer_plan:
                continue
            if any(self._plan_need(item, now) > 0 for item in other.offer_plan):
                continue
            why = (
                f"coverage during its planned shift(s) was secured through "
                f"{secured_by.intervention_id} ({secured_by.display_name})"
            )
            transition_intervention(
                self.session,
                other,
                S.NO_LONGER_REQUIRED,
                at=now,
                actor=SYSTEM_ACTOR,
                action="intervention_no_longer_required",
                summary=f"{other.id} closed before any offer was sent: {why}.",
                reason=why,
                details={
                    "policy": "stop asking once the gap is filled",
                    "secured_by_offer_id": secured_by.id,
                },
            )

    def _sync_split_status(self, rec: InterventionRecord, now: datetime, actor: ActorRef) -> None:
        if T(rec.type) is not T.SPLIT_SHIFT:
            return
        current = S(rec.status)
        offers = self.repo.offers_for(rec.id)
        target = split_shift_status_from_offers(current, [O(o.status) for o in offers])
        if target is current or not can_transition(T.SPLIT_SHIFT, current, target):
            return
        transition_intervention(
            self.session,
            rec,
            target,
            at=now,
            actor=actor,
            action=f"intervention_{target.value}",
            summary=f"{rec.id} is now {target.value.replace('_', ' ')} (from its offers: "
            + ", ".join(f"{o.id} {o.status}" for o in offers)
            + ").",
        )

    def activate(self, offer_id: str, actor: ActorRef) -> ShiftOffer:
        require_role(
            actor, UserRole.PHYSICIAN, UserRole.COORDINATOR, action="activate a split shift"
        )
        actor = with_default_identity(actor)
        with self._write():
            self._sweep_locked()
            offer = self.repo.get_offer(offer_id)
            if offer is None or (
                actor.role is UserRole.PHYSICIAN and offer.physician_id != actor.actor_id
            ):
                raise NotFoundError(f"Offer {offer_id} not found")
            status = O(offer.status)
            if status is O.ACCEPTED:
                now = self._now()
                if now < offer.start_at:
                    raise ConflictError(
                        f"The split shift starts {offer.start_at.isoformat()}; the physician "
                        "cannot go online before it starts.",
                        code="shift_not_started",
                    )
                source = (
                    "physician_reported"
                    if actor.role is UserRole.PHYSICIAN
                    else "coordinator_simulated"
                )
                self._activate(offer, at=now, actor=actor, source=source)
            elif status is not O.ACTIVE:
                raise ConflictError(
                    f"Offer {offer_id} is {status.value}; only an accepted split shift can be "
                    "activated.",
                    code="invalid_transition",
                    details={"current_status": status.value},
                )
        return self._shift_offer(self._offer(offer_id), self._now(), actor)

    def _go_live_seed(
        self, analysis: OperationalAnalysis, offer: OfferRecord, at: datetime
    ) -> tuple[int, str]:
        """Trap protection's seeded count, recalculated from the physicians working at the
        routing-scope hospitals at go-live (the proposal only had an estimate: peers may have
        left or started since)."""
        moment = analysis.state.as_of
        joiner = next(
            (p for p in analysis.state.physicians if p.physician_id == offer.physician_id), None
        )
        peers, covering = seed_peers(
            analysis.state.physicians,
            analysis.coverage_models,
            offer.physician_id,
            offer.routing_scope,
            moment,
            self.optimizer.config().trap.seed_peer_overlap_minutes,
        )
        zone = self._hospital_zone(analysis, offer.routing_scope)
        return seed_count(
            self.optimizer.config(),
            joiner.roster_role if joiner else None,
            peers,
            covering,
            offer.routing_scope,
            f"at go-live ({fmt_local(moment, zone)})",
            joiner_start=offer.start_at,
            tz=network_timezone(analysis.state.hospitals),
        )

    def _activate(self, offer: OfferRecord, *, at: datetime, actor: ActorRef, source: str) -> None:
        # At the activation time itself: a big clock jump applies it later than it happened.
        before = self.analyses.analysis(at)
        proposed_seed = offer.seeded_consult_count
        seed, seed_reason = self._go_live_seed(before, offer, at)
        offer.seeded_consult_count = seed
        offer.activated_at = at
        offer.activation_source = source
        changed = (
            f" (estimated {proposed_seed} at proposal; recalculated from the physicians "
            "working now)"
            if seed != proposed_seed
            else ""
        )
        transition_offer(
            self.session,
            offer,
            O.ACTIVE,
            at=at,
            actor=actor,
            action="physician_activated",
            summary=f"{offer.display_name} is online ({source.replace('_', ' ')}) at "
            f"{at.isoformat()}; routable only at {', '.join(offer.routing_scope)} with a seeded "
            f"routing count of {seed}{changed}.",
            details={
                "source": source,
                "routing_scope": offer.routing_scope,
                "seeded_consult_count": seed,
                "seeded_consult_count_at_proposal": proposed_seed,
                "seed_reason": seed_reason,
            },
        )
        bump_data_version(self.session)
        after = self.analyses.analysis(at)
        impact = self._coverage_impact(
            before,
            offer.routing_scope,
            "Modeled at activation: before → after (same simulation time)",
            after=after,
            notes=[
                "Before: the physician was preparing (not counted as current capacity). After: "
                "counted as confirmed coverage within the approved routing scope."
            ],
        )
        offer.activation_impact = impact.model_dump(mode="json")
        write_audit(
            self.session,
            at=at,
            actor=actor,
            action="coverage_recalculated",
            summary=f"Coverage, alerts and recommendations recalculated after activating "
            f"{offer.display_name}: deficit {impact.total_before:g} → {impact.total_after:g} "
            f"physician-minutes over {impact.horizon_minutes} min at "
            f"{', '.join(offer.routing_scope)}.",
            entity_type="offer",
            entity_id=offer.id,
            intervention_id=offer.intervention_id,
            offer_id=offer.id,
            details={
                "impact": impact,
                "alerts_before": before.alerts.total,
                "alerts_after": after.alerts.total,
                "data_version": after.state.data_version,
            },
        )
        rec = self.repo.get_intervention(offer.intervention_id)
        if rec is not None:
            self._sync_split_status(rec, at, actor)

    # ---------------------------------------------------------- other actions --

    def cancel(self, intervention_id: str, body: CancelRequest, actor: ActorRef) -> Intervention:
        require_role(
            actor, UserRole.COORDINATOR, UserRole.CLINICAL_LEAD, action="cancel interventions"
        )
        actor = with_default_identity(actor)
        with self._write():
            self._sweep_locked()
            rec = self._record(intervention_id)
            status = S(rec.status)
            if status is S.CANCELLED:
                return self.get(intervention_id, actor)  # idempotent
            now = self._now()
            by = f"cancelled by the {actor.role.value.replace('_', ' ')}"
            # Staff free text stays in the audit log and on the request; the physician's phone
            # only ever shows generated wording (it could mention a patient).
            reason = body.reason or by
            staffing_changed = False
            for offer in self.repo.offers_for(rec.id):
                current = O(offer.status)
                if current is O.SENT:
                    transition_offer(
                        self.session,
                        offer,
                        O.WITHDRAWN,
                        at=now,
                        actor=actor,
                        action="offer_withdrawn",
                        summary=f"Offer {offer.id} to {offer.display_name} withdrawn: {reason}.",
                        reason=f"the request was {by}",
                    )
                elif current in (O.ACCEPTED, O.ACTIVE):
                    offer.ended_at = now
                    transition_offer(
                        self.session,
                        offer,
                        O.CANCELLED,
                        at=now,
                        actor=actor,
                        action="split_shift_cancelled",
                        summary=f"{offer.display_name}'s split shift ({offer.id}) cancelled: "
                        f"{reason}.",
                        reason=by,
                    )
                    staffing_changed = True
            if staffing_changed:
                bump_data_version(self.session)
            transition_intervention(
                self.session,
                rec,
                S.CANCELLED,
                at=now,
                actor=actor,
                action="intervention_cancelled",
                summary=f"{actor.actor_id} cancelled {rec.id}: {reason}.",
                reason=reason,
            )
        return self.get(intervention_id, actor)

    def withdraw_offer(self, offer_id: str, body: CancelRequest, actor: ActorRef) -> ShiftOffer:
        require_role(actor, UserRole.COORDINATOR, UserRole.CLINICAL_LEAD, action="withdraw offers")
        actor = with_default_identity(actor)
        offer = self._offer(offer_id)
        if O(offer.status) in (O.ACCEPTED, O.ACTIVE):
            # Ends this physician's shift only; other accepted shifts in the request stay.
            with self._write():
                self._sweep_locked()
                offer = self._offer(offer_id)
                if O(offer.status) in (O.ACCEPTED, O.ACTIVE):
                    now = self._now()
                    by = f"cancelled by the {actor.role.value.replace('_', ' ')}"
                    offer.ended_at = now
                    transition_offer(
                        self.session,
                        offer,
                        O.CANCELLED,
                        at=now,
                        actor=actor,
                        action="split_shift_cancelled",
                        summary=f"{offer.display_name}'s split shift ({offer.id}) cancelled: "
                        f"{body.reason or by}.",
                        reason=by,  # shown on the physician's phone: never staff free text
                        details={"note": body.reason} if body.reason else None,
                    )
                    bump_data_version(self.session)
                    self._sync_split_status(self._record(offer.intervention_id), now, actor)
            return self._shift_offer(self._offer(offer_id), self._now(), actor)
        with self._write():
            self._sweep_locked()
            offer = self._offer(offer_id)
            now = self._now()
            by = f"withdrawn by the {actor.role.value.replace('_', ' ')}"
            reason = body.reason or by
            transition_offer(
                self.session,
                offer,
                O.WITHDRAWN,
                at=now,
                actor=actor,
                action="offer_withdrawn",
                summary=f"Offer {offer.id} to {offer.display_name} withdrawn: {reason}.",
                reason=by,  # shown on the physician's phone: never staff free text
                details={"note": body.reason} if body.reason else None,
            )
            self._sync_split_status(self._record(offer.intervention_id), now, actor)
        return self._shift_offer(self._offer(offer_id), self._now(), actor)

    def apply(self, intervention_id: str, actor: ActorRef) -> Intervention:
        """Apply a coordinator reassignment: re-check routing eligibility now, then record a
        simulated Synapse assignment as a ``workflow``-sourced event (replayed like any
        other event, but distinguishable from imported source data)."""
        require_role(actor, UserRole.COORDINATOR, action="apply consult reassignments")
        actor = with_default_identity(actor)
        deferred: AppError | None = None
        with self._write():
            self._sweep_locked()
            rec = self._record(intervention_id)
            if T(rec.type) is not T.REASSIGN_CONSULT:
                raise ConflictError("Only reassignments are applied.", code="not_applicable")
            if S(rec.status) is not S.PROPOSED:
                raise ConflictError(
                    f"{rec.id} is {rec.status.replace('_', ' ')}; it cannot be applied again.",
                    code="invalid_transition",
                    details={"current_status": rec.status},
                )
            now = self._now()
            plan = rec.reassignment or {}
            consult_id, target = plan.get("consult_id"), plan.get("target_physician_id")
            analysis = self._analysis()
            consult = next(
                (c for c in analysis.state.consultations if c.consult_id == consult_id), None
            )
            if consult is None or not consult.is_open or consult.assigned_physician_id == target:
                why = (
                    f"{consult_id} is already with {plan.get('target_physician_name')}"
                    if consult is not None and consult.assigned_physician_id == target
                    else f"{consult_id} is no longer open"
                )
                transition_intervention(
                    self.session,
                    rec,
                    S.NO_LONGER_REQUIRED,
                    at=now,
                    actor=actor,
                    action="intervention_no_longer_required",
                    summary=f"{rec.id} not applied: {why}.",
                    reason=why,
                )
                deferred = ConflictError(f"Not applied: {why}.", code="no_longer_required")
            else:
                whatif = simulate_intervention(
                    analysis,
                    AssignConsultAction(consult_id=consult_id, physician_id=target),
                    ForecastConfig(self.optimizer.config()),
                )
                if not whatif.allowed:
                    problems = [v.message for v in whatif.violations]
                    write_audit(
                        self.session,
                        at=now,
                        actor=actor,
                        action="apply_blocked",
                        summary=f"{rec.id} not applied; {plan.get('target_physician_name')} is no "
                        "longer eligible: " + "; ".join(problems),
                        entity_type="intervention",
                        entity_id=rec.id,
                        intervention_id=rec.id,
                        details={"problems": problems},
                    )
                    deferred = ConflictError(
                        "Not applied: the target physician no longer passes the routing rules "
                        "at the current data.",
                        code="revalidation_failed",
                        details={"problems": problems},
                    )
                else:
                    event_id = f"WF-{rec.id}-ASSIGN"
                    stamp = now.isoformat()
                    event = normalize_event(
                        {
                            "event_id": event_id,
                            "event_type": KnownEventType.PHYSICIAN_ASSIGNED.value,
                            "event_time": stamp,
                            "ingested_at": stamp,
                            "consult_id": consult_id,
                            "physician_id": target,
                            "hospital_id": consult.hospital_id,
                            "description": f"Reassigned by the coordinator via workflow {rec.id} "
                            "(simulated Synapse action)",
                        },
                        source=EventSource.WORKFLOW,
                        raw={"intervention_id": rec.id},
                    ).event
                    EventRepository(self.session).add([event], import_id=None)
                    bump_data_version(self.session)
                    transition_intervention(
                        self.session,
                        rec,
                        S.COMPLETED,
                        at=now,
                        actor=actor,
                        action="reassignment_applied",
                        summary=f"{consult_id} reassigned from "
                        f"{plan.get('current_physician_name') or 'unassigned'} to "
                        f"{plan.get('target_physician_name')} (workflow event {event_id}).",
                        details={
                            "event_id": event_id,
                            "from": plan.get("current_physician_id"),
                            "to": target,
                            "workload": whatif.workload,
                        },
                    )
        if deferred is not None:
            raise deferred
        return self.get(intervention_id, actor)

    def resolve(self, intervention_id: str, body: ResolveRequest, actor: ActorRef) -> Intervention:
        require_role(
            actor, UserRole.CLINICAL_LEAD, UserRole.COORDINATOR, action="resolve escalations"
        )
        actor = with_default_identity(actor)
        with self._write():
            self._sweep_locked()
            rec = self._record(intervention_id)
            if T(rec.type) is not T.ESCALATION:
                raise ConflictError("Only escalations are resolved.", code="not_applicable")
            transition_intervention(
                self.session,
                rec,
                S.COMPLETED,
                at=self._now(),
                actor=actor,
                action="escalation_resolved",
                summary=f"{actor.actor_id} marked {rec.id} resolved"
                + (f": {body.note}" if body.note else "."),
                reason=body.note,
            )
        return self.get(intervention_id, actor)

    # ------------------------------------------------------------------- reads --

    def _require_staff(self, actor: ActorRef) -> None:
        require_role(
            actor,
            UserRole.COORDINATOR,
            UserRole.CLINICAL_LEAD,
            action="view interventions and the audit log",
        )

    def list_interventions(
        self,
        actor: ActorRef,
        *,
        all_datasets: bool = False,
        statuses: list[str] | None = None,
        types: list[str] | None = None,
    ) -> InterventionPage:
        self._require_staff(actor)
        self.sweep()
        rows = self.repo.list_interventions(
            import_id=self._import_id(), all_datasets=all_datasets, statuses=statuses, types=types
        )
        counts: dict[str, int] = {}
        for r in rows:
            counts[r.status] = counts.get(r.status, 0) + 1
        now = self.sim.current_time() or utc_now()
        return InterventionPage(
            total=len(rows),
            items=[self._to_schema(r, actor, now=now) for r in rows],
            counts_by_status=dict(sorted(counts.items())),
        )

    def get(self, intervention_id: str, actor: ActorRef) -> Intervention:
        self._require_staff(actor)
        rec = self._record(intervention_id)
        return self._to_schema(rec, actor)

    def impact(self, intervention_id: str, actor: ActorRef) -> InterventionImpact:
        self._require_staff(actor)
        self.sweep()
        rec = self._record(intervention_id)
        analysis = self._analysis()
        offers = self.repo.offers_for(rec.id)
        live = [o for o in offers if O(o.status) in (O.ACCEPTED, O.ACTIVE)]
        hospitals = list(
            dict.fromkeys([*rec.hospital_ids, *(h for o in live for h in o.routing_scope)])
        )
        current = self._coverage_impact(
            analysis,
            hospitals,
            "Live forecast now (accepted shifts pending activation are uncertain; active "
            "shifts are confirmed)",
        )
        active = next((o for o in offers if O(o.status) is O.ACTIVE), None)
        trap = TrapAnalysis.model_validate(rec.trap) if rec.trap else None
        routing = None
        notes = []
        if active is not None:
            staffing, internals = self.optimizer.staffing_with_internals(analysis)
            ctx = internals.ctx
            start = active.activated_at or active.start_at
            option = Option(
                index=-1,
                physician_id=active.physician_id,
                name=active.display_name,
                start=active.start_at,
                minutes=active.duration_minutes,
                online_at=max(start, analysis.state.as_of),
                end=active.end_at,
                hospitals=tuple(active.routing_scope),
            )
            joiner = next(
                (p for p in analysis.state.physicians if p.physician_id == active.physician_id),
                None,
            )
            if joiner is not None and option.online_at < option.end:
                protection = protection_for(option, ctx, sorted(joiner.credentialed_hospital_ids))
                protection = protection.model_copy(
                    update={"seeded_consult_count": active.seeded_consult_count}
                )
                trap = trap_analysis(ctx, option, protection)
            dispatch = self.optimizer.dispatch_for(analysis)
            row = next(
                (p for p in dispatch.physicians if p.physician_id == active.physician_id), None
            )
            routed = [
                r.consult_id
                for r in dispatch.plan.recommendations
                if r.physician_id == active.physician_id
            ]
            routing = {
                "physician_id": active.physician_id,
                "display_name": active.display_name,
                "intended_hospital_ids": rec.hospital_ids,
                "authorized_scope_hospital_ids": active.routing_scope,
                "credentialed_hospital_ids": sorted(joiner.credentialed_hospital_ids)
                if joiner
                else [],
                "workload_before_joining": {
                    "actual_consults": 0,
                    "seeded_routing_count": active.seeded_consult_count,
                },
                "consults_this_shift_now": joiner.consults_this_shift if joiner else 0,
                "routing_view": row.model_dump(mode="json") if row else None,
                "current_dispatch_proposals_to_physician": routed,
                "baseline": "Least-loaded routing per the brief's rules 3–4 (unrestricted, raw "
                "zero count) vs the protected policy, on modeled arrivals (see trap).",
                "disclaimer": "Simulated within Sevaro Pulse; this does not change Sevaro's "
                "production routing.",
            }
            notes.append(
                "Trap view is recomputed from the activation time with the seeded count set at "
                "go-live."
            )
        return InterventionImpact(
            intervention_id=rec.id,
            status=S(rec.status),
            proposed=CoverageImpact.model_validate(rec.impact) if rec.impact else None,
            at_activation=next(
                (
                    CoverageImpact.model_validate(o.activation_impact)
                    for o in offers
                    if o.activation_impact
                ),
                None,
            ),
            current=current,
            trap=trap,
            routing=routing,
            notes=notes,
        )

    def audit(
        self,
        actor: ActorRef,
        *,
        intervention_id: str | None = None,
        offer_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> AuditPage:
        self._require_staff(actor)
        total, rows = self.repo.audit(
            intervention_id=intervention_id, offer_id=offer_id, limit=limit, offset=offset
        )
        return AuditPage(
            total=total,
            items=[
                AuditEntry(
                    id=r.id,
                    occurred_at=r.occurred_at,
                    recorded_at=r.recorded_at,
                    actor=ActorRef(role=UserRole(r.actor_role), actor_id=r.actor_id),
                    action=r.action,
                    intervention_id=r.intervention_id,
                    offer_id=r.offer_id,
                    entity_type=r.entity_type,
                    entity_id=r.entity_id,
                    from_status=r.from_status,
                    to_status=r.to_status,
                    summary=r.summary,
                    details=r.details,
                    data_version=r.data_version,
                )
                for r in rows
            ],
        )

    def offers(self, actor: ActorRef) -> OfferPage:
        self._require_staff(actor)
        self.sweep()
        now = self.sim.current_time() or utc_now()
        rows = self.repo.all_offers(self._import_id())
        return OfferPage(total=len(rows), items=[self._shift_offer(o, now, actor) for o in rows])

    def my_offers(self, actor: ActorRef) -> list[PhysicianOfferView]:
        require_role(actor, UserRole.PHYSICIAN, action="view physician offers")
        if not actor.actor_id:
            raise AppError(
                "X-Demo-Actor-Id (the physician's ID) is required.",
                code="actor_required",
                status_code=401,
            )
        self.sweep()
        now = self.sim.current_time() or utc_now()
        hospitals = self._hospitals()
        return [
            self._physician_view(o, now, hospitals)
            for o in self.repo.offers_for_physician(actor.actor_id)
        ]

    def recipients(self) -> list[OfferRecipient]:
        """Simulated sign-in list: off-shift roster physicians plus anyone with offers."""
        reference = ReferenceRepository(self.session).load()
        names = {p.id: p.display_name for p in reference.physicians}
        ids = [p.id for p in reference.physicians if p.roster == "off_shift"]
        counts: dict[str, tuple[int, int]] = {}
        for o in self.repo.all_offers(self._import_id()):
            open_, total = counts.get(o.physician_id, (0, 0))
            counts[o.physician_id] = (open_ + (o.status == O.SENT.value), total + 1)
            if o.physician_id not in ids:
                ids.append(o.physician_id)
        return [
            OfferRecipient(
                physician_id=pid,
                display_name=names.get(pid, pid),
                open_offers=counts.get(pid, (0, 0))[0],
                total_offers=counts.get(pid, (0, 0))[1],
            )
            for pid in ids
        ]

    def summary(self) -> WorkflowSummary:
        state = self.system.get_simulation_state()
        import_id = state.active_import_id if state else None
        rows = self.repo.list_interventions(import_id=import_id) if import_id else []
        offers = self.repo.all_offers(import_id) if import_id else []
        return WorkflowSummary(
            workflow_version=self.repo.workflow_version(),
            data_version=state.data_version if state else 0,
            simulation_time=state.current_time if state and import_id else None,
            pending_approvals=sum(r.status == S.PENDING_APPROVAL.value for r in rows),
            offers_awaiting_response=sum(o.status == O.SENT.value for o in offers),
            accepted_preparing=sum(o.status == O.ACCEPTED.value for o in offers),
            active_split_shifts=sum(o.status == O.ACTIVE.value for o in offers),
            open_interventions=sum(S(r.status) not in TERMINAL_STATUSES for r in rows),
        )

    # ----------------------------------------------------------------- render --

    def _allowed(self, rec: InterventionRecord, role: UserRole) -> list[str]:
        kind, status = T(rec.type), S(rec.status)
        staff = role in (UserRole.COORDINATOR, UserRole.CLINICAL_LEAD)
        actions: list[str] = []
        if (
            role is UserRole.CLINICAL_LEAD
            and status is S.PENDING_APPROVAL
            and kind in (T.SPLIT_SHIFT, T.ESCALATION)
        ):
            actions += ["approve", "reject"]
        if staff and kind is T.SPLIT_SHIFT and status is S.APPROVED:
            actions.append("send_offers")
        if role is UserRole.COORDINATOR and kind is T.REASSIGN_CONSULT and status is S.PROPOSED:
            actions.append("apply")
        if staff and kind is T.ESCALATION and status is S.APPROVED:
            actions.append("resolve")
        if staff and status not in TERMINAL_STATUSES:
            actions.append("cancel")
        return actions

    def _to_schema(
        self,
        rec: InterventionRecord,
        actor: ActorRef,
        *,
        offers: list[OfferRecord] | None = None,
        now: datetime | None = None,
    ) -> Intervention:
        now = now or self.sim.current_time() or utc_now()
        offers = self.repo.offers_for(rec.id) if offers is None else offers
        approval = self.repo.approval_for(rec.id) if rec.id != "PREVIEW" else None
        status = S(rec.status)
        confirmed_cost, confirmed_savings = self._confirmed_cost(rec, offers)
        return Intervention(
            id=rec.id,
            type=T(rec.type),
            status=status,
            status_reason=rec.status_reason,
            title=rec.title,
            rationale=rec.rationale,
            dataset_import_id=rec.dataset_import_id,
            problem=ProblemSnapshot.model_validate(rec.problem),
            recommendation=InterventionRecommendation.model_validate(rec.recommendation),
            candidates=rec.candidates or [],
            offer_plan=rec.offer_plan or [],
            required_physicians=rec.required_physicians,
            reassignment=rec.reassignment,
            escalation=rec.escalation,
            impact=rec.impact,
            trap=rec.trap,
            proposed_by=ActorRef(role=UserRole(rec.proposed_by_role), actor_id=rec.proposed_by_id),
            proposed_at=rec.proposed_at,
            updated_at=rec.updated_at,
            created_data_version=rec.created_data_version,
            version=rec.version,
            approval=ApprovalView(
                id=approval.id,
                decision=approval.decision,  # type: ignore[arg-type]
                decided_by=ActorRef(role=UserRole(approval.actor_role), actor_id=approval.actor_id),
                decided_at=approval.decided_at,
                recorded_at=approval.recorded_at,
                note=approval.note,
                data_version=approval.data_version,
                revalidation=approval.revalidation,
            )
            if approval is not None
            else None,
            offers=[self._shift_offer(o, now, actor) for o in offers],
            allowed_actions=self._allowed(rec, actor.role) if rec.id != "PREVIEW" else [],
            is_terminal=status in TERMINAL_STATUSES,
            confirmed_cost=confirmed_cost,
            confirmed_savings=confirmed_savings,
        )

    def _shift_offer(self, o: OfferRecord, now: datetime, actor: ActorRef) -> ShiftOffer:
        hospitals = self._hospitals()
        status = O(o.status)
        actions: list[str] = []
        if actor.role in (UserRole.COORDINATOR, UserRole.CLINICAL_LEAD):
            if status is O.SENT:
                actions.append("withdraw")
            if status in (O.ACCEPTED, O.ACTIVE):
                actions.append("cancel")
        if actor.role is UserRole.COORDINATOR and status is O.ACCEPTED and now >= o.start_at:
            actions.append("activate")
        return ShiftOffer(
            id=o.id,
            intervention_id=o.intervention_id,
            physician_id=o.physician_id,
            display_name=o.display_name,
            plan_role=o.plan_role,  # type: ignore[arg-type]
            status=status,
            status_reason=o.status_reason,
            hospitals=[
                HospitalRef(id=h, name=hospitals[h].name if h in hospitals else h)
                for h in o.hospital_ids
            ],
            routing_scope_hospital_ids=o.routing_scope,
            seeded_consult_count=o.seeded_consult_count,
            start_at=o.start_at,
            end_at=o.end_at,
            duration_minutes=o.duration_minutes,
            minutes_to_online=o.minutes_to_online,
            reason=o.reason,
            channel=o.channel,
            approved_by=ActorRef(role=UserRole(o.approved_by_role), actor_id=o.approved_by_id),
            sent_by=ActorRef(role=UserRole(o.sent_by_role), actor_id=o.sent_by_id),
            sent_at=o.sent_at,
            expires_at=o.expires_at,
            responded_at=o.responded_at,
            accepted_at=o.accepted_at,
            expected_online_at=o.expected_online_at,
            activated_at=o.activated_at,
            activation_source=o.activation_source,
            ended_at=o.ended_at,
            responses=[
                ResponseView(
                    id=r.id,
                    response=r.response,  # type: ignore[arg-type]
                    outcome=r.outcome,
                    received_at=r.received_at,
                    recorded_at=r.recorded_at,
                    response_seconds=r.response_seconds,
                    detail=r.detail,
                )
                for r in self.repo.responses_for(o.id)
            ],
            allowed_actions=actions,  # type: ignore[arg-type]
        )

    def _physician_view(
        self, o: OfferRecord, now: datetime, hospitals: dict[str, Hospital]
    ) -> PhysicianOfferView:
        status = O(o.status)
        open_ = status is O.SENT and now < o.expires_at
        first = hospitals.get(o.hospital_ids[0]) if o.hospital_ids else None
        zone = first.timezone if first else None
        message = {
            O.SENT: "Reply before the deadline. No patient details are shared in offers.",
            O.ACCEPTED: "Accepted. You are not counted as active capacity until you go online.",
            O.ACTIVE: "You are online for this split shift. Calls reach you only from the "
            "hospitals listed.",
            O.COMPLETED: "Shift completed. Thank you.",
            O.DECLINED: "You declined this offer.",
            O.EXPIRED: "This offer expired without a reply.",
            O.WITHDRAWN: f"Withdrawn: {o.status_reason}." if o.status_reason else "Withdrawn.",
            O.REDUNDANT: "Your acceptance was recorded, but coverage had already been secured. "
            "You are not needed for this shift — no further action.",
            O.CANCELLED: f"Cancelled: {o.status_reason}." if o.status_reason else "Cancelled.",
        }[status]
        return PhysicianOfferView(
            id=o.id,
            status=status,
            status_label=STATUS_LABELS[status],
            hospitals=[
                HospitalRef(id=h, name=hospitals[h].name if h in hospitals else h)
                for h in o.hospital_ids
            ],
            hospital_timezone=zone,
            start_at=o.start_at,
            end_at=o.end_at,
            duration_minutes=o.duration_minutes,
            minutes_to_online=o.minutes_to_online,
            expected_online_at=o.expected_online_at
            or (max(o.start_at, now) + timedelta(minutes=o.minutes_to_online)),
            reason=o.reason,
            sent_at=o.sent_at,
            expires_at=o.expires_at,
            responded_at=o.responded_at,
            activated_at=o.activated_at,
            can_accept=open_,
            can_decline=open_,
            can_go_online=status is O.ACCEPTED and now >= o.start_at,
            message=message,
        )
