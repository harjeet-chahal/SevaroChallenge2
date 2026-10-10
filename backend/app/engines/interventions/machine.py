"""Explicit, validated state machines for interventions and offers (pure).

Every status change in the workflow goes through ``require_*_transition``. A transition
that is not listed here is refused with ``invalid_transition`` (HTTP 409), whatever the
caller's role. Not every intervention type uses every status:

  split_shift   pending_approval -> approved | rejected | cancelled | no_longer_required
                approved         -> offer_sent | cancelled | no_longer_required
                offer_sent       -> accepted | declined | expired | cancelled
                                    | no_longer_required
                accepted         -> activated | cancelled
                activated        -> completed | cancelled
  escalation    pending_approval -> approved | rejected | cancelled | no_longer_required
                approved         -> completed | cancelled
  reassign      proposed         -> completed | cancelled | no_longer_required

Offers (one per physician the shift is offered to):

  sent      -> accepted | declined | expired | withdrawn | redundant
  accepted  -> active | cancelled
  active    -> completed | cancelled

``accepted`` means the physician committed and is preparing to come online; only
``active`` counts as active, routable capacity.
"""

from __future__ import annotations

from app.core.errors import ConflictError
from app.schemas.intervention import InterventionStatus as S
from app.schemas.intervention import InterventionType as T
from app.schemas.offer import OfferStatus as O

INTERVENTION_TRANSITIONS: dict[T, dict[S, frozenset[S]]] = {
    T.SPLIT_SHIFT: {
        S.PENDING_APPROVAL: frozenset({S.APPROVED, S.REJECTED, S.CANCELLED, S.NO_LONGER_REQUIRED}),
        S.APPROVED: frozenset({S.OFFER_SENT, S.CANCELLED, S.NO_LONGER_REQUIRED}),
        S.OFFER_SENT: frozenset(
            {S.ACCEPTED, S.DECLINED, S.EXPIRED, S.CANCELLED, S.NO_LONGER_REQUIRED}
        ),
        S.ACCEPTED: frozenset({S.ACTIVATED, S.CANCELLED}),
        S.ACTIVATED: frozenset({S.COMPLETED, S.CANCELLED}),
    },
    T.ESCALATION: {
        S.PENDING_APPROVAL: frozenset({S.APPROVED, S.REJECTED, S.CANCELLED, S.NO_LONGER_REQUIRED}),
        S.APPROVED: frozenset({S.COMPLETED, S.CANCELLED}),
    },
    T.REASSIGN_CONSULT: {
        S.PROPOSED: frozenset({S.COMPLETED, S.CANCELLED, S.NO_LONGER_REQUIRED}),
    },
}

INITIAL_STATUS: dict[T, S] = {
    T.SPLIT_SHIFT: S.PENDING_APPROVAL,
    T.ESCALATION: S.PENDING_APPROVAL,
    T.REASSIGN_CONSULT: S.PROPOSED,
}

OFFER_TRANSITIONS: dict[O, frozenset[O]] = {
    O.SENT: frozenset({O.ACCEPTED, O.DECLINED, O.EXPIRED, O.WITHDRAWN, O.REDUNDANT}),
    O.ACCEPTED: frozenset({O.ACTIVE, O.CANCELLED}),
    O.ACTIVE: frozenset({O.COMPLETED, O.CANCELLED}),
}

OFFER_TERMINAL: frozenset[O] = frozenset(
    {O.DECLINED, O.EXPIRED, O.WITHDRAWN, O.REDUNDANT, O.COMPLETED, O.CANCELLED}
)


def can_transition(kind: T, current: S, target: S) -> bool:
    return target in INTERVENTION_TRANSITIONS[kind].get(current, frozenset())


def require_transition(kind: T, current: S, target: S, *, entity_id: str) -> None:
    if not can_transition(kind, current, target):
        allowed = sorted(INTERVENTION_TRANSITIONS[kind].get(current, frozenset()))
        raise ConflictError(
            f"{kind.value} {entity_id} is '{current.value}'; it cannot move to '{target.value}'.",
            code="invalid_transition",
            details={
                "intervention_id": entity_id,
                "current_status": current.value,
                "requested_status": target.value,
                "allowed_next": [s.value for s in allowed],
            },
        )


def can_offer_transition(current: O, target: O) -> bool:
    return target in OFFER_TRANSITIONS.get(current, frozenset())


def require_offer_transition(current: O, target: O, *, offer_id: str) -> None:
    if not can_offer_transition(current, target):
        raise ConflictError(
            f"Offer {offer_id} is '{current.value}'; it cannot move to '{target.value}'.",
            code="invalid_transition",
            details={
                "offer_id": offer_id,
                "current_status": current.value,
                "requested_status": target.value,
                "allowed_next": sorted(s.value for s in OFFER_TRANSITIONS.get(current, ())),
            },
        )


def split_shift_status_from_offers(current: S, offers: list[O]) -> S:
    """Derived intervention status once offers exist (after approval and sending)."""
    if not offers:
        return current
    if O.ACTIVE in offers:
        return S.ACTIVATED
    if O.ACCEPTED in offers:
        return S.ACCEPTED
    if O.COMPLETED in offers:
        return S.COMPLETED
    if O.SENT in offers:
        return S.OFFER_SENT
    if current in (S.CANCELLED, S.NO_LONGER_REQUIRED, S.COMPLETED):
        return current
    if O.CANCELLED in offers:
        return S.CANCELLED
    if O.EXPIRED in offers:
        return S.EXPIRED
    if O.DECLINED in offers:
        return S.DECLINED
    return S.NO_LONGER_REQUIRED
