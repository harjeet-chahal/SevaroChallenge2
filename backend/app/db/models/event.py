"""Append-only event log. All live operational state is rebuilt from this table.

Duplicates are stored, not dropped: dedupe status is computed during replay
(engines/event_processing/log.py) so the full history stays auditable.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime


class EventLogEntry(Base):
    __tablename__ = "events"

    sequence: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    event_time: Mapped[datetime] = mapped_column(UTCDateTime)
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime)
    event_time_raw: Mapped[str] = mapped_column(String(64))
    ingested_at_raw: Mapped[str] = mapped_column(String(64))
    consult_id: Mapped[str | None] = mapped_column(String(128), index=True)
    physician_id: Mapped[str | None] = mapped_column(String(128), index=True)
    hospital_id: Mapped[str | None] = mapped_column(String(128), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[str] = mapped_column(String(32))
    source_file: Mapped[str | None] = mapped_column(String(256))
    source_row: Mapped[int | None] = mapped_column(Integer)
    import_id: Mapped[str | None] = mapped_column(
        ForeignKey("dataset_imports.id", ondelete="SET NULL")
    )
    content_hash: Mapped[str] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_events_event_time", "event_time"),
        Index("ix_events_ingested_at", "ingested_at"),
    )


class EventRejectionRecord(Base):
    """A record that failed validation. Kept so invalid input is reported, never lost."""

    __tablename__ = "event_rejections"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(32))
    import_id: Mapped[str | None] = mapped_column(
        ForeignKey("dataset_imports.id", ondelete="SET NULL")
    )
    source_file: Mapped[str | None] = mapped_column(String(256))
    source_row: Mapped[int | None] = mapped_column(Integer)
    event_id: Mapped[str | None] = mapped_column(String(128))
    event_type: Mapped[str | None] = mapped_column(String(64))
    errors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime)
