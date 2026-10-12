"""Run the Phase 3 analysis for a simulation time, with a small in-process cache.

The cache key is (data_version, as_of, horizon, step, rules signature). data_version
changes on every import, injected event and staffing-relevant workflow decision (accept,
activate, end of a split shift), and as_of changes when the clock moves, so a cached
result is never stale. No external infrastructure is involved.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.engines.analysis import OperationalAnalysis, analyze
from app.engines.optimization import load_optimization_config
from app.engines.optimization.split_shift.candidates import stranded_urgent_consults
from app.engines.rules import RiskConfig, load_risk_config
from app.services.state import StateService


class AnalysisCache:
    def __init__(self, maxsize: int = 16) -> None:
        self.maxsize = maxsize
        self._items: OrderedDict[tuple, OperationalAnalysis] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: tuple) -> OperationalAnalysis | None:
        with self._lock:
            item = self._items.get(key)
            if item is not None:
                self._items.move_to_end(key)
            return item

    def clear(self) -> None:
        """Drop everything (after a rolled-back workflow transaction, so no result computed
        from uncommitted state can be served later under a reused version number)."""
        with self._lock:
            self._items.clear()

    def put(self, key: tuple, value: OperationalAnalysis) -> None:
        with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self.maxsize:
                self._items.popitem(last=False)


class AnalysisService:
    def __init__(self, session: Session, settings: Settings, cache: AnalysisCache) -> None:
        self.settings = settings
        self.cache = cache
        self.states = StateService(session, settings)

    def config(self) -> RiskConfig:
        return load_risk_config(self.settings.resolved_risk_rules_file)

    def analysis(
        self,
        as_of: datetime | None = None,
        *,
        horizon_minutes: int | None = None,
        step_minutes: int | None = None,
    ) -> OperationalAnalysis:
        moment = self.states.resolve_as_of(as_of)
        config = self.config()
        horizon = horizon_minutes or config.coverage.horizon_minutes
        step = step_minutes or config.coverage.chart_step_minutes
        version = self.states.simulation.data_version()
        # Stranded urgent consults (routing finds no one on duty) count in the forecast; the
        # routing and staffing policy lives in the optimization config.
        policy = load_optimization_config(self.settings.resolved_optimization_policy_file)
        key = (version, moment.isoformat(), horizon, step, config.signature(), policy.signature())
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        events, reference, version = self.states.load_inputs()
        result = analyze(
            events,
            reference,
            moment,
            config,
            data_version=version,
            horizon_minutes=horizon,
            step_minutes=step,
            overlay=self.states.overlay(),
            stranded=lambda first: stranded_urgent_consults(first, policy),
        )
        self.cache.put(key, result)
        return result
