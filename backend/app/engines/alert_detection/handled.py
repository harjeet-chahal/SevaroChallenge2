"""Handled alerts: problems someone already acted on, kept out of the ranked queue (pure).

Alerts come from the live data and stay while the condition does: a reassigned consult can
still be waiting for its first contact, measured from when it entered the stage. Once every
intervention about an alert's problem has finished and at least one of them completed after
the condition began, the alert is *handled*. Handled alerts are still returned, with the
intervention that handled them, but they rank below every open alert; the open alerts are
re-numbered from 1 and the severity and rule counts describe the open queue only.

A condition that begins again after the completion (a new ``condition_since``) is a new
occurrence and is open again.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.engines.alert_detection.rank import SEVERITY_RANK
from app.schemas.alert import Alert, AlertList, RuleCode
from app.schemas.intervention import TERMINAL_STATUSES, InterventionStatus

GAP_RULES = frozenset({RuleCode.COVERAGE_GAP_NOW.value, RuleCode.COVERAGE_GAP_PROJECTED.value})


def same_problem(a: str, b: str) -> bool:
    """Alert ids that name the same problem: identical, or a hospital's projected and
    current coverage-gap alerts (the id changes when the projected gap begins)."""
    if a == b:
        return True
    rule_a, _, entity_a = a.partition(":")
    rule_b, _, entity_b = b.partition(":")
    return rule_a in GAP_RULES and rule_b in GAP_RULES and entity_a == entity_b


@dataclass(frozen=True)
class InterventionRef:
    """What triage needs to know about an intervention; no patient or physician details."""

    id: str
    status: InterventionStatus
    alert_id: str | None
    consult_id: str | None
    proposed_at: datetime
    """Simulation time of the proposal."""
    updated_at: datetime
    """Simulation time of the latest transition (for a completed one, its completion)."""


def linked(alert: Alert, interventions: Sequence[InterventionRef]) -> list[InterventionRef]:
    """Interventions about this alert's problem: raised from it (or the same coverage gap),
    or about the same consult (e.g. its routing-failure alert)."""
    return [
        i
        for i in interventions
        if (i.alert_id is not None and same_problem(i.alert_id, alert.alert_id))
        or (alert.consult_id is not None and i.consult_id == alert.consult_id)
    ]


def handled_by(alert: Alert, interventions: Sequence[InterventionRef]) -> str | None:
    """The intervention that handled the alert, or None while it still needs someone.

    Judged at the alert's ``as_of``: interventions proposed later do not exist yet, and one
    that finished later was still in flight.
    """
    known = [i for i in linked(alert, interventions) if i.proposed_at <= alert.as_of]
    if not known:
        return None
    if any(i.status not in TERMINAL_STATUSES or i.updated_at > alert.as_of for i in known):
        return None
    completed = [
        i
        for i in known
        if i.status is InterventionStatus.COMPLETED
        and (alert.condition_since is None or i.updated_at >= alert.condition_since)
    ]
    if not completed:
        return None
    return max(completed, key=lambda i: (i.updated_at, i.id)).id


def apply_handled(alerts: AlertList, interventions: Sequence[InterventionRef]) -> AlertList:
    """Mark handled alerts, move them below the open ones and count the open queue only.
    Open alerts keep their relative order; with nothing handled the list is unchanged."""
    marks = {a.alert_id: handled_by(a, interventions) for a in alerts.alerts}
    open_alerts = [a for a in alerts.alerts if marks[a.alert_id] is None]
    done = [a for a in alerts.alerts if marks[a.alert_id] is not None]
    if not done:
        return alerts
    ordered = [
        a.model_copy(update={"priority": position, "handled_by": marks[a.alert_id]})
        for position, a in enumerate(open_alerts + done, start=1)
    ]
    by_severity = Counter(a.severity.value for a in open_alerts)
    by_rule = Counter(a.rule_code.value for a in open_alerts)
    return alerts.model_copy(
        update={
            "alerts": ordered,
            "open_total": len(open_alerts),
            "handled_total": len(done),
            "counts_by_severity": {s.value: by_severity.get(s.value, 0) for s in SEVERITY_RANK},
            "counts_by_rule": dict(sorted(by_rule.items())),
        }
    )
