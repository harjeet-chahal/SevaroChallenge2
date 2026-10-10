from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.db.models import EventLogEntry, EventRejectionRecord
from app.schemas.event import (
    EventRejection,
    EventSource,
    FieldIssue,
    NormalizedEvent,
    StoredEvent,
)

_EVENT_COLUMNS = (
    "event_id",
    "event_type",
    "event_time",
    "ingested_at",
    "event_time_raw",
    "ingested_at_raw",
    "consult_id",
    "physician_id",
    "hospital_id",
    "description",
    "payload",
    "raw",
    "source",
    "source_file",
    "source_row",
    "content_hash",
)


class EventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def load_all(self) -> list[StoredEvent]:
        rows = self.session.scalars(select(EventLogEntry).order_by(EventLogEntry.sequence))
        return [StoredEvent.model_validate(row) for row in rows]

    def add(self, events: Iterable[NormalizedEvent], import_id: str | None) -> int:
        values = [
            {
                **{c: getattr(e, c) for c in _EVENT_COLUMNS},
                "source": e.source.value,
                "import_id": import_id,
            }
            for e in events
        ]
        if values:
            self.session.execute(insert(EventLogEntry), values)
        return len(values)

    def hashes_by_event_id(self, event_ids: Iterable[str]) -> dict[str, list[str]]:
        ids = list(set(event_ids))
        found: dict[str, list[str]] = {}
        if not ids:
            return found
        stmt = (
            select(EventLogEntry.event_id, EventLogEntry.content_hash)
            .where(EventLogEntry.event_id.in_(ids))
            .order_by(EventLogEntry.sequence)
        )
        for event_id, content_hash in self.session.execute(stmt):
            found.setdefault(event_id, []).append(content_hash)
        return found

    def known_consult_ids(self) -> set[str]:
        stmt = (
            select(EventLogEntry.consult_id).where(EventLogEntry.consult_id.is_not(None)).distinct()
        )
        return set(self.session.scalars(stmt))

    def add_rejection(
        self,
        *,
        source: EventSource,
        import_id: str | None,
        source_file: str | None,
        source_row: int | None,
        event_id: str | None,
        event_type: str | None,
        errors: list[FieldIssue],
        raw: dict,
        recorded_at: datetime,
    ) -> None:
        self.session.add(
            EventRejectionRecord(
                source=source.value,
                import_id=import_id,
                source_file=source_file,
                source_row=source_row,
                event_id=event_id,
                event_type=event_type,
                errors=[e.model_dump() for e in errors],
                raw=raw,
                recorded_at=recorded_at,
            )
        )

    def list_rejections(self, limit: int, offset: int) -> tuple[int, list[EventRejection]]:
        total = self.session.scalar(select(func.count()).select_from(EventRejectionRecord)) or 0
        stmt = (
            select(EventRejectionRecord)
            .order_by(EventRejectionRecord.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return total, [EventRejection.model_validate(r) for r in self.session.scalars(stmt)]

    def counts(self) -> dict[str, int]:
        total = self.session.scalar(select(func.count()).select_from(EventLogEntry)) or 0
        live = (
            self.session.scalar(
                select(func.count())
                .select_from(EventLogEntry)
                .where(EventLogEntry.source == EventSource.LIVE_INGEST.value)
            )
            or 0
        )
        rejected = self.session.scalar(select(func.count()).select_from(EventRejectionRecord)) or 0
        return {"events": total, "live_events": live, "rejected_events": rejected}

    def bounds(self) -> tuple[datetime | None, datetime | None, datetime | None]:
        row = self.session.execute(
            select(
                func.min(EventLogEntry.event_time),
                func.max(EventLogEntry.event_time),
                func.max(EventLogEntry.ingested_at),
            )
        ).one()
        # min/max inherit the column type, so values come back as aware UTC datetimes.
        return row[0], row[1], row[2]

    def count_ingested_after(self, moment: datetime) -> int:
        return (
            self.session.scalar(
                select(func.count())
                .select_from(EventLogEntry)
                .where(EventLogEntry.ingested_at > moment)
            )
            or 0
        )

    def delete_all(self) -> None:
        self.session.execute(delete(EventLogEntry))
        self.session.execute(delete(EventRejectionRecord))
