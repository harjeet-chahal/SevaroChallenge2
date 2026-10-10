from __future__ import annotations

from typing import Any

from pydantic import AwareDatetime, Field

from app.schemas.common import ActorRef, ApiModel, EntityId


class AuditEntry(ApiModel):
    """Append-only record of a workflow decision or state change.

    ``occurred_at`` is simulation time (when it happened in the scenario); ``recorded_at``
    is the server's wall clock (when the system wrote it). Every offer is traceable: who
    was considered and why each passed or failed, who approved, what was sent, the reply
    and its timing, expiry, activation, conflicts and their resolution.
    """

    id: int
    occurred_at: AwareDatetime
    recorded_at: AwareDatetime
    actor: ActorRef
    action: str
    intervention_id: EntityId | None = None
    offer_id: EntityId | None = None
    entity_type: str
    entity_id: EntityId | None = None
    from_status: str | None = None
    to_status: str | None = None
    summary: str
    details: dict[str, Any] = Field(default_factory=dict)
    data_version: int


class AuditPage(ApiModel):
    total: int
    items: list[AuditEntry]
