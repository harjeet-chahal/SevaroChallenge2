"""Demand-spike detection against hospital-local hourly p90 baselines (see ``model.py``)."""

from app.engines.demand.model import (
    HospitalDemandModel,
    arrivals_in_window,
    build_demand_models,
)
from app.engines.demand.report import build_demand_report

__all__ = [
    "HospitalDemandModel",
    "arrivals_in_window",
    "build_demand_models",
    "build_demand_report",
]
