"""NEUROGRID intelligence policy. Every number here is an explicit, documented assumption
(see docs/ASSUMPTIONS.md), not a value derived from the challenge data. Override with
``INTELLIGENCE_POLICY_FILE`` (JSON with the same keys)."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field


class LeadTimePolicy(BaseModel):
    approval_minutes: int = Field(default=5, ge=0)
    """ASSUMPTION: time for the clinical lead to review and approve a rescue."""
    response_minutes_expected: int = Field(default=4, ge=0)
    """ASSUMPTION: typical time for a physician to answer an offer."""
    response_minutes_conservative: int = Field(default=10, ge=0)
    """BRIEF-derived: an offer can stay unanswered for its full 10-minute life."""
    green_minutes: int = Field(default=30, ge=0)
    """Remaining opportunity window above which the phase is green."""
    red_minutes: int = Field(default=10, ge=0)
    """At or below this remaining window the phase is red (amber in between)."""


class FragilityWeights(BaseModel):
    """Criticality = Σ weight × computed quantity. Configurable, not calibrated."""

    added_deficit_hours: float = 10.0
    newly_uncovered_hospitals: float = 6.0
    sole_coverage_hospitals: float = 4.0
    credentialed_relevant_hospitals: float = 0.5


class DebtPolicy(BaseModel):
    lookback_minutes: int = Field(default=120, ge=0, le=720)
    step_minutes: int = Field(default=5, ge=1, le=60)


class StochasticPolicy(BaseModel):
    runs: int = Field(default=400, ge=10, le=5000)
    seed: int = 20260317
    step_minutes: int = Field(default=15, ge=5, le=60)
    rate_multiplier: float = Field(default=1.0, gt=0, le=10)
    """Sensitivity setting: scale the baseline mean (e.g. 1.5 = 50 % above baseline)."""


class IntelligenceConfig(BaseModel):
    planning_horizon_minutes: int = Field(default=240, ge=90, le=720)
    """Horizon for planning analyses (fragility, genome, scarcity, last safe moment). The
    dashboard forecast stays at the brief's 90 minutes; the staffing planner uses 240."""
    time_machine_horizon_minutes: int = Field(default=90, ge=90, le=720)
    time_machine_step_minutes: int = Field(default=5, ge=1, le=30)
    default_rescue_minutes: int = Field(default=240, ge=120, le=720)
    """Offer length the simulator proposes when the optimizer has no recommendation."""
    extension_minutes: int = Field(default=120, ge=30, le=480)
    """Shift-extension what-if length (simulation only)."""
    lead: LeadTimePolicy = Field(default_factory=LeadTimePolicy)
    fragility: FragilityWeights = Field(default_factory=FragilityWeights)
    debt: DebtPolicy = Field(default_factory=DebtPolicy)
    stochastic: StochasticPolicy = Field(default_factory=StochasticPolicy)
    multi_factor_margin: float = Field(default=0.15, ge=0, le=1)
    """Genome: if the top two causes are within this share, the primary is MULTI_FACTOR."""
    policy_version: str = "neurogrid-v1"

    def signature(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]


@lru_cache(maxsize=8)
def _load(path: str | None, mtime: float | None) -> IntelligenceConfig:
    if not path:
        return IntelligenceConfig()
    return IntelligenceConfig.model_validate(json.loads(Path(path).read_text()))


def load_intelligence_config(path: Path | str | None) -> IntelligenceConfig:
    if path is None or not Path(path).exists():
        return _load(None, None)
    p = Path(path)
    return _load(str(p), p.stat().st_mtime)
