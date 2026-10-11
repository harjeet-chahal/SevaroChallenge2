"""Data access for voluntary availability (``wf_availability``). No business rules here."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AvailabilityRecord
from app.engines.optimization.split_shift.candidates import AvailabilityWindow

ACTIVE = "active"
WITHDRAWN = "withdrawn"


class AvailabilityRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def next_id(self) -> str:
        ids = self.session.scalars(
            select(AvailabilityRecord.id).where(AvailabilityRecord.id.like("AV-%"))
        )
        numbers = [int(i.rsplit("-", 1)[1]) for i in ids if i.rsplit("-", 1)[1].isdigit()]
        return f"AV-{max(numbers, default=0) + 1:04d}"

    def get(self, availability_id: str) -> AvailabilityRecord | None:
        return self.session.get(AvailabilityRecord, availability_id)

    def list(
        self,
        import_id: str | None,
        *,
        physician_id: str | None = None,
        statuses: tuple[str, ...] | None = None,
    ) -> list[AvailabilityRecord]:
        stmt = select(AvailabilityRecord).where(AvailabilityRecord.dataset_import_id == import_id)
        if physician_id is not None:
            stmt = stmt.where(AvailabilityRecord.physician_id == physician_id)
        if statuses:
            stmt = stmt.where(AvailabilityRecord.status.in_(statuses))
        return list(
            self.session.scalars(stmt.order_by(AvailabilityRecord.start_at, AvailabilityRecord.id))
        )

    def windows(self, import_id: str | None) -> dict[str, list[AvailabilityWindow]]:
        """physician_id -> active windows in this dataset import (planning input)."""
        out: dict[str, list[AvailabilityWindow]] = {}
        for r in self.list(import_id, statuses=(ACTIVE,)):
            out.setdefault(r.physician_id, []).append(
                AvailabilityWindow(
                    availability_id=r.id,
                    physician_id=r.physician_id,
                    start=r.start_at,
                    end=r.end_at,
                )
            )
        return out
