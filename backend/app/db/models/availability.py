"""Voluntary availability shared by off-shift physicians (off-shift portal).

A physician says "I could cover an extra shift between these times". It is a preference
the scheduling system reads; it never assigns a shift and never bypasses the split-shift
rules or the clinical-lead approval. Rows are scoped to the dataset import they were made
under (like offers), are never deleted (withdrawal is a status) and every change is
audited in ``wf_audit_log``. The table name is new, so existing databases gain it
additively (``create_all``) without a schema rebuild.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime


class AvailabilityRecord(Base):
    __tablename__ = "wf_availability"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    physician_id: Mapped[str] = mapped_column(String(128), index=True)
    display_name: Mapped[str] = mapped_column(String(256))
    dataset_import_id: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    """``active`` or ``withdrawn``."""
    start_at: Mapped[datetime] = mapped_column(UTCDateTime)
    end_at: Mapped[datetime] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    """Simulation time of submission."""
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    """Simulation time of the latest change."""
    withdrawn_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime)
    """Wall-clock time of the latest change (audit only)."""
    version: Mapped[int] = mapped_column(Integer, default=1)
