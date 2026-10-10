"""Workflow policy (Phase 5). Values tagged BRIEF come from the challenge handbook.

Documented semantics where the handbook is silent:

- **Week (ASSUMPTION).** "No more than 3 offers a week" is a *rolling* 7 × 24 h window
  ending at the simulation time, counting every offer that was sent to the physician
  (whatever its outcome). A calendar week would let a physician receive 6 offers across a
  week boundary in two days; rolling is stricter and needs no week-start convention.
- **Open offer (BRIEF + ASSUMPTION).** An offer is open while sent and unanswered. An
  accepted split shift that has not finished also blocks a new offer to that physician
  (they are already committed); it is counted under the same rule.
- **Binding acceptance (CHOICE).** An acceptance is binding the moment it is recorded,
  if the request still needs a physician *and* the forecast still shows a deficit at the
  offer's hospitals during its covered window (counting other accepted shifts). The
  clinical lead already approved the offer, so no second confirmation is needed.
- **Conflicting acceptances (CHOICE).** First binding acceptance wins (acceptances are
  serialized in one database transaction each). Once the need is met, every other pending
  offer for it is withdrawn immediately. An acceptance that arrives after the need was
  met is never dropped: it is recorded as ``redundant`` (or as a late reply to a withdrawn
  offer), the physician is released and told so, and the conflict and its resolution are
  audited. Redundant coverage is never activated.
- **Activation (CHOICE, deterministic simulation).** Expected online time =
  max(offer start, acceptance time) + the roster's minutes to come online. The physician
  may go online earlier from their phone once the shift has started; otherwise the system
  activates them exactly at the expected online time when the simulation clock reaches it.
"""

from __future__ import annotations

from datetime import timedelta

from pydantic import BaseModel


class WorkflowPolicy(BaseModel):
    offer_ttl_minutes: int = 10
    """BRIEF: an offer expires 10 minutes after it is sent (simulation clock)."""
    max_open_offers_per_physician: int = 1
    """BRIEF: one open offer per physician."""
    max_offers_per_physician_per_week: int = 3
    """BRIEF: no more than 3 offers a week (rolling 7 days, see module docstring)."""
    week_window_hours: int = 7 * 24
    max_backup_offers: int = 3
    """CHOICE: at most this many backup physicians per staffing request."""
    auto_activate_at_expected_online: bool = True
    """CHOICE: deterministic simulation of the physician coming online."""
    require_remaining_need_on_accept: bool = True
    """CHOICE: an acceptance is binding only if the forecast still shows a deficit."""
    policy_version: str = "phase5-v1"

    @property
    def offer_ttl(self) -> timedelta:
        return timedelta(minutes=self.offer_ttl_minutes)

    @property
    def week_window(self) -> timedelta:
        return timedelta(hours=self.week_window_hours)
