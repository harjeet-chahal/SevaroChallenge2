"""Builders for engine tests. Timestamps use a non-UTC offset on purpose."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.engines.event_processing import normalize_event
from app.schemas.event import EventSource, StoredEvent
from app.schemas.hospital import Hospital
from app.schemas.physician import Physician, PhysicianSchedule, ShiftWindow
from app.schemas.state import ReferenceData

LOCAL = timezone(timedelta(hours=-6))
BASE = datetime(2031, 2, 3, 9, 0, tzinfo=LOCAL)


def t(minutes: float) -> datetime:
    return BASE + timedelta(minutes=minutes)


class EventFactory:
    def __init__(self) -> None:
        self.sequence = 0

    def __call__(
        self,
        event_type: str,
        at: float,
        *,
        ingested: float | None = None,
        event_id: str | None = None,
        consult: str | None = None,
        physician: str | None = None,
        hospital: str | None = None,
        status: str | None = None,
        consult_type: str | None = None,
        description: str | None = None,
    ) -> StoredEvent:
        self.sequence += 1
        fields = {
            "event_id": event_id or f"E{self.sequence:04d}",
            "event_type": event_type,
            "event_time": t(at).isoformat(),
            "ingested_at": t(ingested if ingested is not None else at + 0.05).isoformat(),
            "consult_id": consult,
            "physician_id": physician,
            "hospital_id": hospital,
            "status": status,
            "consult_type": consult_type,
            "description": description,
        }
        result = normalize_event(fields, source=EventSource.LIVE_INGEST)
        return StoredEvent(**result.event.model_dump(), sequence=self.sequence)


def reference(*physician_ids: str, shift: tuple[float, float] = (-60, 600)) -> ReferenceData:
    return ReferenceData(
        hospitals=[
            Hospital(id="H1", name="Test Hospital One", timezone="America/Chicago"),
            Hospital(id="H2", name="Test Hospital Two", timezone="America/Denver"),
        ],
        physicians=[
            Physician(
                id=pid,
                display_name=f"Dr {pid}",
                roster="on_shift",
                schedule=PhysicianSchedule(
                    current_shift=ShiftWindow(start=t(shift[0]), end=t(shift[1]))
                ),
            )
            for pid in physician_ids
        ],
    )


def consult_flow(ev: EventFactory, consult: str, physician: str, start: float) -> list[StoredEvent]:
    """received -> triaged -> assigned -> contacted (incoming call) at minute offsets."""
    return [
        ev("consult_received", start, consult=consult, hospital="H1", consult_type="Stroke"),
        ev("consult_triaged", start + 1, consult=consult, hospital="H1"),
        ev("physician_assigned", start + 2, consult=consult, physician=physician, hospital="H1"),
        ev("incoming_call_started", start + 3, consult=consult, physician=physician, hospital="H1"),
    ]
