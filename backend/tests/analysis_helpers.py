"""Small scenario builder for Phase 3 engine tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta

from app.engines.analysis import OperationalAnalysis, analyze
from app.engines.event_processing import normalize_event
from app.engines.rules import RiskConfig
from app.schemas.coverage import BaselineVolume, CoverageRequirement
from app.schemas.event import EventSource, StoredEvent
from app.schemas.hospital import Hospital
from app.schemas.physician import Physician, PhysicianSchedule, ShiftWindow
from app.schemas.state import ReferenceData


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)


@dataclass
class Scenario:
    hospitals: list[Hospital] = field(default_factory=list)
    physicians: list[Physician] = field(default_factory=list)
    requirements: list[CoverageRequirement] = field(default_factory=list)
    baselines: list[BaselineVolume] = field(default_factory=list)
    events: list[StoredEvent] = field(default_factory=list)

    def hospital(self, hid: str, tz: str = "America/Chicago") -> Scenario:
        self.hospitals.append(Hospital(id=hid, name=f"Hospital {hid}", timezone=tz))
        return self

    def on_shift(self, pid: str, creds: list[str], start: datetime, end: datetime) -> Scenario:
        self.physicians.append(
            Physician(
                id=pid,
                display_name=f"Dr {pid}",
                roster="on_shift",
                credentialed_hospital_ids=creds,
                schedule=PhysicianSchedule(current_shift=ShiftWindow(start=start, end=end)),
            )
        )
        return self

    def off_shift(
        self, pid: str, creds: list[str], next_start: datetime | None, online: int | None = None
    ) -> Scenario:
        self.physicians.append(
            Physician(
                id=pid,
                display_name=f"Dr {pid}",
                roster="off_shift",
                credentialed_hospital_ids=creds,
                schedule=PhysicianSchedule(
                    next_shift_starts_at=next_start, minutes_to_come_online=online
                ),
            )
        )
        return self

    def requirement(
        self, hid: str, start: str, end: str, n: int, day_type: str | None = None
    ) -> Scenario:
        self.requirements.append(
            CoverageRequirement(
                hospital_id=hid,
                block_start_local=time.fromisoformat(start),
                block_end_local=time.fromisoformat(end),
                min_available_physicians=n,
                day_type=day_type,
            )
        )
        return self

    def baseline(self, hid: str, hour: int, p90: float, day_type: str | None = None) -> Scenario:
        self.baselines.append(
            BaselineVolume(
                hospital_id=hid,
                hour_local=hour,
                mean_consults=p90 / 2,
                p90_consults=p90,
                day_type=day_type,
            )
        )
        return self

    def event(
        self,
        event_type: str,
        when: datetime,
        *,
        ingested: datetime | None = None,
        event_id: str | None = None,
        **fields: str,
    ) -> Scenario:
        seq = len(self.events) + 1
        record = {
            "event_id": event_id or f"E{seq:04d}",
            "event_type": event_type,
            "event_time": when.isoformat(),
            "ingested_at": (ingested or when + timedelta(seconds=1)).isoformat(),
            **fields,
        }
        result = normalize_event(record, source=EventSource.LIVE_INGEST)
        self.events.append(StoredEvent(**result.event.model_dump(), sequence=seq))
        return self

    @property
    def reference(self) -> ReferenceData:
        return ReferenceData(
            hospitals=self.hospitals,
            physicians=self.physicians,
            coverage_requirements=self.requirements,
            baseline_volume=self.baselines,
        )

    def analyze(
        self, as_of: datetime, config: RiskConfig | None = None, **kw
    ) -> OperationalAnalysis:
        return analyze(self.events, self.reference, as_of, config, **kw)


def hospital_coverage(analysis: OperationalAnalysis, hid: str):
    return next(h for h in analysis.coverage.hospitals if h.hospital_id == hid)


def alerts_by_id(analysis: OperationalAnalysis) -> dict:
    return {a.alert_id: a for a in analysis.alerts.alerts}


def segments(analysis: OperationalAnalysis, hid: str) -> list[tuple]:
    """(start, end, required, available, deficit) tuples for compact assertions."""
    return [
        (s.start, s.end, s.required, s.available, s.deficit)
        for s in hospital_coverage(analysis, hid).segments
    ]
