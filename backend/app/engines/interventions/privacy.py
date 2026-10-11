"""What an off-shift physician may be told (pure).

The offer text is generated from operational facts only: hospital names, the time the
shortfall starts and the hospital's time zone. It never contains consult IDs, consult
types, patient details or the coordinator's free-text rationale. ``find_disallowed``
is a defensive check run on every physician-facing payload.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from app.engines.timeline import fmt_local


def offer_reason(
    hospital_names: list[str],
    shortfall_at: datetime | None,
    tz: str,
    surge: bool,
    volunteered: bool = False,
) -> str:
    where = ", ".join(hospital_names) if hospital_names else "your credentialed hospitals"
    when = f" from {fmt_local(shortfall_at, tz)}" if shortfall_at is not None else ""
    cause = " Demand there is above its normal level." if surge else ""
    shared = " It falls within the availability you shared." if volunteered else ""
    return (
        f"Short-term coverage gap forecast at {where}{when}: fewer credentialed "
        f"neurologists available than required.{cause} You are opted in, credentialed there "
        f"and rested.{shared}"
    )[:500]


def find_disallowed(text_values: Iterable[str], forbidden: Iterable[str]) -> list[str]:
    """Forbidden tokens (e.g. every consult ID in the dataset) that appear in the payload."""
    blob = "\n".join(text_values).lower()
    return sorted({t for t in forbidden if t and t.lower() in blob})
