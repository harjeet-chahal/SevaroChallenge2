"""Physician state: derive each physician's availability from reconciled system signals.

Self-reported status, telephony, video, camera and desktop-agent signals can disagree.
Raw signals are kept separately from the derived decision, which always carries the
rule that decided it and an explanation. See ``availability.py`` for the precedence.
"""

from app.engines.physician_state.availability import (
    AvailabilityDecision,
    AvailabilityInputs,
    decide_availability,
)
from app.engines.physician_state.engine import (
    PhysicianSignals,
    PhysicianStateTracker,
    build_physician_state,
    build_physician_states,
)

__all__ = [
    "AvailabilityDecision",
    "AvailabilityInputs",
    "PhysicianSignals",
    "PhysicianStateTracker",
    "build_physician_state",
    "build_physician_states",
    "decide_availability",
]
