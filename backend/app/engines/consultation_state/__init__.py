"""Consultation state: rebuild each consult's lifecycle stage and time-in-stage.

Tracked independently of physician activity: one physician can have several open
consults in different stages at once, and a physician becoming busy never changes them.
See ``transitions.py`` for the documented rules.
"""

from app.engines.consultation_state.engine import ConsultationTracker
from app.engines.consultation_state.transitions import (
    STAGE_RANK,
    TARGET_STAGE,
    TransitionDecision,
    decide_transition,
)

__all__ = [
    "STAGE_RANK",
    "TARGET_STAGE",
    "ConsultationTracker",
    "TransitionDecision",
    "decide_transition",
]
