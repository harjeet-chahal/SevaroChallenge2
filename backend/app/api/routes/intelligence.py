"""NEUROGRID intelligence endpoints (read-only analyses, rescue contracts, chaos lab).

Analyses default to the simulation clock and recompute whenever the data version, the
clock or the workflow version changes. Nothing here writes operational state, except
``POST /rescue-contracts/{id}/verify`` (one audit entry) and the import ``apply`` path,
which is the existing ``POST /api/events/csv``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Query, UploadFile

from app.api.deps import AppSettings, Cache, DbSession, DemoActor, OptCache
from app.core.errors import AppError
from app.schemas.intelligence import (
    AvailabilityReport,
    ChaosResult,
    ChaosScenarioInfo,
    ContractVerification,
    CoverageDebtReport,
    EvaluationReport,
    FragilityReport,
    GenomeReport,
    HandoffReport,
    ImportPreview,
    LastSafeMomentReport,
    LoadGuardianReport,
    ProblemReport,
    RescueSimulation,
    ScarcityReport,
    TimeMachineReport,
)
from app.services.chaos import ChaosService
from app.services.import_preview import preview_csv
from app.services.intelligence import IntelligenceService
from app.services.rescue_contracts import RescueContractService

router = APIRouter(tags=["neurogrid"])

Horizon = Annotated[int | None, Query(ge=90, le=720, description="Horizon, minutes (≥ 90)")]


def _svc(db, settings, cache, opt) -> IntelligenceService:
    return IntelligenceService(db, settings, cache, opt)


@router.get("/intelligence/availability", response_model=AvailabilityReport)
def availability(db: DbSession, settings: AppSettings, cache: Cache, opt: OptCache):
    """NEUROGRID availability classes with evidence, per physician."""
    return _svc(db, settings, cache, opt).availability()


@router.get("/intelligence/problems", response_model=ProblemReport)
def problems(db: DbSession, settings: AppSettings, cache: Cache, opt: OptCache):
    """Alerts grouped by root problem (deterministic fingerprints), tiered priority."""
    return _svc(db, settings, cache, opt).problems()


@router.get("/intelligence/time-machine", response_model=TimeMachineReport)
def time_machine(
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt: OptCache,
    horizon_minutes: Horizon = None,
    step_minutes: Annotated[int | None, Query(ge=1, le=30)] = None,
    rate_multiplier: Annotated[float | None, Query(gt=0, le=10)] = None,
):
    """Projected coverage frames, shift lanes and stochastic demand bands."""
    return _svc(db, settings, cache, opt).time_machine(
        horizon_minutes, step_minutes, rate_multiplier
    )


@router.get("/intelligence/last-safe-moment", response_model=LastSafeMomentReport)
def last_safe_moment(db: DbSession, settings: AppSettings, cache: Cache, opt: OptCache):
    """Latest time to start each rescue so the physician is online before the gap."""
    return _svc(db, settings, cache, opt).last_safe_moment()


@router.get("/intelligence/fragility", response_model=FragilityReport)
def fragility(
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt: OptCache,
    horizon_minutes: Horizon = None,
):
    """Credentialing graph, single-point failures, exclusive allocation, multi-failures."""
    return _svc(db, settings, cache, opt).fragility(horizon_minutes)


@router.get("/intelligence/genome", response_model=GenomeReport)
def genome(
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt: OptCache,
    horizon_minutes: Horizon = None,
):
    """Root-cause diagnosis of every projected shortfall and unroutable consult."""
    return _svc(db, settings, cache, opt).genome(horizon_minutes)


@router.get("/intelligence/scarcity", response_model=ScarcityReport)
def scarcity(db: DbSession, settings: AppSettings, cache: Cache, opt: OptCache):
    """How replaceable each off-shift backup is."""
    return _svc(db, settings, cache, opt).scarcity()


@router.get("/intelligence/coverage-debt", response_model=CoverageDebtReport)
def coverage_debt(
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt: OptCache,
    lookback_minutes: Annotated[int | None, Query(ge=0, le=720)] = None,
):
    """Accumulated uncovered physician-minutes: reconstructed history and projection."""
    return _svc(db, settings, cache, opt).coverage_debt(lookback_minutes)


@router.get("/intelligence/handoff", response_model=HandoffReport)
def handoff(
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt: OptCache,
    horizon_minutes: Horizon = None,
):
    """Departing/arriving physicians, open work and upcoming deadlines."""
    return _svc(db, settings, cache, opt).handoff(horizon_minutes)


@router.get("/intelligence/simulate", response_model=RescueSimulation)
def simulate(
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt: OptCache,
    hospital_id: Annotated[list[str] | None, Query()] = None,
    alert_id: str | None = None,
):
    """Rescue Impact Simulator: every option side by side on isolated copies."""
    return _svc(db, settings, cache, opt).simulate(hospital_ids=hospital_id, alert_id=alert_id)


@router.get("/intelligence/load-guardian", response_model=LoadGuardianReport)
def load_guardian(db: DbSession, settings: AppSettings, cache: Cache, opt: OptCache):
    """Physician Load Guardian: protected vs unrestricted routing for a joiner."""
    return _svc(db, settings, cache, opt).load_guardian()


@router.get("/intelligence/evaluation", response_model=EvaluationReport)
def evaluation(db: DbSession, settings: AppSettings, cache: Cache, opt: OptCache):
    """Monitoring-only vs reactive vs NEUROGRID, measured on the current state."""
    return _svc(db, settings, cache, opt).evaluation()


# ---------------------------------------------------------------- rescue contracts --


@router.get("/rescue-contracts/phases", response_model=dict[str, str])
def contract_phases(
    db: DbSession, settings: AppSettings, cache: Cache, opt: OptCache, actor: DemoActor
):
    """Contract phase for every intervention of the active dataset."""
    return RescueContractService(db, settings, cache, opt).phases(actor)


@router.get("/rescue-contracts/{intervention_id}/verification", response_model=ContractVerification)
def contract_verification(
    intervention_id: str,
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt: OptCache,
    actor: DemoActor,
):
    """Recompute whether the contract's success condition holds now (no write)."""
    return RescueContractService(db, settings, cache, opt).verify(
        intervention_id, actor, record=False
    )


