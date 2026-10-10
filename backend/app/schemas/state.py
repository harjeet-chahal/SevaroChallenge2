"""Reference data in, reconstructed operational state out."""

from __future__ import annotations

from pydantic import AwareDatetime, Field

from app.schemas.common import ApiModel, EntityId
from app.schemas.consultation import ConsultationState, StateAnomaly
from app.schemas.coverage import BaselineVolume, CoverageRequirement
from app.schemas.hospital import Hospital
from app.schemas.physician import Physician, PhysicianState


class ReferenceData(ApiModel):
    """Static dataset facts the replay needs (rosters, hospitals, credentials).

    Coverage requirements and baselines are carried for later engines; the replay
    itself does not interpret them.
    """

    hospitals: list[Hospital] = Field(default_factory=list)
    physicians: list[Physician] = Field(default_factory=list)
    coverage_requirements: list[CoverageRequirement] = Field(default_factory=list)
    baseline_volume: list[BaselineVolume] = Field(default_factory=list)


class StateSummary(ApiModel):
    """Plain counts over the reconstructed state. No forecasting or risk scoring."""

    physicians_total: int = Field(ge=0)
    physicians_on_shift: int = Field(ge=0)
    on_shift_busy: int = Field(ge=0)
    on_shift_available: int = Field(ge=0)
    on_shift_unavailable: int = Field(ge=0)
    physicians_flagged: int = Field(ge=0)
    """Physicians with at least one warning-level signal flag."""
    consults_open: int = Field(ge=0)
    consults_open_assigned: int = Field(ge=0)
    consults_open_unassigned: int = Field(ge=0)
    consults_closed: int = Field(ge=0)
    open_consults_by_stage: dict[str, int] = Field(default_factory=dict)


class ReplayDiagnostics(ApiModel):
    events_total: int = Field(ge=0)
    events_applied: int = Field(ge=0)
    events_not_yet_ingested: int = Field(ge=0)
    """Ingested after as_of: invisible at this time."""
    events_future_event_time: int = Field(ge=0)
    """Ingested by as_of but timestamped after it (clock skew); not applied yet."""
    duplicates_skipped: int = Field(ge=0)
    conflicting_duplicates: int = Field(ge=0)
    late_arrivals_applied: int = Field(ge=0)
    """Applied events that arrived after an event with a later event_time."""
    unknown_event_types: dict[str, int] = Field(default_factory=dict)
    unknown_physician_ids: list[EntityId] = Field(default_factory=list)
    unknown_hospital_ids: list[EntityId] = Field(default_factory=list)
    anomalies: list[StateAnomaly] = Field(default_factory=list)


class OperationalState(ApiModel):
    as_of: AwareDatetime
    data_version: int = 0
    summary: StateSummary
    physicians: list[PhysicianState]
    consultations: list[ConsultationState]
    hospitals: list[Hospital]
    diagnostics: ReplayDiagnostics
