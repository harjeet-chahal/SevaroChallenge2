"""Health and configuration reporting."""

from __future__ import annotations

import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.time import utc_now
from app.repositories.system import SystemRepository
from app.repositories.workflow import WorkflowRepository
from app.schemas.system import ComponentHealth, ConfigResponse, HealthResponse

logger = logging.getLogger(__name__)


class SystemService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.repo = SystemRepository(session)
        self.settings = settings

    def health(self) -> HealthResponse:
        try:
            self.repo.ping()
            database = ComponentHealth(status="ok")
        except SQLAlchemyError as exc:
            logger.warning("Database health check failed: %s", exc)
            database = ComponentHealth(status="error", detail="Database unreachable")

        return HealthResponse(
            status="ok" if database.status == "ok" else "degraded",
            version=self.settings.app_version,
            environment=self.settings.app_env,
            checked_at=utc_now(),
            database=database,
        )

    def config(self) -> ConfigResponse:
        state = self.repo.get_simulation_state()
        dataset_loaded = bool(state and state.active_import_id)
        workflow = WorkflowRepository(self.repo.session)

        if dataset_loaded and state and state.current_time is not None:
            simulation_time = state.current_time
            source = "dataset" if state.current_time == state.reference_time else "manual"
        elif self.settings.simulation_reference_time is not None:
            simulation_time = self.settings.simulation_reference_time
            source = "environment"
        else:
            simulation_time = None
            source = "unset"

        return ConfigResponse(
            app_name=self.settings.app_name,
            version=self.settings.app_version,
            environment=self.settings.app_env,
            simulation_time=simulation_time,
            simulation_time_source=source,
            dataset_loaded=dataset_loaded,
            data_version=state.data_version if state else 0,
            workflow_version=workflow.workflow_version(),
            pending_approvals=(
                len(
                    workflow.list_interventions(
                        import_id=state.active_import_id, statuses=["pending_approval"]
                    )
                )
                if state and state.active_import_id
                else 0
            ),
            server_time=utc_now(),
        )
