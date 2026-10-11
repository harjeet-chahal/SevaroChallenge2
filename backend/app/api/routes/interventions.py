"""Phase 5 intervention endpoints (Detect -> Decide -> Act).

Roles are simulated with ``X-Demo-Role`` (+ ``X-Demo-Actor-Id``) and enforced here, at
the API layer, not only in the UI. This is a demo stand-in, not production auth.

  coordinator    preview / propose, send approved offers, apply reassignments,
                 simulate activation, cancel
  clinical_lead  approve / reject, send approved offers, resolve escalations, cancel
  physician      only their own offers (see routes/offers.py)
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import AppSettings, Cache, DbSession, DemoActor, OptCache
from app.schemas.audit import AuditPage
from app.schemas.intervention import (
    CancelRequest,
    DecisionRequest,
    Intervention,
    InterventionCreate,
    InterventionImpact,
    InterventionPage,
    InterventionPreview,
    ResolveRequest,
    WorkflowSummary,
)
from app.services.workflow import WorkflowService

router = APIRouter(tags=["interventions"])


def _svc(db, settings, cache, opt_cache) -> WorkflowService:
    return WorkflowService(db, settings, cache, opt_cache)


@router.post(
    "/interventions/preview",
    response_model=InterventionPreview,
    summary="Dry-run a proposal against the current data version (stores nothing)",
)
def preview(
    body: InterventionCreate,
    actor: DemoActor,
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt_cache: OptCache,
) -> InterventionPreview:
    return _svc(db, settings, cache, opt_cache).preview(body, actor)


@router.post(
    "/interventions",
    response_model=Intervention,
    status_code=status.HTTP_201_CREATED,
    summary="Propose an intervention. A split shift becomes a pending clinical approval; "
    "no physician is contacted.",
)
def propose(
    body: InterventionCreate,
    actor: DemoActor,
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt_cache: OptCache,
) -> Intervention:
    return _svc(db, settings, cache, opt_cache).propose(body, actor)


@router.get("/interventions", response_model=InterventionPage)
def list_interventions(
    actor: DemoActor,
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt_cache: OptCache,
    scope: Annotated[str, Query(pattern="^(active|all)$")] = "active",
    status_filter: Annotated[list[str] | None, Query(alias="status")] = None,
    type_filter: Annotated[list[str] | None, Query(alias="type")] = None,
) -> InterventionPage:
    """``scope=active`` (default): the active dataset's interventions; ``all``: history
    across re-imports."""
    return _svc(db, settings, cache, opt_cache).list_interventions(
        actor, all_datasets=scope == "all", statuses=status_filter, types=type_filter
    )


@router.get("/interventions/summary", response_model=WorkflowSummary)
def summary(
    db: DbSession, settings: AppSettings, cache: Cache, opt_cache: OptCache
) -> WorkflowSummary:
    """Counts for badges and live updates. Contains no patient or physician details."""
    return _svc(db, settings, cache, opt_cache).summary()


@router.get("/interventions/{intervention_id}", response_model=Intervention)
def get_intervention(
    intervention_id: str,
    actor: DemoActor,
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt_cache: OptCache,
) -> Intervention:
    service = _svc(db, settings, cache, opt_cache)
    service.get(intervention_id, actor)  # role check first: a refused caller changes nothing
    service.sweep()
    return service.get(intervention_id, actor)


@router.post("/interventions/{intervention_id}/decision", response_model=Intervention)
def decide(
    intervention_id: str,
    body: DecisionRequest,
    actor: DemoActor,
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt_cache: OptCache,
) -> Intervention:
    """Clinical lead only. Approval re-validates eligibility, offer limits and the
    remaining coverage need against the current data before recording the decision."""
    return _svc(db, settings, cache, opt_cache).decide(intervention_id, body, actor)


@router.post("/interventions/{intervention_id}/send-offers", response_model=Intervention)
def send_offers(
    intervention_id: str,
    actor: DemoActor,
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt_cache: OptCache,
) -> Intervention:
    """Send the approved split-shift offer(s) — simulated delivery, nothing leaves the
    system. Refused (409 approval_required) before approval."""
    return _svc(db, settings, cache, opt_cache).send_offers(intervention_id, actor)


@router.post("/interventions/{intervention_id}/apply", response_model=Intervention)
def apply(
    intervention_id: str,
    actor: DemoActor,
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt_cache: OptCache,
) -> Intervention:
    """Coordinator: apply a reassignment (re-checked now; recorded as a workflow event)."""
    return _svc(db, settings, cache, opt_cache).apply(intervention_id, actor)


@router.post("/interventions/{intervention_id}/resolve", response_model=Intervention)
def resolve(
    intervention_id: str,
    body: ResolveRequest,
    actor: DemoActor,
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt_cache: OptCache,
) -> Intervention:
    return _svc(db, settings, cache, opt_cache).resolve(intervention_id, body, actor)


@router.post("/interventions/{intervention_id}/cancel", response_model=Intervention)
def cancel(
    intervention_id: str,
    body: CancelRequest,
    actor: DemoActor,
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt_cache: OptCache,
) -> Intervention:
    return _svc(db, settings, cache, opt_cache).cancel(intervention_id, body, actor)


@router.get("/interventions/{intervention_id}/impact", response_model=InterventionImpact)
def impact(
    intervention_id: str,
    actor: DemoActor,
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt_cache: OptCache,
) -> InterventionImpact:
    return _svc(db, settings, cache, opt_cache).impact(intervention_id, actor)


@router.get("/interventions/{intervention_id}/audit", response_model=AuditPage)
def intervention_audit(
    intervention_id: str,
    actor: DemoActor,
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt_cache: OptCache,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
) -> AuditPage:
    return _svc(db, settings, cache, opt_cache).audit(
        actor, intervention_id=intervention_id, limit=limit
    )


@router.get("/audit", response_model=AuditPage, summary="Workflow audit log (newest first)")
def audit(
    actor: DemoActor,
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt_cache: OptCache,
    intervention_id: str | None = None,
    offer_id: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditPage:
    return _svc(db, settings, cache, opt_cache).audit(
        actor, intervention_id=intervention_id, offer_id=offer_id, limit=limit, offset=offset
    )
