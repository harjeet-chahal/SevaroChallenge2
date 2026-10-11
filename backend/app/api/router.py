"""Aggregates all route modules under the /api prefix."""

from fastapi import APIRouter

from app.api.routes import (
    analysis,
    availability,
    datasets,
    events,
    interventions,
    live,
    offers,
    optimization,
    simulation,
    state,
    system,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(system.router)
api_router.include_router(datasets.router)
api_router.include_router(simulation.router)
api_router.include_router(state.router)
api_router.include_router(events.router)
api_router.include_router(analysis.router)
api_router.include_router(optimization.router)
api_router.include_router(interventions.router)
api_router.include_router(offers.router)
api_router.include_router(availability.router)
api_router.include_router(live.router)
