"""Phase 3 read-only analysis endpoints. All default to the simulation clock; ``as_of``
reconstructs and analyses any other time without moving the clock."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import AppSettings, Cache, DbSession
from app.core.errors import NotFoundError
from app.engines.optimization_input import build_optimization_input
from app.schemas.alert import Alert, AlertList, RuleCode
from app.schemas.common import Severity
from app.schemas.coverage import CoverageReport, HospitalCoverage
from app.schemas.demand import DemandReport
from app.schemas.metrics import OperationalMetrics
from app.schemas.optimization import OptimizationInput
from app.schemas.simulation import SupportedDatetime
from app.services.analysis import AnalysisService
from app.services.triage import AlertTriage

router = APIRouter(tags=["analysis"])

AsOf = Annotated[
    SupportedDatetime | None,
    Query(
        description="Analyse at this time (ISO-8601 with offset). Defaults to the simulation clock."
    ),
]
Horizon = Annotated[
    int | None, Query(ge=90, le=720, description="Forecast horizon, minutes (≥ 90)")
]
Step = Annotated[int | None, Query(ge=1, le=60, description="Chart sample interval, minutes")]


@router.get("/alerts", response_model=AlertList, summary="Ranked operational alerts")
def list_alerts(
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    as_of: AsOf = None,
    severity: Severity | None = None,
    rule_code: RuleCode | None = None,
    hospital_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> AlertList:
    result = AlertTriage(db).alerts(AnalysisService(db, settings, cache).analysis(as_of).alerts)
    alerts = [
        a
        for a in result.alerts
        if (severity is None or a.severity is severity)
        and (rule_code is None or a.rule_code is rule_code)
        and (hospital_id is None or a.hospital_id == hospital_id)
    ]
    return result.model_copy(update={"alerts": alerts[:limit]})


@router.get("/alerts/{alert_id}", response_model=Alert)
def get_alert(
    db: DbSession, settings: AppSettings, cache: Cache, alert_id: str, as_of: AsOf = None
) -> Alert:
    analysis = AnalysisService(db, settings, cache).analysis(as_of)
    for alert in AlertTriage(db).alerts(analysis.alerts).alerts:
        if alert.alert_id == alert_id:
            return alert
    raise NotFoundError(f"Alert '{alert_id}' is not active at this time")


@router.get("/coverage", response_model=CoverageReport, summary="Coverage now and projected")
def coverage(
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    as_of: AsOf = None,
    horizon_minutes: Horizon = None,
    step_minutes: Step = None,
) -> CoverageReport:
    return (
        AnalysisService(db, settings, cache)
        .analysis(as_of, horizon_minutes=horizon_minutes, step_minutes=step_minutes)
        .coverage
    )


@router.get("/coverage/{hospital_id}", response_model=HospitalCoverage)
def hospital_coverage(
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    hospital_id: str,
    as_of: AsOf = None,
    horizon_minutes: Horizon = None,
    step_minutes: Step = None,
) -> HospitalCoverage:
    report = (
        AnalysisService(db, settings, cache)
        .analysis(as_of, horizon_minutes=horizon_minutes, step_minutes=step_minutes)
        .coverage
    )
    for h in report.hospitals:
        if h.hospital_id == hospital_id:
            return h
    raise NotFoundError(f"Hospital '{hospital_id}' not found")


@router.get("/demand", response_model=DemandReport, summary="Arrivals vs hourly p90 baselines")
def demand(db: DbSession, settings: AppSettings, cache: Cache, as_of: AsOf = None) -> DemandReport:
    return AnalysisService(db, settings, cache).analysis(as_of).demand


@router.get("/metrics", response_model=OperationalMetrics, summary="Operational summary metrics")
def metrics(
    db: DbSession, settings: AppSettings, cache: Cache, as_of: AsOf = None
) -> OperationalMetrics:
    analysis = AnalysisService(db, settings, cache).analysis(as_of)
    return AlertTriage(db).metrics(analysis.metrics, analysis.alerts)


@router.get(
    "/optimization/input",
    response_model=OptimizationInput,
    summary="Optimizer-ready snapshot for Phase 4 (read-only data; nothing is assigned)",
)
def optimization_input(
    db: DbSession, settings: AppSettings, cache: Cache, as_of: AsOf = None
) -> OptimizationInput:
    return build_optimization_input(AnalysisService(db, settings, cache).analysis(as_of))
