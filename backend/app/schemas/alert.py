"""Operational alerts: what needs attention, why, how urgently, and what kind of action fits.

Alerts are recomputed from state on every request. ``alert_id`` is stable for the same
ongoing issue (rule + entity), so severity can change without the alert becoming a new,
unrelated item.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, Field

from app.schemas.common import ApiModel, EntityId, Severity


class RuleCode(StrEnum):
    STAGE_TRIAGED_UNASSIGNED = "STAGE_TRIAGED_UNASSIGNED"
    STAGE_ASSIGNED_NOT_CONTACTED = "STAGE_ASSIGNED_NOT_CONTACTED"
    STAGE_IMAGING_PENDING = "STAGE_IMAGING_PENDING"
    STAGE_IMAGING_REVIEW = "STAGE_IMAGING_REVIEW"
    NOTE_OVERDUE = "NOTE_OVERDUE"
    OPEN_NOTES_NEAR_SHIFT_END = "OPEN_NOTES_NEAR_SHIFT_END"
    ASSIGNED_PHYSICIAN_UNAVAILABLE = "ASSIGNED_PHYSICIAN_UNAVAILABLE"
    ROUTING_FAILURE = "ROUTING_FAILURE"
    SIGNAL_EXTERNAL_VIDEO = "SIGNAL_EXTERNAL_VIDEO"
    SIGNAL_AGENT_OFFLINE = "SIGNAL_AGENT_OFFLINE"
    DEMAND_SPIKE = "DEMAND_SPIKE"
    COVERAGE_GAP_NOW = "COVERAGE_GAP_NOW"
    COVERAGE_GAP_PROJECTED = "COVERAGE_GAP_PROJECTED"


class AlertCategory(StrEnum):
    CONSULT_DELAY = "consult_delay"
    PHYSICIAN_WORKFLOW = "physician_workflow"
    PHYSICIAN_SIGNAL = "physician_signal"
    DEMAND = "demand"
    COVERAGE = "coverage"


class RecommendedAction(StrEnum):
    """Intervention *category* only. Nothing is executed in this phase."""

    REASSIGN_CONSULT = "reassign_consult"
    ESCALATE = "escalate"
    CONTACT_PHYSICIAN = "contact_physician"
    PROPOSE_SPLIT_SHIFT = "propose_split_shift"
    MONITOR = "monitor"


RuleSource = Literal["challenge_brief", "assumption"]


class AlertEvidence(ApiModel):
    """A single fact that supports an alert."""

    label: str
    value: str
    at: AwareDatetime | None = None
    source_event_ids: list[EntityId] = Field(default_factory=list)


class AlertRank(ApiModel):
    """Lexicographic ranking key, most significant first. Lower sorts earlier."""

    severity_rank: int
    """critical=0, warning=1, info=2 — hard precedence."""
    category_rank: int
    """Clinical-urgency class; stroke consult delays outrank everything else at equal severity."""
    repeat_requests: int = 0
    """Times the hospital called again about this consult (same patient): moves it up within
    its severity and category."""
    urgency: float
    """Higher is more urgent: overrun ratio, imminence, or deficit size depending on the rule."""
    coverage_risk: int
    """2 = hospital has a coverage gap now, 1 = projected within the horizon, 0 = none."""
    affected: int
    """Number of consults / hospitals the issue touches."""


class Alert(ApiModel):
    alert_id: str
    rule_code: RuleCode
    rule_name: str
    rule_source: RuleSource
    rule_reference: str
    """Where the rule comes from (e.g. the brief's Operational Standards table) or why it is
    an assumption."""
    category: AlertCategory
    severity: Severity
    severity_reason: str
    priority: int = Field(ge=1)
    """1 = most urgent. Deterministic from ``rank``."""
    priority_reasons: list[str] = Field(default_factory=list)
    rank: AlertRank
    title: str
    summary: str
    recommended_action_type: RecommendedAction
    recommended_action_reason: str
    hospital_id: EntityId | None = None
    hospital_name: str | None = None
    hospital_timezone: str | None = None
    consult_id: EntityId | None = None
    physician_id: EntityId | None = None
    physician_name: str | None = None
    as_of: AwareDatetime
    condition_since: AwareDatetime | None = None
    """When the condition began, where it can be derived from state (e.g. stage entry)."""
    elapsed_seconds: int | None = None
    warning_after_seconds: int | None = None
    critical_after_seconds: int | None = None
    impact_at: AwareDatetime | None = None
    """For projected issues: when the problem is expected to start."""
    minutes_to_impact: float | None = None
    evidence: list[AlertEvidence] = Field(default_factory=list)
    event_ids: list[EntityId] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    handled_by: EntityId | None = None
    """The completed intervention that handled this problem. Handled alerts stay in the list
    (the condition is still in the data) but rank below every open alert."""


class AlertList(ApiModel):
    as_of: AwareDatetime
    data_version: int
    total: int
    """Every active alert, open and handled."""
    open_total: int
    """Alerts still needing someone; ``priority`` 1..open_total are these, in order."""
    handled_total: int = 0
    counts_by_severity: dict[str, int]
    """Open alerts only, by severity."""
    counts_by_rule: dict[str, int]
    """Open alerts only, by rule."""
    alerts: list[Alert]
    notes: list[str] = Field(default_factory=list)
    """Rules that could not be evaluated (e.g. unknown consult type), stated plainly."""
