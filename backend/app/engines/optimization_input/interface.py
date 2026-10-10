"""Solver extension points defined in Phase 3.

Phase 4 implements them in ``app.engines.optimization`` (``run_dispatch`` with OR-Tools
min-cost flow, ``run_staffing`` with CP-SAT), working directly from the Phase 3
``OperationalAnalysis`` so they share its coverage models. Proposals still go through
human approval and never mutate state.
"""

from __future__ import annotations

from typing import Protocol

from app.schemas.optimization import OptimizationInput


class ConsultMatcher(Protocol):
    """Constrained, workload-aware consult -> physician matching (e.g. min-cost flow / CP-SAT)."""

    def propose_assignments(self, problem: OptimizationInput) -> list[dict]: ...


class StaffingOptimizer(Protocol):
    """Split-shift staffing: choose off-shift physicians/windows that minimise deficit
    physician-minutes subject to the brief's eligibility rules and the split-shift trap."""

    def propose_staffing(self, problem: OptimizationInput) -> list[dict]: ...
