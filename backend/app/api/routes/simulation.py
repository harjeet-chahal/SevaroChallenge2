from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter

from app.api.deps import AppSettings, Cache, DbSession, OptCache
from app.schemas.simulation import (
    AdvanceSimulationRequest,
    SetSimulationTimeRequest,
    SimulationClock,
)
from app.services.simulation import SimulationService
from app.services.workflow import WorkflowService

router = APIRouter(prefix="/simulation", tags=["simulation"])


def _after_move(db, settings, cache, opt_cache) -> SimulationClock:
    """Moving the clock is the only way simulated time passes, so apply everything that
    became due (offer expiry, activation, shift end) right away, then report the clock."""
    WorkflowService(db, settings, cache, opt_cache).sweep()
    return SimulationService(db, settings).clock()


@router.get("", response_model=SimulationClock)
def get_clock(db: DbSession, settings: AppSettings) -> SimulationClock:
    return SimulationService(db, settings).clock()


@router.post("/time", response_model=SimulationClock, summary="Set the simulation time")
def set_time(
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt_cache: OptCache,
    body: SetSimulationTimeRequest,
) -> SimulationClock:
    SimulationService(db, settings).set_time(body.time)
    return _after_move(db, settings, cache, opt_cache)


@router.post(
    "/advance", response_model=SimulationClock, summary="Move the simulation clock forward"
)
def advance(
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt_cache: OptCache,
    body: AdvanceSimulationRequest,
) -> SimulationClock:
    delta = timedelta(minutes=body.minutes, seconds=body.seconds)
    SimulationService(db, settings).advance(delta)
    return _after_move(db, settings, cache, opt_cache)


@router.post(
    "/reset", response_model=SimulationClock, summary="Return to the dataset reference time"
)
def reset(
    db: DbSession, settings: AppSettings, cache: Cache, opt_cache: OptCache
) -> SimulationClock:
    """Moving back does not undo workflow decisions; derived staffing only applies a
    workflow fact from its simulated timestamp onwards."""
    SimulationService(db, settings).reset()
    return _after_move(db, settings, cache, opt_cache)
