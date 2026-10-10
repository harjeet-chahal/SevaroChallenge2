"""Application-level state: schema version, simulation clock and dataset import history."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime


class AppMeta(Base):
    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(String(256))


class SimulationState(Base):
    """Single row: the simulation clock and which dataset is active.

    ``current_time`` is the simulation's "now" and never follows the wall clock.
    ``data_version`` increments on every import or event injection.
    """

    __tablename__ = "simulation_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    current_time: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reference_time: Mapped[datetime | None] = mapped_column(UTCDateTime)
    reference_source: Mapped[str | None] = mapped_column(String(32))
    active_import_id: Mapped[str | None] = mapped_column(String(64))
    data_version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class DatasetImport(Base):
    __tablename__ = "dataset_imports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_name: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(32), index=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    report: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
