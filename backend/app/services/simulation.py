"""The simulation clock. It moves only when told to; it never follows the wall clock."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import ConflictError
from app.core.time import to_utc, utc_now
from app.repositories import EventRepository, SystemRepository
from app.schemas.simulation import SimulationClock


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

    def set_time(self, moment: datetime) -> SimulationClock:
        return self._move(moment)

    def advance(self, delta: timedelta) -> SimulationClock:
        return self._move(self.require_current_time() + delta)

    def reset(self) -> SimulationClock:
        self.require_current_time()
        state = self.system.get_simulation_state()
        if state is None or state.reference_time is None:
            raise ConflictError("The active dataset has no reference time to reset to.")
        return self._move(state.reference_time)
