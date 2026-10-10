"""Load the event log + reference data and run the pure replay."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.time import to_utc
from app.engines.interventions.overlay import OverlayEntry, apply_workflow_overlay
from app.engines.replay import reconstruct_state
from app.repositories import EventRepository, ReferenceRepository
from app.repositories.workflow import WorkflowRepository
from app.schemas.event import StoredEvent
from app.schemas.state import OperationalState, ReferenceData
from app.services.simulation import SimulationService


class StateService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.simulation = SimulationService(session, settings)

    def resolve_as_of(self, as_of: datetime | None) -> datetime:
        current = self.simulation.require_current_time()
        return to_utc(as_of) if as_of is not None else current

    def load_inputs(self) -> tuple[list[StoredEvent], ReferenceData, int]:
        """Everything the pure engines need from the database."""
        return (
            EventRepository(self.session).load_all(),
            ReferenceRepository(self.session).load(),
            self.simulation.data_version(),
        )

    def overlay(self) -> list[OverlayEntry]:
        """Accepted/activated split shifts of the active dataset (Phase 5 workflow)."""
        state = self.simulation.system.get_simulation_state()
        return WorkflowRepository(self.session).overlay_entries(
            state.active_import_id if state else None
        )

    def state(
        self, as_of: datetime | None = None, *, with_workflow: bool = True
    ) -> OperationalState:
        """Replayed state, with workflow decisions applied on top unless
        ``with_workflow=False`` (used to verify the pure replay against snapshots)."""
        moment = self.resolve_as_of(as_of)
        events, reference, version = self.load_inputs()
        state = reconstruct_state(events, moment, reference, data_version=version)
        if with_workflow:
            entries = self.overlay()
            if entries:
                state, _ = apply_workflow_overlay(state, reference, entries)
        return state
