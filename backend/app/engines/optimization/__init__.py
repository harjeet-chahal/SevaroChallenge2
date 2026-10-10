"""Phase 4 optimizers: consult dispatch (min-cost flow) and split-shift staffing (CP-SAT).

Recommendations only: nothing in this package assigns a consult, creates an offer or
changes staffing. See docs/optimization.md.
"""

from app.engines.optimization.comparison import dispatch_section, staffing_section, trap_section
from app.engines.optimization.config import OptimizationConfig, load_optimization_config
from app.engines.optimization.routing import build_dispatch_problem, run_dispatch
from app.engines.optimization.simulate import ForecastConfig, simulate_intervention
from app.engines.optimization.solvers import SolverUnavailableError, ortools_version
from app.engines.optimization.split_shift import run_staffing

__all__ = [
    "ForecastConfig",
    "OptimizationConfig",
    "SolverUnavailableError",
    "build_dispatch_problem",
    "dispatch_section",
    "load_optimization_config",
    "ortools_version",
    "run_dispatch",
    "run_staffing",
    "simulate_intervention",
    "staffing_section",
    "trap_section",
]
