"""Split-shift offers sent (in simulation only) to off-shift physicians.

An offer exists only after a clinical lead approved its intervention and someone sent it.
Physicians see ``PhysicianOfferView`` only: hospitals, hours, time to come online, a
generated reason and the deadline. No patient names, consult IDs or clinical details, and
never the coordinator's free-text rationale.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, Field

from app.schemas.common import ActorRef, ApiModel, EntityId
from app.schemas.hospital import HospitalRef


class OfferStatus(StrEnum):
    SENT = "sent"
    """Delivered (simulated) and awaiting a reply; expires 10 simulated minutes after sending."""
    ACCEPTED = "accepted"
    """Binding acceptance; the physician is preparing to come online (not active capacity)."""
    ACTIVE = "active"
    """The physician is online and counted/routable within the approved scope."""
    COMPLETED = "completed"
    DECLINED = "declined"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"
    """Withdrawn before a reply: coverage secured by someone else, or the request cancelled."""
    REDUNDANT = "redundant"
    """Accepted after the need was already met: recorded, not activated, physician released."""
    CANCELLED = "cancelled"
    """An accepted or active split shift ended early by the coordinator or clinical lead."""


OPEN_OFFER_STATUSES: frozenset[OfferStatus] = frozenset({OfferStatus.SENT})
COMMITTED_OFFER_STATUSES: frozenset[OfferStatus] = frozenset(
    {OfferStatus.ACCEPTED, OfferStatus.ACTIVE}
)


class PhysicianOfferView(ApiModel):
    """Exactly what an off-shift physician is allowed to see. No patient information."""

    id: EntityId
    status: OfferStatus
    status_label: str
    hospitals: list[HospitalRef]
    hospital_timezone: str | None = None
    """Display zone for times (the first hospital's zone)."""
    start_at: AwareDatetime
    end_at: AwareDatetime
    duration_minutes: int = Field(gt=0)
    minutes_to_online: int
    expected_online_at: AwareDatetime | None = None
    reason: str = Field(max_length=500)
    sent_at: AwareDatetime
    expires_at: AwareDatetime
    responded_at: AwareDatetime | None = None
    activated_at: AwareDatetime | None = None
    can_accept: bool
    can_decline: bool
    can_go_online: bool
    message: str | None = None
    """Plain outcome message, e.g. why an offer was withdrawn."""


class OfferResponseRecord(ApiModel):
    id: int
    response: Literal["accept", "decline", "activate"]
    outcome: str
    received_at: AwareDatetime
    recorded_at: AwareDatetime
    response_seconds: int | None
    """Simulated seconds between sending and this response."""
    detail: str | None = None


class ShiftOffer(ApiModel):
    """Full offer record for coordinators, clinical leads and the audit trail."""

    id: EntityId
    intervention_id: EntityId
    physician_id: EntityId
    display_name: str
    plan_role: Literal["primary", "backup"]
    status: OfferStatus
    status_reason: str | None = None
    hospitals: list[HospitalRef]
    routing_scope_hospital_ids: list[EntityId]
    seeded_consult_count: int
    start_at: AwareDatetime
    end_at: AwareDatetime
    duration_minutes: int
    minutes_to_online: int
    reason: str
    channel: str | None = None
    """Roster's preferred channel label. Delivery is simulated; nothing leaves the system."""
    approved_by: ActorRef
    sent_by: ActorRef
    sent_at: AwareDatetime
    expires_at: AwareDatetime
    responded_at: AwareDatetime | None = None
    accepted_at: AwareDatetime | None = None
    expected_online_at: AwareDatetime | None = None
    activated_at: AwareDatetime | None = None
    activation_source: str | None = None
    ended_at: AwareDatetime | None = None
    responses: list[OfferResponseRecord] = Field(default_factory=list)
    allowed_actions: list[Literal["withdraw", "activate", "cancel"]] = Field(default_factory=list)
    """What the caller's role may do with this offer right now (server-computed)."""


class OfferResponseRequest(ApiModel):
    response: Literal["accept", "decline"]


class OfferResponseResult(ApiModel):
    offer: PhysicianOfferView
    outcome: str
    """accepted | declined | redundant | duplicate_ignored."""
    idempotent_replay: bool = False
    message: str


class OfferRecipient(ApiModel):
    """Simulated sign-in list for the physician view (names only, no patient data)."""

    physician_id: EntityId
    display_name: str
    open_offers: int
    total_offers: int


class OfferPage(ApiModel):
    total: int
    items: list[ShiftOffer]


class ExpireResult(ApiModel):
    simulation_time: AwareDatetime
    expired_offer_ids: list[EntityId]
    activated_offer_ids: list[EntityId]
    completed_offer_ids: list[EntityId]
