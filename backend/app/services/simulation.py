"""The simulation clock. It moves only when told to; it never follows the wall clock."""

from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError, ConflictError
from app.core.time import to_utc, utc_now
from app.repositories import EventRepository, SystemRepository
from app.schemas.simulation import SUPPORTED_RANGE, SimulationClock, is_supported_time

CLOCK_MARGIN = timedelta(days=366)
"""How far the clock may be set or advanced beyond the loaded data (earliest/latest event
and the reference time). Further out every view is empty, and moving there would still
run the workflow sweep (expiring offers, ending shifts)."""


class SimulationService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.system = SystemRepository(session)
        self.events = EventRepository(session)

    def dataset_loaded(self) -> bool:
        state = self.system.get_simulation_state()
        return bool(state and state.active_import_id)

    def current_time(self) -> datetime | None:
        state = self.system.get_simulation_state()
        return state.current_time if state else None

    def require_current_time(self) -> datetime:
        current = self.current_time()
        if current is None or not self.dataset_loaded():
            raise ConflictError(
                "No dataset is loaded, so there is no simulation time yet.",
                code="no_dataset",
                details={"hint": "POST /api/datasets/import or /api/datasets/sample first."},
            )
        return current

    def data_version(self) -> int:
        state = self.system.get_simulation_state()
        return state.data_version if state else 0

    def clock(self) -> SimulationClock:
        state = self.system.get_simulation_state()
        loaded = self.dataset_loaded()
        first, last, last_ingested = self.events.bounds() if loaded else (None, None, None)
        current = state.current_time if state else None
        return SimulationClock(
            current_time=current,
            reference_time=state.reference_time if state else None,
            reference_source=state.reference_source if state else None,  # type: ignore[arg-type]
            server_time=utc_now(),
            dataset_loaded=loaded,
            data_version=state.data_version if state else 0,
            first_event_time=first,
            last_event_time=last,
            last_ingested_at=last_ingested,
            events_pending_ingestion=(
                self.events.count_ingested_after(current) if loaded and current else 0
            ),
        )

    def _move(self, new_time: datetime) -> SimulationClock:
        self.require_current_time()
        state = self.system.get_or_create_simulation_state(utc_now())
        state.current_time = to_utc(new_time)
        state.updated_at = utc_now()
        self.session.commit()
        return self.clock()

    def _out_of_range(self, message: str, **details: object) -> AppError:
        return AppError(
            message,
            code="simulation_time_out_of_range",
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            details={key: value for key, value in details.items() if value is not None},
        )

    def _check_range(self, moment: datetime) -> None:
        """Keep the clock where the replay is meaningful (and date arithmetic is safe)."""
        if not is_supported_time(moment):
            raise self._out_of_range(
                f"Simulation time must be within {SUPPORTED_RANGE}.", requested=moment
            )
        state = self.system.get_simulation_state()
        anchors = [t for t in (*self.events.bounds(), state and state.reference_time) if t]
        if not anchors:
            return
        earliest, latest = min(anchors) - CLOCK_MARGIN, max(anchors) + CLOCK_MARGIN
        if not earliest <= to_utc(moment) <= latest:
            raise self._out_of_range(
                "Simulation time must be within a year of the loaded dataset "
                f"({earliest.isoformat()} to {latest.isoformat()}).",
                requested=moment,
                earliest=earliest,
                latest=latest,
            )

    def set_time(self, moment: datetime) -> SimulationClock:
        self.require_current_time()
        self._check_range(moment)
        return self._move(moment)

    def advance(self, delta: timedelta) -> SimulationClock:
        current = self.require_current_time()
        try:
            target = current + delta
        except OverflowError as exc:
            raise self._out_of_range(
                f"Simulation time must be within {SUPPORTED_RANGE}.", current=current
            ) from exc
        self._check_range(target)
        return self._move(target)

    def reset(self) -> SimulationClock:
        self.require_current_time()
        state = self.system.get_simulation_state()
        if state is None or state.reference_time is None:
            raise ConflictError("The active dataset has no reference time to reset to.")
        return self._move(state.reference_time)
