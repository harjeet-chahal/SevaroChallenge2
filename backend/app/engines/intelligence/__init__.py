"""NEUROGRID intelligence layer: pure analyses on top of the Phase 3-5 engines.

Every function takes already-computed engine outputs (analysis, coverage models, staffing
internals) and returns a schema. No database access, no wall clock.
"""

from app.engines.intelligence.availability import availability_report, class_map, classify
from app.engines.intelligence.common import planning_models, single_point_physicians
from app.engines.intelligence.config import IntelligenceConfig, load_intelligence_config
from app.engines.intelligence.genome import genome_report
from app.engines.intelligence.network import fragility_report
from app.engines.intelligence.operations import (
    coverage_debt_report,
    handoff_report,
    problem_report,
)
from app.engines.intelligence.rescue_planning import last_safe_moment_report, scarcity_report
from app.engines.intelligence.simulator import (
    load_guardian_report,
    options_by_hospital,
    simulate_rescues,
)
from app.engines.intelligence.time_machine import time_machine_report

__all__ = [
    "IntelligenceConfig",
    "availability_report",
    "class_map",
    "classify",
    "coverage_debt_report",
    "fragility_report",
    "genome_report",
    "handoff_report",
    "last_safe_moment_report",
    "load_guardian_report",
    "load_intelligence_config",
    "options_by_hospital",
    "planning_models",
    "problem_report",
    "scarcity_report",
    "simulate_rescues",
    "single_point_physicians",
    "time_machine_report",
]
