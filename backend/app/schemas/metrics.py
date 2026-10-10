from __future__ import annotations

from pydantic import AwareDatetime, Field

from app.schemas.common import ApiModel, EntityId


class PhysicianWorkload(ApiModel):
    physician_id: EntityId
    display_name: str
    on_shift: bool | None
    availability: str
    consults_this_shift: int
    calls_this_shift: int
    open_consults: int
    credentialed_hospitals: int
    """Shown next to workload: uneven load can come from credentialing, not effort."""


class OperationalMetrics(ApiModel):
    as_of: AwareDatetime
    data_version: int
    physicians: dict[str, int]
    consults: dict[str, int]
    open_consults_by_stage: dict[str, int]
    longest_open_wait_seconds: int | None
    alerts_by_severity: dict[str, int]
    alerts_by_rule: dict[str, int]
    coverage: dict[str, float | int | None]
    earliest_projected_gap_at: AwareDatetime | None = None
    earliest_projected_gap_hospital_id: EntityId | None = None
    demand: dict[str, int]
    workload: list[PhysicianWorkload] = Field(default_factory=list)
    disclaimer: str = (
        "Coverage figures are modeled from schedules, credentials and current signals; "
        "they are not measured patient outcomes."
    )
