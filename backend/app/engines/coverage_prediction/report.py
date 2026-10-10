from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta

from app.engines.coverage_prediction.forecast import (
    HospitalCoverageModel,
    build_hospital_coverage,
    build_hospital_model,
)
from app.engines.demand import HospitalDemandModel
from app.engines.rules import CoverageRule
from app.schemas.coverage import CoverageReport
from app.schemas.state import OperationalState, ReferenceData

METHOD = (
    "Deterministic piecewise-constant simulation. Change points: simulation time, horizon "
    "end, physician shift starts/ends, local coverage-block boundaries, local hour boundaries, "
    "arrivals leaving the 60-minute demand window, and UTC-offset (DST) transitions. Between "
    "change points required R(t) and available A(t) are constant; deficit = max(0, R - A); "
    "physician-minutes = exact sum over segments. Chart interval samples are display-only."
)


def coverage_assumptions(rule: CoverageRule) -> list[str]:
    return [
        "A physician counts toward every hospital they are credentialed at (per-hospital, "
        "non-exclusive counting, as the brief defines coverage).",
        "Busy physicians (on a call or video) count as available coverage: they are on duty."
        if rule.busy_counts_as_available
        else "Busy physicians are excluded from coverage (configuration).",
        "Temporarily Unavailable physicians stay excluded for the horizon (no return time known)."
        if rule.unavailable_persists
        else "Temporarily Unavailable physicians are counted as uncertain (configuration).",
        "Physicians with an unknown shift end are counted through the horizon and marked "
        "uncertain; "
        "no end time is invented.",
        "Offline desktop agents keep the physician counted (routing assumes available) but "
        "uncertain.",
        "Future consult arrivals are not assumed: projected demand spikes use only arrivals "
        "already "
        "visible at the simulation time.",
        "Off-shift roster physicians count from their next scheduled shift start if it falls in "
        "the horizon.",
    ]


def build_coverage_models(
    state: OperationalState,
    reference: ReferenceData,
    demand: Mapping[str, HospitalDemandModel],
    rule: CoverageRule,
    horizon_minutes: int,
) -> dict[str, HospitalCoverageModel]:
    as_of = state.as_of
    horizon_end = as_of + timedelta(minutes=horizon_minutes)
    return {
        h.id: build_hospital_model(
            h,
            state.physicians,
            reference.coverage_requirements,
            demand.get(h.id),
            as_of,
            horizon_end,
            rule,
        )
        for h in sorted(state.hospitals, key=lambda h: h.id)
    }


def build_coverage_report(
    models: Mapping[str, HospitalCoverageModel],
    as_of: datetime,
    rule: CoverageRule,
    horizon_minutes: int,
    step_minutes: int,
    data_version: int,
) -> CoverageReport:
    return CoverageReport(
        as_of=as_of,
        horizon_minutes=horizon_minutes,
        horizon_end=as_of + timedelta(minutes=horizon_minutes),
        chart_step_minutes=step_minutes,
        data_version=data_version,
        method=METHOD,
        assumptions=coverage_assumptions(rule),
        hospitals=[
            build_hospital_coverage(m, step_minutes=step_minutes, horizon_minutes=horizon_minutes)
            for _, m in sorted(models.items())
        ],
    )
