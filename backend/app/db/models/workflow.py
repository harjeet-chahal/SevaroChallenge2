"""Phase 5 workflow persistence: interventions, approvals, offers, responses, audit log.

These tables hold *decisions*, not source data. They are never touched by an event-CSV
append, and a full dataset re-import closes (never deletes) the open ones, so history is
always kept. Operational state stays derived from the event log; accepted and activated
split shifts are applied on top of it as a time-aware overlay (engines/interventions).

Table names carry a ``wf_`` prefix. The Phase 1 placeholder tables (``interventions``,
``offers``, ``audit_log``) were never written to; using new names lets existing databases
gain these tables additively (``create_all``) without a schema rebuild.

Invariants enforced by the database as well as by the service:
- at most one decision per intervention (unique ``wf_approvals.intervention_id``);
- at most one open (sent, unanswered) offer per physician (partial unique index).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime


class InterventionRecord(Base):
    __tablename__ = "wf_interventions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(32), index=True)
    status_reason: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(String(300))
    rationale: Mapped[str | None] = mapped_column(Text)
    dataset_import_id: Mapped[str | None] = mapped_column(String(64), index=True)
    alert_id: Mapped[str | None] = mapped_column(String(200), index=True)
    consult_id: Mapped[str | None] = mapped_column(String(128), index=True)
    hospital_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    required_physicians: Mapped[int] = mapped_column(Integer, default=1)
    problem: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    recommendation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    offer_plan: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    reassignment: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    escalation: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    impact: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    trap: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    proposed_by_role: Mapped[str] = mapped_column(String(32))
    proposed_by_id: Mapped[str | None] = mapped_column(String(128))
    proposed_at: Mapped[datetime] = mapped_column(UTCDateTime)
    """Simulation time of the proposal."""
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    """Simulation time of the latest transition."""
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime)
    """Wall-clock time the record was created."""
    created_data_version: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)


class ApprovalRecord(Base):
    __tablename__ = "wf_approvals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    intervention_id: Mapped[str] = mapped_column(
        ForeignKey("wf_interventions.id", ondelete="CASCADE"), unique=True
    )
    decision: Mapped[str] = mapped_column(String(16))
    actor_role: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str | None] = mapped_column(String(128))
    decided_at: Mapped[datetime] = mapped_column(UTCDateTime)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime)
    note: Mapped[str | None] = mapped_column(Text)
    data_version: Mapped[int] = mapped_column(Integer)
    revalidation: Mapped[list[str]] = mapped_column(JSON, default=list)


class OfferRecord(Base):
    __tablename__ = "wf_offers"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    intervention_id: Mapped[str] = mapped_column(
        ForeignKey("wf_interventions.id", ondelete="CASCADE"), index=True
    )
    physician_id: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str] = mapped_column(String(256))
    plan_role: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(32), index=True)
    status_reason: Mapped[str | None] = mapped_column(Text)
    hospital_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    routing_scope: Mapped[list[str]] = mapped_column(JSON, default=list)
    seeded_consult_count: Mapped[int] = mapped_column(Integer, default=0)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    minutes_to_online: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(500))
    channel: Mapped[str | None] = mapped_column(String(64))
    approved_by_role: Mapped[str] = mapped_column(String(32))
    approved_by_id: Mapped[str | None] = mapped_column(String(128))
    sent_by_role: Mapped[str] = mapped_column(String(32))
    sent_by_id: Mapped[str | None] = mapped_column(String(128))
    sent_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    accepted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    expected_online_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    activated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    activation_source: Mapped[str | None] = mapped_column(String(64))
    activation_impact: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime)

    __table_args__ = (
        Index(
            "uq_wf_offers_one_open_per_physician",
            "physician_id",
            unique=True,
            sqlite_where=text("status = 'sent'"),
            postgresql_where=text("status = 'sent'"),
        ),
    )


class OfferResponseRecord(Base):
    """Every response attempt, including rejected and duplicate ones."""

    __tablename__ = "wf_offer_responses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    offer_id: Mapped[str] = mapped_column(
        ForeignKey("wf_offers.id", ondelete="CASCADE"), index=True
    )
    physician_id: Mapped[str] = mapped_column(String(128))
    response: Mapped[str] = mapped_column(String(16))
    outcome: Mapped[str] = mapped_column(String(48))
    received_at: Mapped[datetime] = mapped_column(UTCDateTime)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime)
    response_seconds: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[str | None] = mapped_column(Text)


class AuditLogEntry(Base):
    __tablename__ = "wf_audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    """Simulation time."""
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime)
    """Wall-clock time."""
    actor_role: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str | None] = mapped_column(String(128))
    action: Mapped[str] = mapped_column(String(64), index=True)
    intervention_id: Mapped[str | None] = mapped_column(String(64), index=True)
    offer_id: Mapped[str | None] = mapped_column(String(64), index=True)
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(128))
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    data_version: Mapped[int] = mapped_column(Integer, default=0)
