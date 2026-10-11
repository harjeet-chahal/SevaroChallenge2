"""Split-shift offer endpoints.

Physicians (``X-Demo-Role: physician`` + ``X-Demo-Actor-Id: <physician id>``) see and
answer only their own offers; payloads carry no patient information. Coordinators and
clinical leads see every offer with its full history.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import Field

from app.api.deps import AppSettings, Cache, DbSession, DemoActor, OptCache
from app.core.errors import NotFoundError
from app.db.models import PhysicianRecord
from app.schemas.common import ApiModel, UserRole
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
from app.schemas.physician import ShiftWindow
from app.services.workflow import WorkflowService, require_role
from app.services.workflow_records import bump_data_version, write_audit

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


class ExtraAvailability(ApiModel):
    enabled: bool = False
    windows: list[ShiftWindow] = Field(default_factory=list, max_length=20)


@router.get("/extra-availability", response_model=ExtraAvailability)
def extra_availability(actor: DemoActor, db: DbSession) -> ExtraAvailability:
    require_role(actor, UserRole.PHYSICIAN, action="view own extra-shift availability")
    row = db.get(PhysicianRecord, actor.actor_id)
    if row is None:
        raise NotFoundError("Physician not found")
    return ExtraAvailability.model_validate((row.attributes or {}).get("extra_availability", {}))


@router.put("/extra-availability", response_model=ExtraAvailability)
def save_extra_availability(
    body: ExtraAvailability,
    actor: DemoActor,
    db: DbSession,
    settings: AppSettings,
    cache: Cache,
    opt_cache: OptCache,
) -> ExtraAvailability:
    require_role(actor, UserRole.PHYSICIAN, action="update own extra-shift availability")
    svc = _svc(db, settings, cache, opt_cache)
    with svc._write():
        row = db.get(PhysicianRecord, actor.actor_id)
        if row is None:
            raise NotFoundError("Physician not found")
        row.attributes = {
            **(row.attributes or {}),
            "extra_availability": body.model_dump(mode="json"),
        }
        bump_data_version(db)
        write_audit(
            db,
            at=svc._now(),
            actor=actor,
            action="extra_availability_updated",
            summary=f"{row.display_name} updated extra-shift availability.",
            entity_type="physician",
            entity_id=row.id,
            details=body.model_dump(mode="json"),
        )
    return body
