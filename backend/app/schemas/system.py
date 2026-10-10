from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime

from app.schemas.common import ApiModel


class ComponentHealth(ApiModel):
    status: Literal["ok", "error"]
    detail: str | None = None


class HealthResponse(ApiModel):
    status: Literal["ok", "degraded"]
    version: str
    environment: str
    checked_at: AwareDatetime
    database: ComponentHealth


class ConfigResponse(ApiModel):
    app_name: str
    version: str
    environment: str
    simulation_time: AwareDatetime | None
    """The simulation's "now". Null until a dataset is loaded or a time is set."""
    simulation_time_source: Literal["environment", "dataset", "manual", "unset"]
    """environment: SIMULATION_REFERENCE_TIME with no dataset loaded; dataset: clock is at the
    dataset reference time; manual: clock was set or advanced; unset: no time yet."""
    dataset_loaded: bool
    data_version: int = 0
    """Changes whenever the dataset, the event log or derived staffing (an accepted,
    activated or ended split shift) changes, so clients know to refetch."""
    workflow_version: int = 0
    """Changes on every workflow transition (proposal, decision, offer, response, ...)."""
    pending_approvals: int = 0
    server_time: AwareDatetime | None = None
