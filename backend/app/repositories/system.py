"""Data access for application-level state. Repositories never contain business rules."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db.models import DatasetImport, SimulationState
from app.schemas.dataset import DatasetImportReport, DatasetImportStatus

SIMULATION_STATE_ROW_ID = 1


class SystemRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def ping(self) -> None:
        self.session.execute(text("SELECT 1"))

    def get_simulation_state(self) -> SimulationState | None:
        return self.session.get(SimulationState, SIMULATION_STATE_ROW_ID)

    def get_or_create_simulation_state(self, now: datetime) -> SimulationState:
        state = self.get_simulation_state()
        if state is None:
            state = SimulationState(id=SIMULATION_STATE_ROW_ID, data_version=0, updated_at=now)
            self.session.add(state)
            self.session.flush()
        return state

    def latest_completed_import(self) -> DatasetImport | None:
        stmt = (
            select(DatasetImport)
            .where(DatasetImport.status == DatasetImportStatus.COMPLETED.value)
            .order_by(DatasetImport.completed_at.desc())
            .limit(1)
        )
        return self.session.scalars(stmt).first()

    def latest_import(self) -> DatasetImport | None:
        stmt = select(DatasetImport).order_by(DatasetImport.started_at.desc()).limit(1)
        return self.session.scalars(stmt).first()

    def get_import(self, import_id: str) -> DatasetImport | None:
        return self.session.get(DatasetImport, import_id)

    def list_imports(self, limit: int = 20) -> list[DatasetImport]:
        stmt = select(DatasetImport).order_by(DatasetImport.started_at.desc()).limit(limit)
        return list(self.session.scalars(stmt))

    def save_import_report(self, report: DatasetImportReport) -> DatasetImport:
        row = self.session.get(DatasetImport, report.import_id) or DatasetImport(
            id=report.import_id
        )
        row.source_name = report.source_name
        row.status = report.status.value
        row.started_at = report.started_at
        row.completed_at = report.completed_at
        row.report = report.model_dump(mode="json")
        self.session.add(row)
        return row
