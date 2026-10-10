"""Rebuild every consult's lifecycle from events, independently of physician activity."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime

from app.engines.consultation_state.transitions import (
    ASSIGNMENT_LINKING_EVENTS,
    decide_transition,
)
from app.schemas.consultation import (
    AssignmentChange,
    ConsultationState,
    ConsultStage,
    ConsultStageTransition,
    StateAnomaly,
)
from app.schemas.event import KnownEventType as E
from app.schemas.event import StoredEvent
from app.schemas.hospital import Hospital


@dataclass
class _Consult:
    consult_id: str
    hospital_id: str | None = None
    consult_type: str | None = None
    priority: str | None = None
    stage: ConsultStage | None = None
    stage_entered_at: datetime | None = None
    provisional: bool = False
    received_at: datetime | None = None
    closed_at: datetime | None = None
    first_seen_at: datetime | None = None
    assigned_physician_id: str | None = None
    stage_history: list[ConsultStageTransition] = field(default_factory=list)
    assignment_history: list[AssignmentChange] = field(default_factory=list)
    routing_failures: int = 0
    last_routing_failure_at: datetime | None = None
    evidence: list[str] = field(default_factory=list)
    anomalies: list[StateAnomaly] = field(default_factory=list)

    def anomaly(self, code: str, message: str, event: StoredEvent) -> None:
        self.anomalies.append(
            StateAnomaly(
                code=code,
                message=message,
                event_id=event.event_id,
                consult_id=self.consult_id,
                physician_id=event.physician_id,
            )
        )

    def enter(self, stage: ConsultStage, event: StoredEvent, provisional: bool) -> None:
        self.stage = stage
        self.stage_entered_at = event.event_time
        self.provisional = provisional
        self.stage_history.append(
            ConsultStageTransition(
                stage=stage,
                entered_at=event.event_time,
                event_id=event.event_id,
                event_type=event.event_type,
                provisional=provisional,
            )
        )
        if stage is ConsultStage.SIGNED_OFF:
            self.closed_at = event.event_time


class ConsultationTracker:
    """Apply events in replay order, then ``finalize`` at an ``as_of`` time."""

    def __init__(self) -> None:
        self._consults: dict[str, _Consult] = {}

    def apply(self, event: StoredEvent) -> None:
        if not event.consult_id:
            return
        consult = self._consults.get(event.consult_id)
        if consult is None:
            consult = _Consult(consult_id=event.consult_id, first_seen_at=event.event_time)
            self._consults[event.consult_id] = consult
            if event.event_type != E.CONSULT_RECEIVED:
                consult.anomaly(
                    "missing_consult_received",
                    f"first event for this consult is {event.event_type}, not consult_received",
                    event,
                )
        consult.evidence.append(event.event_id)

        self._apply_metadata(consult, event)
        self._apply_assignment(consult, event)
        if event.event_type == E.ROUTING_ATTEMPT_FAILED:
            consult.routing_failures += 1
            consult.last_routing_failure_at = event.event_time

        decision = decide_transition(consult.stage, consult.provisional, event.event_type)
        if decision.target is not None:
            consult.enter(decision.target, event, decision.provisional)
        elif event.event_type == E.CONSULT_RECEIVED and consult.stage is not None:
            if consult.received_at is not None and consult.received_at < event.event_time:
                # The hospital called again about the same consult: same patient, counted
                # once, and the clock keeps running from the first request (brief).
                consult.anomaly(
                    "repeat_request",
                    "hospital requested this consult again; same patient, counted once, "
                    "waiting time still runs from the first request",
                    event,
                )
            else:
                consult.anomaly(
                    "received_out_of_sequence",
                    "consult_received is timestamped after other events for this consult",
                    event,
                )
        elif decision.anomaly_code:
            consult.anomaly(decision.anomaly_code, decision.note or "", event)

    @staticmethod
    def _apply_metadata(consult: _Consult, event: StoredEvent) -> None:
        if event.hospital_id:
            if consult.hospital_id is None:
                consult.hospital_id = event.hospital_id
            elif consult.hospital_id != event.hospital_id:
                consult.anomaly(
                    "hospital_mismatch",
                    f"event names hospital {event.hospital_id}, consult is at "
                    f"{consult.hospital_id}; first value kept",
                    event,
                )
        if event.event_type == E.CONSULT_RECEIVED and consult.received_at is None:
            consult.received_at = event.event_time
        if consult.consult_type is None and event.payload.get("consult_type"):
            consult.consult_type = str(event.payload["consult_type"])
        if consult.priority is None and event.payload.get("priority"):
            consult.priority = str(event.payload["priority"])

    @staticmethod
    def _apply_assignment(consult: _Consult, event: StoredEvent) -> None:
        physician = event.physician_id
        if not physician:
            return
        if event.event_type == E.PHYSICIAN_ASSIGNED:
            if physician != consult.assigned_physician_id:
                consult.assigned_physician_id = physician
                consult.assignment_history.append(
                    AssignmentChange(
                        physician_id=physician, at=event.event_time, event_id=event.event_id
                    )
                )
        elif event.event_type in ASSIGNMENT_LINKING_EVENTS:
            if consult.assigned_physician_id is None:
                consult.assigned_physician_id = physician
                consult.assignment_history.append(
                    AssignmentChange(
                        physician_id=physician,
                        at=event.event_time,
                        event_id=event.event_id,
                        inferred=True,
                    )
                )
                consult.anomaly(
                    "assignment_inferred",
                    f"no physician_assigned event; linked to {physician} by {event.event_type}",
                    event,
                )
            elif physician != consult.assigned_physician_id:
                consult.anomaly(
                    "unassigned_physician_activity",
                    f"{event.event_type} by {physician}, but the consult is assigned to "
                    f"{consult.assigned_physician_id}",
                    event,
                )

    def finalize(
        self, as_of: datetime, hospitals: Mapping[str, Hospital] | None = None
    ) -> list[ConsultationState]:
        hospitals = hospitals or {}
        states: list[ConsultationState] = []
        for consult in self._consults.values():
            stage = consult.stage
            entered = consult.stage_entered_at
            anomalies = list(consult.anomalies)
            if stage is None or entered is None:
                # Only non-lifecycle events seen (e.g. ringing, routing failure).
                stage = ConsultStage.RECEIVED
                entered = consult.first_seen_at or as_of
                anomalies.append(
                    StateAnomaly(
                        code="stage_unknown",
                        message="no lifecycle event seen; shown as Received",
                        consult_id=consult.consult_id,
                    )
                )
            hospital = hospitals.get(consult.hospital_id) if consult.hospital_id else None
            states.append(
                ConsultationState(
                    consult_id=consult.consult_id,
                    hospital_id=consult.hospital_id,
                    hospital_name=hospital.name if hospital else None,
                    hospital_timezone=hospital.timezone if hospital else None,
                    consult_type=consult.consult_type,
                    priority=consult.priority,
                    stage=stage,
                    is_open=stage is not ConsultStage.SIGNED_OFF,
                    assigned_physician_id=consult.assigned_physician_id,
                    received_at=consult.received_at,
                    stage_entered_at=entered,
                    closed_at=consult.closed_at,
                    as_of=as_of,
                    seconds_in_stage=max(0, int((as_of - entered).total_seconds())),
                    seconds_since_received=(
                        max(0, int((as_of - consult.received_at).total_seconds()))
                        if consult.received_at
                        else None
                    ),
                    stage_history=consult.stage_history,
                    assignment_history=consult.assignment_history,
                    routing_failures=consult.routing_failures,
                    last_routing_failure_at=consult.last_routing_failure_at,
                    evidence_event_ids=consult.evidence,
                    anomalies=anomalies,
                )
            )
        states.sort(key=lambda c: (c.received_at or c.stage_entered_at, c.consult_id))
        return states
