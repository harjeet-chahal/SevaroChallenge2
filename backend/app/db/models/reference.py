"""Reference data loaded from the dataset: hospitals, physicians, credentials, requirements.

Columns here are the *internal* model. The importer maps source CSV columns onto them,
and any unmapped source columns are kept in ``attributes``.
"""

from __future__ import annotations

from datetime import datetime, time
from typing import Any

from sqlalchemy import JSON, Float, ForeignKey, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime


class HospitalRecord(Base):
    __tablename__ = "hospitals"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(256))
    timezone: Mapped[str] = mapped_column(String(64))
    coverage_tier: Mapped[str | None] = mapped_column(String(64))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PhysicianRecord(Base):
    __tablename__ = "physicians"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(256))
    roster: Mapped[str] = mapped_column(String(16))
    """on_shift or off_shift: which roster file the physician came from."""
    roster_role: Mapped[str | None] = mapped_column(String(64))
    split_shift_opt_in: Mapped[bool | None]
    notification_channel: Mapped[str | None] = mapped_column(String(64))
    shift_start_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    shift_end_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_shift_ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    next_shift_starts_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    hours_worked_trailing_7d: Mapped[float | None] = mapped_column(Float)
    minutes_to_come_online: Mapped[int | None] = mapped_column(Integer)
    offers_declined_30d: Mapped[int | None] = mapped_column(Integer)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)


class PhysicianCredential(Base):
    __tablename__ = "physician_credentials"

    physician_id: Mapped[str] = mapped_column(
        ForeignKey("physicians.id", ondelete="CASCADE"), primary_key=True
    )
    hospital_id: Mapped[str] = mapped_column(
        ForeignKey("hospitals.id", ondelete="CASCADE"), primary_key=True
    )


class CoverageRequirementRecord(Base):
    __tablename__ = "coverage_requirements"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    hospital_id: Mapped[str] = mapped_column(
        ForeignKey("hospitals.id", ondelete="CASCADE"), index=True
    )
    block_start_local: Mapped[time] = mapped_column(Time)
    block_end_local: Mapped[time] = mapped_column(Time)
    min_available_physicians: Mapped[int] = mapped_column(Integer)
    day_type: Mapped[str | None] = mapped_column(String(32))


class BaselineVolumeRecord(Base):
    __tablename__ = "baseline_volume"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    hospital_id: Mapped[str] = mapped_column(
        ForeignKey("hospitals.id", ondelete="CASCADE"), index=True
    )
    hour_local: Mapped[int] = mapped_column(Integer)
    mean_consults: Mapped[float] = mapped_column(Float)
    p90_consults: Mapped[float] = mapped_column(Float)
    day_type: Mapped[str | None] = mapped_column(String(32))


class ReferenceSnapshotRow(Base):
    """Rows from optional reference snapshot files, kept verbatim for verification only.

    Never loaded as live state: the replay must reproduce these values on its own.
    """

    __tablename__ = "reference_snapshot_rows"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    file: Mapped[str] = mapped_column(String(256))
    kind: Mapped[str] = mapped_column(String(32))
    """physicians, consults or unknown (detected from the columns)."""
    row_number: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
