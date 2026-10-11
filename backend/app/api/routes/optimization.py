"""Phase 4 optimization endpoints. Read-only: they recommend, never execute.

No endpoint here assigns a consult, creates/approves/sends an offer, or changes staffing.
POST /simulate computes a projection and stores nothing.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AppSettings, Cache, DbSession, OptCache
from app.core.errors import AppError
from app.schemas.dispatch import DispatchResult
from app.schemas.simulation import SUPPORTED_RANGE, SupportedDatetime, is_supported_time
from app.schemas.staffing import StaffingResult
from app.schemas.whatif import OptimizationComparison, SimulateRequest, WhatIfResult
from app.services.optimization import OptimizationService

router = APIRouter(prefix="/optimization", tags=["optimization"])

AsOf = Annotated[
    SupportedDatetime | None,
    Query(description="Optimize at this time (ISO-8601 with offset). Defaults to the clock."),
]


def _service(db, settings, cache, opt_cache) -> OptimizationService:
    return OptimizationService(db, settings, cache, opt_cache)


def _check_body_times(body: SimulateRequest) -> None:
    """Same window as the ``as_of`` query parameter; the body schema can't carry it."""
    start = getattr(body.action, "start", None)
    for field, value in (("as_of", body.as_of), ("action.start", start)):
        if value is not None and not is_supported_time(value):
            raise AppError(
                f"{field} {value.isoformat()} is outside the supported range ({SUPPORTED_RANGE})",
                code="validation_error",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                details={"field": field},
            )


@router.get(
    "/assignments",
    response_model=DispatchResult,
    summary="Proposed consult routing (min-cost flow). Not executed.",
)
def assignments(
    db: DbSession, settings: AppSettings, cache: Cache, opt_cache: OptCache, as_of: AsOf = None
) -> DispatchResult:
    return _service(db, settings, cache, opt_cache).assignments(as_of)


@router.get(
    "/split-shifts",
    response_model=StaffingResult,
    summary="Split-shift eligibility and proposed staffing (CP-SAT). No offer is sent.",
)
def split_shifts(
    db: DbSession, settings: AppSettings, cache: Cache, opt_cache: OptCache, as_of: AsOf = None
) -> StaffingResult:
    return _service(db, settings, cache, opt_cache).split_shifts(as_of)


@router.get(
    "/comparison",
    response_model=OptimizationComparison,
    summary="Baseline vs optimized on the same snapshot and constraints",
)
def comparison(
    db: DbSession, settings: AppSettings, cache: Cache, opt_cache: OptCache, as_of: AsOf = None
) -> OptimizationComparison:
    return _service(db, settings, cache, opt_cache).comparison(as_of)


@router.post(
    "/simulate",
    response_model=WhatIfResult,
    summary="What-if preview (projected if accepted). Read-only: stores nothing.",
)
def simulate(
    body: SimulateRequest,
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt_cache: OptCache,
) -> WhatIfResult:
    _check_body_times(body)
    return _service(db, settings, cache, opt_cache).simulate(body)
