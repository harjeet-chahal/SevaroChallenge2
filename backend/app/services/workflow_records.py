"""Low-level workflow writes shared by the workflow service and the dataset importer.

Every status change goes through ``transition_intervention`` / ``transition_offer``,
which validate it against the state machine and write an audit record in the same
transaction. Nothing here depends on the analysis engines, so the importer can use it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic_core import to_jsonable_python
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.db.models import AuditLogEntry, InterventionRecord, OfferRecord
from app.engines.interventions import (
    can_transition,
    require_offer_transition,
    require_transition,
)
from app.repositories import SystemRepository
from app.repositories.workflow import WorkflowRepository
from app.schemas.common import ActorRef, UserRole
from app.schemas.intervention import TERMINAL_STATUSES, InterventionStatus, InterventionType
from app.schemas.offer import OfferStatus

SYSTEM_ACTOR = ActorRef(role=UserRole.SYSTEM, actor_id="simulation-policy")


def data_version(session: Session) -> int:
    state = SystemRepository(session).get_simulation_state()
    return state.data_version if state else 0


def bump_data_version(session: Session) -> int:
    """Workflow decisions that change derived staffing (accept, activate, end) bump the
    data version, so every cached analysis and every open view recomputes."""
    state = SystemRepository(session).get_or_create_simulation_state(utc_now())
    state.data_version = (state.data_version or 0) + 1
    state.updated_at = utc_now()
    session.flush()
    return state.data_version


def write_audit(
    session: Session,
    *,
    at: datetime,
    actor: ActorRef,
    action: str,
    summary: str,
    entity_type: str,
    entity_id: str | None,
    intervention_id: str | None = None,
    offer_id: str | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLogEntry:
    entry = AuditLogEntry(
        occurred_at=at,
        recorded_at=utc_now(),
        actor_role=actor.role.value,
        actor_id=actor.actor_id,
        action=action,
        intervention_id=intervention_id,
        offer_id=offer_id,
        entity_type=entity_type,
        entity_id=entity_id,
        from_status=from_status,
        to_status=to_status,
        summary=summary,
        details=to_jsonable_python(details or {}),
        data_version=data_version(session),
    )
    session.add(entry)
    session.flush()
    return entry


def transition_intervention(
    session: Session,
    rec: InterventionRecord,
    target: InterventionStatus,
    *,
    at: datetime,
    actor: ActorRef,
    action: str,
    summary: str,
    reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    kind = InterventionType(rec.type)
    current = InterventionStatus(rec.status)
    require_transition(kind, current, target, entity_id=rec.id)
    rec.status = target.value
    rec.status_reason = reason
    rec.updated_at = max(at, rec.updated_at)
    rec.version += 1
    write_audit(
        session,
        at=at,
        actor=actor,
        action=action,
        summary=summary,
        entity_type="intervention",
        entity_id=rec.id,
        intervention_id=rec.id,
        from_status=current.value,
        to_status=target.value,
        details={**(details or {}), **({"reason": reason} if reason else {})},
    )


def transition_offer(
    session: Session,
    offer: OfferRecord,
    target: OfferStatus,
    *,
    at: datetime,
    actor: ActorRef,
    action: str,
    summary: str,
    reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    current = OfferStatus(offer.status)
    require_offer_transition(current, target, offer_id=offer.id)
    offer.status = target.value
    if reason is not None:
        offer.status_reason = reason
    write_audit(
        session,
        at=at,
        actor=actor,
        action=action,
        summary=summary,
        entity_type="offer",
        entity_id=offer.id,
        intervention_id=offer.intervention_id,
        offer_id=offer.id,
        from_status=current.value,
        to_status=target.value,
        details={**(details or {}), **({"reason": reason} if reason else {})},
    )
    session.flush()


def close_workflow_for_dataset_replacement(
    session: Session, *, previous_import_id: str | None, new_import_id: str, at: datetime
) -> int:
    """Re-import policy: a full dataset replacement starts a new operational picture, so
    every open intervention from the previous dataset is closed, never deleted.

    - sent offers are withdrawn; accepted or active split shifts are cancelled (their
      staffing overlay stops applying, because it is scoped to its own dataset);
    - open interventions become ``no_longer_required`` (or ``cancelled`` where the state
      machine does not allow that, i.e. accepted/activated split shifts);
    - every step is audited. History stays queryable with ``scope=all``.

    An event-CSV append is *not* a replacement and never calls this.
    """
    if previous_import_id is None:
        return 0
    repo = WorkflowRepository(session)
    reason = f"dataset replaced by import {new_import_id}"
    closed = 0
    for rec in repo.list_interventions(import_id=previous_import_id):
        status = InterventionStatus(rec.status)
        if status in TERMINAL_STATUSES:
            continue
        for offer in repo.offers_for(rec.id):
            current = OfferStatus(offer.status)
            target = {
                OfferStatus.SENT: OfferStatus.WITHDRAWN,
                OfferStatus.ACCEPTED: OfferStatus.CANCELLED,
                OfferStatus.ACTIVE: OfferStatus.CANCELLED,
            }.get(current)
            if target is None:
                continue
            if target is OfferStatus.CANCELLED:
                offer.ended_at = at
            transition_offer(
                session,
                offer,
                target,
                at=at,
                actor=SYSTEM_ACTOR,
                action="offer_closed_dataset_replaced",
                summary=f"Offer {offer.id} {target.value}: {reason}.",
                reason=reason,
            )
        target = (
            InterventionStatus.NO_LONGER_REQUIRED
            if can_transition(
                InterventionType(rec.type), status, InterventionStatus.NO_LONGER_REQUIRED
            )
            else InterventionStatus.CANCELLED
        )
        transition_intervention(
            session,
            rec,
            target,
            at=at,
            actor=SYSTEM_ACTOR,
            action="intervention_closed_dataset_replaced",
            summary=f"{rec.id} closed ({target.value}): {reason}.",
            reason=reason,
        )
        closed += 1
    return closed
