"""Split-shift offer endpoints.

Physicians (``X-Demo-Role: physician`` + ``X-Demo-Actor-Id: <physician id>``) see and
answer only their own offers; payloads carry no patient information. Coordinators and
clinical leads see every offer with its full history.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import AppSettings, Cache, DbSession, DemoActor, OptCache
from app.schemas.common import UserRole
from app.schemas.intervention import CancelRequest
from app.schemas.offer import (
    ExpireResult,
    OfferPage,
    OfferRecipient,
    OfferResponseRequest,
    OfferResponseResult,
    PhysicianOfferView,
    ShiftOffer,
)
from app.services.workflow import WorkflowService, require_role

router = APIRouter(prefix="/offers", tags=["offers"])


def _svc(db, settings, cache, opt_cache) -> WorkflowService:
    return WorkflowService(db, settings, cache, opt_cache)


@router.get("", response_model=OfferPage, summary="All offers (coordinator / clinical lead)")
def list_offers(
    actor: DemoActor, db: DbSession, settings: AppSettings, cache: Cache, opt_cache: OptCache
) -> OfferPage:
    return _svc(db, settings, cache, opt_cache).offers(actor)


@router.get(
    "/mine",
    response_model=list[PhysicianOfferView],
    summary="The calling physician's offers (only approved and sent ones exist)",
)
def my_offers(
    actor: DemoActor, db: DbSession, settings: AppSettings, cache: Cache, opt_cache: OptCache
) -> list[PhysicianOfferView]:
    return _svc(db, settings, cache, opt_cache).my_offers(actor)


@router.get(
    "/recipients",
    response_model=list[OfferRecipient],
    summary="Simulated physician sign-in list (names and offer counts only)",
)
def recipients(
    db: DbSession, settings: AppSettings, cache: Cache, opt_cache: OptCache
) -> list[OfferRecipient]:
    return _svc(db, settings, cache, opt_cache).recipients()


@router.post("/expire-due", response_model=ExpireResult)
def expire_due(
    actor: DemoActor, db: DbSession, settings: AppSettings, cache: Cache, opt_cache: OptCache
) -> ExpireResult:
    """Apply everything due at the current simulation time (expiry, activation, shift end).
    The same check runs automatically on every workflow request and clock move."""
    require_role(actor, UserRole.COORDINATOR, UserRole.CLINICAL_LEAD, action="run the expiry check")
    return _svc(db, settings, cache, opt_cache).sweep()


@router.post("/{offer_id}/respond", response_model=OfferResponseResult)
def respond(
    offer_id: str,
    body: OfferResponseRequest,
    actor: DemoActor,
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt_cache: OptCache,
) -> OfferResponseResult:
    """Accept or decline. Repeating the same answer is idempotent (200,
    ``idempotent_replay``); expired, declined, withdrawn or cancelled offers cannot be
    accepted (409). Every attempt is logged."""
    return _svc(db, settings, cache, opt_cache).respond(offer_id, body, actor)


@router.post("/{offer_id}/activate", response_model=ShiftOffer)
def activate(
    offer_id: str,
    actor: DemoActor,
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt_cache: OptCache,
) -> ShiftOffer:
    """The physician reports being online (or the coordinator simulates it). Allowed once
    the shift has started; otherwise activation happens automatically at the expected
    online time when the simulation clock reaches it."""
    return _svc(db, settings, cache, opt_cache).activate(offer_id, actor)


@router.post("/{offer_id}/withdraw", response_model=ShiftOffer)
def withdraw(
    offer_id: str,
    body: CancelRequest,
    actor: DemoActor,
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt_cache: OptCache,
) -> ShiftOffer:
    """Withdraw a sent offer; for an accepted/active one this cancels the split shift."""
    return _svc(db, settings, cache, opt_cache).withdraw_offer(offer_id, body, actor)