@router.post("/rescue-contracts/{intervention_id}/verify", response_model=ContractVerification)
def contract_verify(
    intervention_id: str,
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt: OptCache,
    actor: DemoActor,
):
    """Verify and record the result in the audit log."""
    return RescueContractService(db, settings, cache, opt).verify(
        intervention_id, actor, record=True
    )


# ---------------------------------------------------------------- chaos lab --


@router.get("/chaos/scenarios", response_model=list[ChaosScenarioInfo])
def chaos_scenarios(db: DbSession, settings: AppSettings):
    return ChaosService(db, settings).scenarios()


@router.post("/chaos/run/{scenario_id}", response_model=ChaosResult)
def chaos_run(scenario_id: str, db: DbSession, settings: AppSettings, actor: DemoActor):
    """Run one scenario on an isolated branch. The baseline is never written."""
    if actor.role.value not in ("coordinator", "clinical_lead"):
        raise AppError("Chaos Lab is for operations staff.", code="forbidden", status_code=403)
    return ChaosService(db, settings).run(scenario_id)


# ---------------------------------------------------------------- import preview --


@router.post("/events/csv/preview", response_model=ImportPreview)
async def import_preview(
    db: DbSession,
    settings: AppSettings,
    file: Annotated[UploadFile, File()],
    advance_clock: bool = False,
):
    """Validate and replay a supplemental event CSV on a branch. Nothing is applied."""
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise AppError("Upload too large", code="upload_too_large", status_code=413)
    if not (file.filename or "").lower().endswith(".csv"):
        raise AppError("Upload a .csv file", code="not_csv", status_code=422)
    return preview_csv(
        db, settings, file.filename or "events.csv", data, advance_clock=advance_clock
    )
