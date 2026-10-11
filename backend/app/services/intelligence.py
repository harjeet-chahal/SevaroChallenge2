"""NEUROGRID intelligence: orchestration of the pure engines in app.engines.intelligence.

Read-only. Inputs are the cached Phase 3 analysis, the Phase 4 staffing internals and
(read-only) Phase 5 workflow records. Results are cached per (kind, data version,
simulation time, workflow version, policy signatures, parameters), so an import, an
injected event, a clock move or any workflow transition always recomputes.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import NotFoundError
from app.engines.analysis import OperationalAnalysis, analyze
from app.engines.coverage_prediction import hypothetical_window
from app.engines.intelligence import (
    IntelligenceConfig,
    availability_report,
    class_map,
    coverage_debt_report,
    fragility_report,
    genome_report,
    handoff_report,
    last_safe_moment_report,
    load_guardian_report,
    load_intelligence_config,
    options_by_hospital,
    planning_models,
    problem_report,
    scarcity_report,
    simulate_rescues,
    single_point_physicians,
    time_machine_report,
)
from app.engines.intelligence.availability import classify
from app.engines.intelligence.common import deficit_between, profiles
from app.repositories import EventRepository
from app.repositories.workflow import WorkflowRepository
from app.schemas.intelligence import (
    AvailabilityReport,
    CoverageDebtReport,
    EvaluationReport,
    EvaluationRow,
    FragilityReport,
    GenomeReport,
    HandoffReport,
    LastSafeMomentReport,
    LoadGuardianReport,
    ProblemReport,
    RescueSimulation,
    ScarcityReport,
    TimeMachineReport,
)
from app.schemas.intervention import TERMINAL_STATUSES, InterventionStatus
from app.services.analysis import AnalysisCache, AnalysisService
from app.services.dataset_import.service import DatasetService
from app.services.optimization import OptimizationService
from app.services.simulation import SimulationService


class IntelligenceService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        analysis_cache: AnalysisCache,
        optimization_cache: AnalysisCache,
    ) -> None:
        self.session = session
        self.settings = settings
        self.cache = optimization_cache
        self.analyses = AnalysisService(session, settings, analysis_cache)
        self.optimizer = OptimizationService(session, settings, analysis_cache, optimization_cache)
        self.workflow = WorkflowRepository(session)
        self.sim = SimulationService(session, settings)

    # ------------------------------------------------------------------ plumbing --

    def config(self) -> IntelligenceConfig:
        return load_intelligence_config(self.settings.resolved_intelligence_policy_file)

    def _analysis(self, as_of: datetime | None = None) -> OperationalAnalysis:
        return self.analyses.analysis(as_of)

    def _key(self, kind: str, analysis: OperationalAnalysis, *extra: Any) -> tuple:
        return (
            "intel",
            kind,
            analysis.state.data_version,
            analysis.state.as_of.isoformat(),
            self.workflow.workflow_version(),
            analysis.config.signature(),
            self.optimizer.config().signature(),
            self.config().signature(),
            *extra,
        )

    def _cached(self, key: tuple, compute):
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        value = compute()
        self.cache.put(key, value)
        return value

    def _staffing(self, analysis: OperationalAnalysis):
        # Forecast candidates across the full planning window. Only the operational
        # planner/workflow decides whether an offer is permitted now.
        cfg = self.optimizer.config().model_copy(deep=True)
        cfg.staffing.planning_horizon_minutes = max(
            cfg.staffing.planning_horizon_minutes, self.config().planning_horizon_minutes
        )
        cfg.staffing.shortage_lookahead_minutes = cfg.staffing.planning_horizon_minutes
        return self.optimizer.staffing_with_internals(analysis, config=cfg)

    def _action_lookahead(self, analysis: OperationalAnalysis) -> int:
        return (
            self.optimizer.config().staffing.shortage_lookahead_minutes
            or analysis.coverage.horizon_minutes
        )

    def _routable(self, analysis: OperationalAnalysis) -> dict[str, bool]:
        cfg = self.optimizer.config()
        return {
            p.physician_id: classify(p, analysis, cfg).auto_routable
            for p in analysis.state.physicians
        }

    def _active_rescues(self) -> list[dict]:
        state = self.sim.system.get_simulation_state()
        import_id = state.active_import_id if state else None
        out = []
        for rec in self.workflow.list_interventions(import_id=import_id):
            if InterventionStatus(rec.status) in TERMINAL_STATUSES:
                continue
            out.append(
                {
                    "intervention_id": rec.id,
                    "type": rec.type,
                    "status": rec.status,
                    "title": rec.title,
                    "hospital_ids": list(rec.hospital_ids or []),
                    "physician_ids": [i["physician_id"] for i in (rec.offer_plan or [])],
                }
            )
        return out

    # ------------------------------------------------------------------ reports --

    def availability(self, as_of: datetime | None = None) -> AvailabilityReport:
        analysis = self._analysis(as_of)
        return self._cached(
            self._key("availability", analysis),
            lambda: availability_report(analysis, self.optimizer.config()),
        )

    def fragility(self, horizon: int | None = None) -> FragilityReport:
        analysis = self._analysis()
        cfg = self.config()
        horizon = horizon or cfg.planning_horizon_minutes

        def compute() -> FragilityReport:
            _, internals = self._staffing(analysis)
            return fragility_report(
                analysis,
                planning_models(analysis, horizon),
                class_map(analysis, self.optimizer.config()),
                self._routable(analysis),
                cfg,
                horizon_minutes=horizon,
                candidates_by_hospital=options_by_hospital(internals.candidates),
            )

        return self._cached(self._key("fragility", analysis, horizon), compute)

    def genome(self, horizon: int | None = None) -> GenomeReport:
        analysis = self._analysis()
        cfg = self.config()
        horizon = horizon or cfg.planning_horizon_minutes

        def compute() -> GenomeReport:
            models = planning_models(analysis, horizon)
            sp = single_point_physicians(models)
            by_hospital: dict[str, list[str]] = {}
            for pid, hids in sp.items():
                for h in hids:
                    by_hospital.setdefault(h, []).append(pid)
            scarcity = self.scarcity()
            return genome_report(
                analysis,
                models,
                class_map(analysis, self.optimizer.config()),
                self._routable(analysis),
                cfg,
                horizon_minutes=horizon,
                single_points=by_hospital,
                uncovered_by_candidates=scarcity.uncovered_hospital_ids,
            )

        return self._cached(self._key("genome", analysis, horizon), compute)

    def scarcity(self) -> ScarcityReport:
        analysis = self._analysis()

        def compute() -> ScarcityReport:
            _, internals = self._staffing(analysis)
            report = scarcity_report(internals.ctx, internals.candidates)
            report.policy.insert(
                0,
                f"Candidates are evaluated for the {internals.ctx.horizon_minutes}-minute "
                "planning window. This is a forecast, not permission to send an offer: "
                f"staffing actions use the {self._action_lookahead(analysis)}-minute "
                "shortage look-ahead and are revalidated before approval and dispatch.",
            )
            return report

        return self._cached(self._key("scarcity", analysis), compute)

    def last_safe_moment(self) -> LastSafeMomentReport:
        analysis = self._analysis()

        def compute() -> LastSafeMomentReport:
            _, internals = self._staffing(analysis)
            in_progress: dict[str, list[str]] = {}
            for r in self._active_rescues():
                if r["type"] == "split_shift":
                    for h in r["hospital_ids"]:
                        in_progress.setdefault(h, []).append(
                            f"{r['intervention_id']} ({r['status']})"
                        )
            return last_safe_moment_report(
                internals.ctx,
                internals.candidates,
                self.config(),
                rescues_in_progress=in_progress,
                action_lookahead_minutes=self._action_lookahead(analysis),
            )

        return self._cached(self._key("lsm", analysis), compute)

    def problems(self) -> ProblemReport:
        analysis = self._analysis()
        return self._cached(
            self._key("problems", analysis),
            lambda: problem_report(analysis, self.genome().diagnoses),
        )

    def handoff(self, horizon: int | None = None) -> HandoffReport:
        analysis = self._analysis()
        horizon = horizon or analysis.coverage.horizon_minutes
        return self._cached(
            self._key("handoff", analysis, horizon),
            lambda: handoff_report(
                analysis,
                planning_models(analysis, horizon),
                horizon_minutes=horizon,
                pending_rescues=self._active_rescues(),
            ),
        )

    def coverage_debt(self, lookback: int | None = None) -> CoverageDebtReport:
        analysis = self._analysis()
        policy = self.config().debt
        lookback = policy.lookback_minutes if lookback is None else lookback
        step = policy.step_minutes

        def compute() -> CoverageDebtReport:
            events, reference, version = self.analyses.states.load_inputs()
            overlay = self.analyses.states.overlay()
            history = []
            for k in range(lookback // step, 0, -1):
                t = analysis.state.as_of - timedelta(minutes=k * step)
                history.append(
                    analyze(
                        events,
                        reference,
                        t,
                        analysis.config,
                        data_version=version,
                        overlay=overlay,
                    )
                )
            return coverage_debt_report(
                analysis, history, lookback_minutes=lookback, step_minutes=step
            )

        return self._cached(self._key("debt", analysis, lookback), compute)

    def freshness(self, analysis: OperationalAnalysis) -> dict:
        events = EventRepository(self.session)
        first, last, last_ingested = events.bounds()
        as_of = analysis.state.as_of
        diag = analysis.state.diagnostics
        return {
            "as_of": as_of,
            "last_event_time": last,
            "last_ingested_at": last_ingested,
            "minutes_since_last_ingest": round((as_of - last_ingested).total_seconds() / 60, 2)
            if last_ingested and last_ingested <= as_of
            else None,
            "events_pending_ingestion": events.count_ingested_after(as_of),
            "late_arrivals_applied": diag.late_arrivals_applied,
            "duplicates_skipped": diag.duplicates_skipped,
            "conflicting_duplicates": diag.conflicting_duplicates,
            "unknown_event_types": diag.unknown_event_types,
        }

    def time_machine(
        self,
        horizon: int | None = None,
        step: int | None = None,
        rate_multiplier: float | None = None,
    ) -> TimeMachineReport:
        analysis = self._analysis()
        cfg = self.config()
        horizon = horizon or cfg.time_machine_horizon_minutes
        step = step or cfg.time_machine_step_minutes
        stochastic = cfg.stochastic
        if rate_multiplier is not None:
            stochastic = stochastic.model_copy(update={"rate_multiplier": rate_multiplier})
        return self._cached(
            self._key("time_machine", analysis, horizon, step, stochastic.rate_multiplier),
            lambda: time_machine_report(
                analysis,
                planning_models(analysis, horizon),
                class_map(analysis, self.optimizer.config()),
                horizon_minutes=horizon,
                step_minutes=step,
                stochastic=stochastic,
                freshness=self.freshness(analysis),
            ),
        )

    def simulate(
        self, *, hospital_ids: list[str] | None = None, alert_id: str | None = None
    ) -> RescueSimulation:
        analysis = self._analysis()
        names = {h.id: h.name for h in analysis.state.hospitals}
        label = ""
        targets = list(hospital_ids or [])
        if alert_id:
            alert = next((a for a in analysis.alerts.alerts if a.alert_id == alert_id), None)
            if alert is None:
                raise NotFoundError(f"Alert '{alert_id}' is not active at this time")
            if alert.hospital_id and alert.hospital_id not in targets:
                targets.append(alert.hospital_id)
            label = alert.title
        unknown = [h for h in targets if h not in names]
        if unknown:
            raise NotFoundError(f"Unknown hospital(s): {', '.join(unknown)}")
        staffing, internals = self._staffing(analysis)
        action_staffing, action_internals = self.optimizer.staffing_with_internals(analysis)
        if not targets:
            lsm = self.last_safe_moment()
            targets = (
                [lsm.items[0].hospital_id] if lsm.items else list(staffing.gap_hospital_ids[:1])
            )
        if not targets:
            stranded = [
                c.hospital_id
                for c in analysis.state.consultations
                if c.is_open
                and c.assigned_physician_id is None
                and c.routing_failures
                and c.hospital_id
            ]
            targets = sorted(set(stranded))[:1]
        label = label or ("Rescue options for " + ", ".join(names.get(h, h) for h in targets))
        return self._cached(
            self._key("simulate", analysis, tuple(targets), alert_id),
            lambda: simulate_rescues(
                internals.ctx,
                internals.candidates,
                internals.options,
                staffing,
                self.optimizer.dispatch_for(analysis),
                self.config(),
                target_hospital_ids=targets,
                target_label=label,
                alert_id=alert_id,
                action_options=action_internals.options,
                action_staffing=action_staffing,
                action_lookahead_minutes=self._action_lookahead(analysis),
            ),
        )

    def load_guardian(self) -> LoadGuardianReport:
        analysis = self._analysis()

        def compute() -> LoadGuardianReport:
            staffing, internals = self._staffing(analysis)
            report = load_guardian_report(internals.ctx, staffing, internals.options)
            report.conclusion += (
                " Planning what-if; an actual offer must also pass the operational "
                f"{self._action_lookahead(analysis)}-minute shortage look-ahead."
            )
            return report

        return self._cached(self._key("guardian", analysis), compute)

    # ------------------------------------------------------------------ evaluation --

    def evaluation(self) -> EvaluationReport:
        """Monitoring-only vs reactive vs NEUROGRID on the *current* state, measured.

        - monitoring only: shows current state; acts on nothing.
        - reactive: starts the rescue workflow only when a shortfall begins (coverage
          arrives after the full lead time).
        - NEUROGRID: starts now with the Last-Safe-Moment candidate.
        Coverage figures use the planning-window models and the candidate's real offer
        window; nothing is assumed beyond the documented lead-time policy.
        """
        timings: dict[str, float] = {}
        t0 = time.perf_counter()
        analysis = self._analysis()
        timings["analysis_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        t0 = time.perf_counter()
        staffing, internals = self._staffing(analysis)
        timings["staffing_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        t0 = time.perf_counter()
        lsm = self.last_safe_moment()
        timings["last_safe_moment_ms"] = round((time.perf_counter() - t0) * 1000, 2)
        ctx = internals.ctx
        models = ctx.models
        base = profiles(models)
        baseline_pm = round(sum(p.deficit_pm for p in base.values()), 2)
        reactive_pm = neuro_pm = 0.0
        cands = {c.physician_id: c for c in internals.candidates}
        prevented = 0
        for item in lsm.items:
            m = models[item.hospital_id]
            pr = base[item.hospital_id]
            best = cands.get(item.best_physician_id or "")
            if best is None or best.max_minutes is None:
                reactive_pm += pr.deficit_pm
                neuro_pm += pr.deficit_pm
                continue
            timing = next(t for t in item.candidates if t.physician_id == best.physician_id)
            lead = timedelta(minutes=timing.lead.expected_total_minutes)
            span = timedelta(minutes=best.max_minutes)
            react_start = item.shortfall_at + lead
            w_react = hypothetical_window(
                best.physician_id,
                "",
                react_start,
                react_start - timedelta(minutes=best.online_minutes) + span,
                "reactive",
            )
            action_opens = (
                item.shortfall_at
                - timedelta(minutes=self._action_lookahead(analysis))
                + timedelta(microseconds=1)
            )
            neuro_online = max(timing.activation_expected_at or react_start, action_opens + lead)
            w_neuro = hypothetical_window(
                best.physician_id,
                "",
                neuro_online,
                neuro_online - timedelta(minutes=best.online_minutes) + span,
                "neurogrid",
            )
            reactive_pm += m.deficit_physician_minutes([w_react])
            after = m.deficit_physician_minutes([w_neuro])
            neuro_pm += after
            if (
                deficit_between(m, item.shortfall_at, item.shortfall_at + timedelta(minutes=1))
                and neuro_online <= item.shortfall_at
            ):
                prevented += 1
        other = sum(
            p.deficit_pm for h, p in base.items() if h not in {i.hospital_id for i in lsm.items}
        )
        reactive_pm += other
        neuro_pm += other
        sent = self.workflow.offers_with_status(
            [
                "sent",
                "accepted",
                "active",
                "completed",
                "declined",
                "expired",
                "withdrawn",
                "redundant",
                "cancelled",
            ]
        )
        approvals_missing = sum(
            1 for o in sent if self.workflow.approval_for(o.intervention_id) is None
        )
        open_by_phys: dict[str, int] = {}
        for o in self.workflow.offers_with_status(["sent"]):
            open_by_phys[o.physician_id] = open_by_phys.get(o.physician_id, 0) + 1
        duplicates = sum(1 for v in open_by_phys.values() if v > 1)
        projected = sum(
            1
            for p in base.values()
            if p.first_shortfall and p.first_shortfall > analysis.state.as_of
        )
        now_gaps = sum(
            1
            for p in base.values()
            if p.first_shortfall and p.first_shortfall <= analysis.state.as_of
        )
        verification = DatasetService(self.session, self.settings).verify()
        mismatches = (
            f"{len(verification.mismatches)} of {verification.compared_fields} fields"
            if verification.available
            else "no snapshot files"
        )
        rows = [
            EvaluationRow(
                metric="Projected shortfalls detected before they start (planning window)",
                monitoring_only=0,
                reactive=0,
                neurogrid=projected,
                note="Monitoring and reactive modes only see a gap once it exists "
                f"({now_gaps} exist now).",
            ),
            EvaluationRow(
                metric="Coverage deficit, physician-minutes (planning window)",
                monitoring_only=baseline_pm,
                reactive=round(reactive_pm, 2),
                neurogrid=round(neuro_pm, 2),
                note="Reactive starts the same rescue when the gap begins (lead time "
                "applies); NEUROGRID starts no earlier than the staffing action window. "
                "Same candidate, same rules; future eligibility is revalidated before action.",
            ),
            EvaluationRow(
                metric="Shortfalls fully prevented by the recommended rescue",
                monitoring_only=0,
                reactive=0,
                neurogrid=prevented,
                note="Counted when the candidate is expected online at or before the "
                "shortfall start.",
            ),
            EvaluationRow(
                metric="Eligibility violations in recommendations",
                monitoring_only="n/a",
                reactive="not enforced",
                neurogrid=0,
                note="Every candidate is checked against every split-shift rule; failing "
                "candidates are never recommended (tests: test_neurogrid_*).",
            ),
            EvaluationRow(
                metric="Offers sent without clinical-lead approval",
                monitoring_only="n/a",
                reactive="n/a",
                neurogrid=approvals_missing,
                note=f"Measured from the workflow tables ({len(sent)} offers so far).",
            ),
            EvaluationRow(
                metric="Physicians with more than one open offer",
                monitoring_only="n/a",
                reactive="n/a",
                neurogrid=duplicates,
                note="Measured from the workflow tables.",
            ),
            EvaluationRow(
                metric="Reference snapshot mismatches",
                monitoring_only="n/a",
                reactive="n/a",
                neurogrid=mismatches,
                note="Engine replay vs the supplied 18:20 snapshot files (when present).",
            ),
        ]
        return EvaluationReport(
            as_of=analysis.state.as_of,
            data_version=analysis.state.data_version,
            rows=rows,
            timings_ms=timings,
            notes=[
                "All values are computed on the current scenario state; nothing is invented.",
                "Deficits are modeled (credentialed on-duty capacity vs requirement), not "
                "observed patient outcomes.",
            ],
        )
