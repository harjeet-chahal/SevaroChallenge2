"""Data access for the Phase 5 workflow tables. No business rules here."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    ApprovalRecord,
    AuditLogEntry,
    InterventionRecord,
    OfferRecord,
    OfferResponseRecord,
)
from app.engines.interventions.overlay import OverlayEntry
from app.schemas.offer import OfferStatus

_OVERLAY_STATUSES = (
    OfferStatus.ACCEPTED.value,
    OfferStatus.ACTIVE.value,
    OfferStatus.COMPLETED.value,
    OfferStatus.CANCELLED.value,
)


class WorkflowRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # --- ids -----------------------------------------------------------------------

    def _next_number(self, model, prefix: str) -> int:
        ids = self.session.scalars(select(model.id).where(model.id.like(f"{prefix}-%")))
        numbers = [int(i.rsplit("-", 1)[1]) for i in ids if i.rsplit("-", 1)[1].isdigit()]
        return max(numbers, default=0) + 1

    def next_intervention_id(self) -> str:
        return f"INT-{self._next_number(InterventionRecord, 'INT'):04d}"

    def next_offer_id(self) -> str:
        return f"OFF-{self._next_number(OfferRecord, 'OFF'):04d}"

    # --- interventions -------------------------------------------------------------

    def get_intervention(self, intervention_id: str) -> InterventionRecord | None:
        return self.session.get(InterventionRecord, intervention_id)

    def list_interventions(
        self,
        *,
        import_id: str | None,
        all_datasets: bool = False,
        statuses: Iterable[str] | None = None,
        types: Iterable[str] | None = None,
    ) -> list[InterventionRecord]:
        stmt = select(InterventionRecord)
        if not all_datasets:
            stmt = stmt.where(InterventionRecord.dataset_import_id == import_id)
        if statuses:
            stmt = stmt.where(InterventionRecord.status.in_(list(statuses)))
        if types:
            stmt = stmt.where(InterventionRecord.type.in_(list(types)))
        stmt = stmt.order_by(InterventionRecord.recorded_at.desc(), InterventionRecord.id.desc())
        return list(self.session.scalars(stmt))

    def approval_for(self, intervention_id: str) -> ApprovalRecord | None:
        return self.session.scalars(
            select(ApprovalRecord).where(ApprovalRecord.intervention_id == intervention_id)
        ).first()

    # --- offers --------------------------------------------------------------------

    def get_offer(self, offer_id: str) -> OfferRecord | None:
        return self.session.get(OfferRecord, offer_id)

    def offers_for(self, intervention_id: str) -> list[OfferRecord]:
        return list(
            self.session.scalars(
                select(OfferRecord)
                .where(OfferRecord.intervention_id == intervention_id)
                .order_by(OfferRecord.id)
            )
        )

    def offers_for_physician(self, physician_id: str) -> list[OfferRecord]:
        return list(
            self.session.scalars(
                select(OfferRecord)
                .where(OfferRecord.physician_id == physician_id)
                .order_by(OfferRecord.sent_at.desc(), OfferRecord.id.desc())
            )
        )

    def all_offers(self, import_id: str | None) -> list[OfferRecord]:
        stmt = (
            select(OfferRecord)
            .join(InterventionRecord, InterventionRecord.id == OfferRecord.intervention_id)
            .where(InterventionRecord.dataset_import_id == import_id)
            .order_by(OfferRecord.sent_at.desc(), OfferRecord.id.desc())
        )
        return list(self.session.scalars(stmt))

    def offers_with_status(self, statuses: Iterable[str]) -> list[OfferRecord]:
        return list(
            self.session.scalars(
                select(OfferRecord)
                .where(OfferRecord.status.in_(list(statuses)))
                .order_by(OfferRecord.id)
            )
        )

    def responses_for(self, offer_id: str) -> list[OfferResponseRecord]:
        return list(
            self.session.scalars(
                select(OfferResponseRecord)
                .where(OfferResponseRecord.offer_id == offer_id)
                .order_by(OfferResponseRecord.id)
            )
        )

    def offer_counts(
        self, physician_id: str, as_of: datetime, window: timedelta
    ) -> tuple[int, int, int]:
        """(open sent offers, committed accepted/active shifts, offers sent in the window)."""
        offers = self.offers_for_physician(physician_id)
        open_ = sum(o.status == OfferStatus.SENT.value for o in offers)
        committed = sum(
            o.status in (OfferStatus.ACCEPTED.value, OfferStatus.ACTIVE.value) for o in offers
        )
        week = sum(as_of - window < o.sent_at <= as_of for o in offers)
        return open_, committed, week

    def offer_log(self, as_of: datetime, window: timedelta) -> dict[str, tuple[int, int]]:
        """physician_id -> (open offers + committed split shifts, offers sent in window)."""
        log: dict[str, tuple[int, int]] = {}
        rows = self.session.scalars(select(OfferRecord).where(OfferRecord.sent_at <= as_of))
        for o in rows:
            open_, week = log.get(o.physician_id, (0, 0))
            if o.status in (
                OfferStatus.SENT.value,
                OfferStatus.ACCEPTED.value,
                OfferStatus.ACTIVE.value,
            ):
                open_ += 1
            if as_of - window < o.sent_at <= as_of:
                week += 1
            log[o.physician_id] = (open_, week)
        return log

    def overlay_entries(self, import_id: str | None) -> list[OverlayEntry]:
        stmt = (
            select(OfferRecord)
            .join(InterventionRecord, InterventionRecord.id == OfferRecord.intervention_id)
            .where(
                InterventionRecord.dataset_import_id == import_id,
                OfferRecord.status.in_(_OVERLAY_STATUSES),
                OfferRecord.accepted_at.is_not(None),
            )
            .order_by(OfferRecord.id)
        )
        entries: list[OverlayEntry] = []
        for o in self.session.scalars(stmt):
            assert o.accepted_at is not None
            entries.append(
                OverlayEntry(
                    physician_id=o.physician_id,
                    intervention_id=o.intervention_id,
                    offer_id=o.id,
                    start_at=o.start_at,
                    end_at=o.end_at,
                    accepted_at=o.accepted_at,
                    expected_online_at=o.expected_online_at or o.start_at,
                    activated_at=o.activated_at,
                    ended_at=o.ended_at,
                    scope=tuple(o.routing_scope),
                    seeded_count=o.seeded_consult_count,
                    minutes=o.duration_minutes,
                )
            )
        return entries

    # --- audit ---------------------------------------------------------------------

    def workflow_version(self) -> int:
        return int(self.session.scalar(select(func.max(AuditLogEntry.id))) or 0)

    def audit(
        self,
        *,
        intervention_id: str | None = None,
        offer_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> tuple[int, list[AuditLogEntry]]:
        stmt = select(AuditLogEntry)
        count = select(func.count(AuditLogEntry.id))
        if intervention_id:
            stmt = stmt.where(AuditLogEntry.intervention_id == intervention_id)
            count = count.where(AuditLogEntry.intervention_id == intervention_id)
        if offer_id:
            stmt = stmt.where(AuditLogEntry.offer_id == offer_id)
            count = count.where(AuditLogEntry.offer_id == offer_id)
        total = int(self.session.scalar(count) or 0)
        rows = self.session.scalars(
            stmt.order_by(AuditLogEntry.id.desc()).limit(limit).offset(offset)
        )
        return total, list(rows)
