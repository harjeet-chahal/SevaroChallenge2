from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from app.engines.demand.model import HospitalDemandModel
from app.engines.rules import DemandRule
from app.schemas.demand import DemandReport, HospitalDemand
from app.schemas.hospital import Hospital


def build_demand_report(
    models: Mapping[str, HospitalDemandModel],
    hospitals: Mapping[str, Hospital],
    as_of: datetime,
    horizon_end: datetime,
    rule: DemandRule,
) -> DemandReport:
    rows = []
    for hospital_id in sorted(models):
        model = models[hospital_id]
        hospital = hospitals[hospital_id]
        rows.append(
            HospitalDemand(
                hospital_id=hospital_id,
                hospital_name=hospital.name,
                timezone=hospital.timezone,
                current=model.evaluate(as_of),
                spike_ends_at=model.spike_end(horizon_end),
                consults_without_received_time=model.consults_without_received_time,
            )
        )
    return DemandReport(
        as_of=as_of,
        window_minutes=rule.window_minutes,
        requirement_increase=rule.requirement_increase,
        rule=rule.reference,
        method=(
            f"Distinct consults with consult_received event_time in the half-open window "
            f"(t - {rule.window_minutes} min, t], using only events visible at the simulation "
            "time, compared with the p90 for the hospital-local clock hour containing t "
            "(IANA zone, DST-aware). Spike when arrivals > p90; the requirement rises by "
            f"{rule.requirement_increase}. Missing baselines are reported, never substituted."
        ),
        hospitals=rows,
    )
