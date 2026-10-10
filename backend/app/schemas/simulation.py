"""Simulation clock. Simulated time is independent of the server's wall clock."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from app.schemas.common import ApiModel

ReferenceTimeSource = Literal[
    "import_option",
    "environment",
    "dataset_manifest",
    "snapshot_filename",
    "latest_ingested_at",
]


class SimulationClock(ApiModel):
    current_time: AwareDatetime | None
    """The simulation's "now". All state endpoints default to this."""
    reference_time: AwareDatetime | None
    """Where reset returns to; usually the dataset's documented reference point."""
    reference_source: ReferenceTimeSource | None
    server_time: AwareDatetime
    """Real wall-clock time on the server, shown only to make the distinction explicit."""
    dataset_loaded: bool
    data_version: int
    first_event_time: AwareDatetime | None = None
    last_event_time: AwareDatetime | None = None
    last_ingested_at: AwareDatetime | None = None
    events_pending_ingestion: int = 0
    """Stored events whose ingested_at is still in the simulated future."""


class SetSimulationTimeRequest(ApiModel):
    time: AwareDatetime
    """ISO-8601 with a UTC offset."""


class AdvanceSimulationRequest(ApiModel):
    minutes: float = Field(default=0, ge=0, le=7 * 24 * 60)
    seconds: float = Field(default=0, ge=0, le=7 * 24 * 3600)

    @model_validator(mode="after")
    def _positive(self) -> Self:
        if self.minutes == 0 and self.seconds == 0:
            raise ValueError("advance by a positive number of minutes or seconds")
        return self
