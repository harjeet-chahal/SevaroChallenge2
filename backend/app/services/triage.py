"""Alerts as the coordinator's queue: the analysis alerts with handled problems ranked last.

The analysis itself stays pure and cached on the data version; this reads the active
dataset's interventions (which change with the workflow version) and applies
:func:`app.engines.alert_detection.handled.apply_handled` on every request.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.engines.alert_detection.handled import InterventionRef, apply_handled
from app.repositories import SystemRepository
from app.repositories.workflow import WorkflowRepository
from app.schemas.alert import AlertList
from app.schemas.intervention import InterventionStatus
from app.schemas.metrics import OperationalMetrics


class AlertTriage:
    def __init__(self, session: Session) -> None:
        self.system = SystemRepository(session)
        self.workflow = WorkflowRepository(session)

    def interventions(self) -> list[InterventionRef]:
        state = self.system.get_simulation_state()
        import_id = state.active_import_id if state else None
        if not import_id:
            return []
        return [
            InterventionRef(
                id=r.id,
                status=InterventionStatus(r.status),
                alert_id=r.alert_id,
                consult_id=r.consult_id,
                proposed_at=r.proposed_at,
                updated_at=r.updated_at,
            )
            for r in self.workflow.list_interventions(import_id=import_id)
        ]

    def alerts(self, alerts: AlertList) -> AlertList:
        return apply_handled(alerts, self.interventions())

    def metrics(self, metrics: OperationalMetrics, alerts: AlertList) -> OperationalMetrics:
        """Alert counts in the metrics describe the same open queue as the alert list."""
        queue = self.alerts(alerts)
        return metrics.model_copy(
            update={
                "alerts_by_severity": queue.counts_by_severity,
                "alerts_by_rule": queue.counts_by_rule,
            }
        )
