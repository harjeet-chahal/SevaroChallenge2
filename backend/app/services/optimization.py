"""Phase 4 recommendations on top of the cached Phase 3 analysis. Read-only.

Nothing here writes to the database: no assignment, offer or staffing change is made.
Phase 5 inputs are read, not written: the analysis includes accepted/activated split
shifts (workflow overlay) and the staffing rules use the workflow's offer log.
Results are cached per (data_version, as_of, risk-rules signature, optimizer-policy
signature, parameters), so a new event, an import, a clock move or a policy change always
recomputes. The solvers are deterministic (single worker, fixed seed), so a cache hit and
a recomputation return the same answer.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.engines.analysis import OperationalAnalysis
from app.engines.interventions import WorkflowPolicy
from app.engines.optimization import (
    ForecastConfig,
    OptimizationConfig,
    SolverUnavailableError,
    dispatch_section,
    load_optimization_config,
    ortools_version,
    run_dispatch,
    run_staffing,
    simulate_intervention,
    staffing_section,
    trap_section,
)
from app.repositories.workflow import WorkflowRepository
from app.schemas.dispatch import DispatchResult
from app.schemas.staffing import StaffingResult
from app.schemas.whatif import OptimizationComparison, SimulateRequest, WhatIfResult
from app.services.analysis import AnalysisCache, AnalysisService


class OptimizerUnavailableError(AppError):
    status_code = 503
    code = "optimizer_unavailable"


class OptimizationService:
    def __init__(
        self,
        session: Session,
        settings: Settings,
        analysis_cache: AnalysisCache,
        cache: AnalysisCache,
    ) -> None:
        self.session = session
        self.settings = settings
        self.cache = cache
        self.analyses = AnalysisService(session, settings, analysis_cache)

    def config(self) -> OptimizationConfig:
        return load_optimization_config(self.settings.resolved_optimization_policy_file)

    def _analysis(self, as_of: datetime | None) -> OperationalAnalysis:
        return self.analyses.analysis(as_of)

    def _key(self, kind: str, analysis: OperationalAnalysis, cfg: OptimizationConfig) -> tuple:
        return (
            kind,
            analysis.state.data_version,
            analysis.state.as_of.isoformat(),
            analysis.config.signature(),
            analysis.coverage.horizon_minutes,
            cfg.signature(),
        )

    def _cached(self, key: tuple, compute):
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        try:
            value = compute()
        except SolverUnavailableError as exc:
            raise OptimizerUnavailableError(
                f"{exc}. Install the backend requirements (ortools) or allow the labelled "
                "fallback (solver.allow_fallback).",
                details={"ortools_version": ortools_version()},
            ) from exc
        self.cache.put(key, value)
        return value

    def _dispatch(self, analysis: OperationalAnalysis, cfg: OptimizationConfig):
        return self._cached(
            self._key("dispatch", analysis, cfg), lambda: run_dispatch(analysis, cfg)
        )

    def _staffing(self, analysis: OperationalAnalysis, cfg: OptimizationConfig):
        # Notification limits come from the workflow's offer log, which changes without a
        # data-version bump (e.g. an offer sent or declined): key on the workflow version.
        workflow = WorkflowRepository(self.session)
        key = (*self._key("staffing", analysis, cfg), workflow.workflow_version())
        window = WorkflowPolicy().week_window
        return self._cached(
            key,
            lambda: run_staffing(
                analysis, cfg, offer_log=workflow.offer_log(analysis.state.as_of, window)
            ),
        )

    def staffing_with_internals(self, analysis: OperationalAnalysis):
        """(StaffingResult, StaffingInternals) for the workflow service's revalidation."""
        return self._staffing(analysis, self.config())

    def dispatch_for(self, analysis: OperationalAnalysis) -> DispatchResult:
        return self._dispatch(analysis, self.config())[0]

    def assignments(self, as_of: datetime | None = None) -> DispatchResult:
        cfg = self.config()
        return self._dispatch(self._analysis(as_of), cfg)[0]

    def split_shifts(self, as_of: datetime | None = None) -> StaffingResult:
        cfg = self.config()
        return self._staffing(self._analysis(as_of), cfg)[0]

    def comparison(self, as_of: datetime | None = None) -> OptimizationComparison:
        cfg = self.config()
        analysis = self._analysis(as_of)
        dispatch, baseline, problem = self._dispatch(analysis, cfg)
        staffing, internals = self._staffing(analysis, cfg)
        coverage_pm = round(
            sum(h.metrics.deficit_physician_minutes for h in analysis.coverage.hospitals), 4
        )
        return OptimizationComparison(
            as_of=analysis.state.as_of,
            data_version=analysis.state.data_version,
            policy_version=cfg.policy_version,
            dispatch=dispatch_section(dispatch, baseline, problem, coverage_pm),
            staffing=staffing_section(staffing, internals),
            trap=trap_section(staffing),
            solvers=[dispatch.solver, staffing.solver],
            notes=[
                "Both methods in each section use the same snapshot and the same hard "
                "constraints; only the decision rule differs.",
                "Figures are modeled from schedules, credentials and signals, not measured "
                "outcomes. Ties and cases where the baseline is better are reported as such.",
            ],
        )

    def simulate(self, request: SimulateRequest) -> WhatIfResult:
        cfg = self.config()
        analysis = self._analysis(request.as_of)
        try:
            return simulate_intervention(
                analysis,
                request.action,
                ForecastConfig(optimization=cfg, horizon_minutes=request.horizon_minutes),
            )
        except SolverUnavailableError as exc:  # pragma: no cover - simulate needs no solver
            raise OptimizerUnavailableError(str(exc)) from exc
