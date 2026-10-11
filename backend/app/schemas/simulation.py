"""Simulation clock. Simulated time is independent of the server's wall clock."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import AfterValidator, AwareDatetime, Field, model_validator

from app.schemas.common import ApiModel

MIN_SUPPORTED_YEAR = 1900
MAX_SUPPORTED_YEAR = 2200
SUPPORTED_RANGE = f"years {MIN_SUPPORTED_YEAR}-{MAX_SUPPORTED_YEAR}"
"""Timestamps the engine accepts (events, roster times, the clock, ``as_of``). Far enough
from datetime's limits (years 1-9999) that UTC conversion and the replay's date
arithmetic can never overflow."""


def is_supported_time(value: datetime) -> bool:
    """Checked on the value as given (before UTC conversion, which can itself overflow)."""
    return MIN_SUPPORTED_YEAR <= value.year <= MAX_SUPPORTED_YEAR


def _check_supported_time(value: datetime) -> datetime:
    if not is_supported_time(value):
        raise ValueError(f"{value.isoformat()} is outside the supported range ({SUPPORTED_RANGE})")
    return value


SupportedDatetime = Annotated[AwareDatetime, AfterValidator(_check_supported_time)]
"""An aware datetime within ``SUPPORTED_RANGE``; anything else is a 422 validation error."""

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
    time: SupportedDatetime
    """ISO-8601 with a UTC offset. The service also keeps it near the loaded dataset."""


class AdvanceSimulationRequest(ApiModel):
    minutes: float = Field(default=0, ge=0, le=7 * 24 * 60)
    seconds: float = Field(default=0, ge=0, le=7 * 24 * 3600)

    @model_validator(mode="after")
    def _positive(self) -> Self:
        if self.minutes == 0 and self.seconds == 0:
            raise ValueError("advance by a positive number of minutes or seconds")
        return self
