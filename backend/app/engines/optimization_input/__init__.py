"""Optimizer-ready snapshot for Phase 4 (data only; no solver here)."""

from app.engines.optimization_input.build import (
    build_optimization_input,
    candidate_interventions,
)
from app.engines.optimization_input.interface import ConsultMatcher, StaffingOptimizer

__all__ = [
    "ConsultMatcher",
    "StaffingOptimizer",
    "build_optimization_input",
    "candidate_interventions",
]
