from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.deps import AppSettings, DbSession
from app.schemas.system import ConfigResponse, HealthResponse
from app.services.system import SystemService

router = APIRouter(tags=["system"])


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "A dependency is unhealthy"}},
)
def get_health(db: DbSession, settings: AppSettings, response: Response) -> HealthResponse:
    health = SystemService(db, settings).health()
    if health.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return health


@router.get("/config", response_model=ConfigResponse)
def get_config(db: DbSession, settings: AppSettings) -> ConfigResponse:
    return SystemService(db, settings).config()
