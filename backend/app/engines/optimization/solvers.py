"""OR-Tools import guard. If OR-Tools is missing, callers get ``None`` and must use a
clearly labelled fallback — never pretend a solver ran."""

from __future__ import annotations

from types import ModuleType


class SolverUnavailableError(RuntimeError):
    """OR-Tools is not installed and the policy forbids the labelled fallback."""


def load_min_cost_flow() -> ModuleType | None:
    try:
        from ortools.graph.python import min_cost_flow
    except ImportError:  # pragma: no cover - exercised via monkeypatch in tests
        return None
    return min_cost_flow


def load_cp_model() -> ModuleType | None:
    try:
        from ortools.sat.python import cp_model
    except ImportError:  # pragma: no cover
        return None
    return cp_model


def ortools_version() -> str | None:
    try:
        import ortools
    except ImportError:  # pragma: no cover
        return None
    return ortools.__version__
