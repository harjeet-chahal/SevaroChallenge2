"""Every threshold, severity and policy used by the Phase 3 engines, in one place.

Values marked ``source="challenge_brief"`` are copied from the brief:
- Operational Standards (Synthetic) table — stage time standards and open notes near shift end
- Coverage and Split-Shift Eligibility — coverage gap and demand-spike rule (+1 requirement)
- Availability rules — camera-without-Synapse is "flagged"; offline agent risk is "surfaced"

Everything else is a documented ``assumption``: the brief does not specify it. All values
can be overridden with a JSON file (``RISK_RULES_FILE``) without code changes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.alert import RecommendedAction, RuleCode, RuleSource
from app.schemas.common import Severity
from app.schemas.consultation import ConsultStage as S

ConsultCategory = str
"""Normalized consult category, e.g. 'stroke' or 'general_neuro'. 'all' matches any."""


class StageStandard(BaseModel):
    code: RuleCode
    name: str
    stages: list[S]
    applies_to: list[ConsultCategory]
    clock: Literal["stage_entry", "end_of_video_or_call"]
    warning_minutes: float = Field(gt=0)
    critical_minutes: float = Field(gt=0)
    requires_unassigned: bool = False
    action_warning: RecommendedAction
    action_critical: RecommendedAction
    source: RuleSource = "challenge_brief"
    reference: str = "Brief, Operational Standards (Synthetic) table"


_BRIEF_TABLE = "Brief, Operational Standards (Synthetic) table"


def _standards() -> list[StageStandard]:
    A = RecommendedAction
    return [
        StageStandard(
            code=RuleCode.STAGE_TRIAGED_UNASSIGNED,
            name="Triaged, not yet assigned",
            stages=[S.TRIAGED],
            applies_to=["all"],
            clock="stage_entry",
            warning_minutes=5,
            critical_minutes=10,
            requires_unassigned=True,
            action_warning=A.REASSIGN_CONSULT,
            action_critical=A.ESCALATE,
            reference=f"{_BRIEF_TABLE}: 'Triaged, not yet assigned' — All — 5 / 10 min",
        ),
        StageStandard(
            code=RuleCode.STAGE_ASSIGNED_NOT_CONTACTED,
            name="Assigned, physician not yet contacted",
            stages=[S.ASSIGNED],
            applies_to=["stroke"],
            clock="stage_entry",
            warning_minutes=3,
            critical_minutes=8,
            action_warning=A.CONTACT_PHYSICIAN,
            action_critical=A.REASSIGN_CONSULT,
            reference=(
                f"{_BRIEF_TABLE}: 'Assigned, physician not yet contacted' — Stroke — 3 / 8 min"
            ),
        ),
        StageStandard(
            code=RuleCode.STAGE_IMAGING_PENDING,
            name="CT/CTA or Imaging Pending",
            stages=[S.IMAGING_PENDING],
            applies_to=["stroke"],
            clock="stage_entry",
            warning_minutes=12,
            critical_minutes=20,
            action_warning=A.MONITOR,
            action_critical=A.ESCALATE,
            reference=f"{_BRIEF_TABLE}: 'CT/CTA or Imaging Pending' — Stroke — 12 / 20 min",
        ),
        StageStandard(
            code=RuleCode.STAGE_IMAGING_REVIEW,
            name="Imaging Review (imaging back, video not started)",
            stages=[S.IMAGING_REVIEW],
            applies_to=["stroke"],
            clock="stage_entry",
            warning_minutes=6,
            critical_minutes=12,
            action_warning=A.CONTACT_PHYSICIAN,
            action_critical=A.ESCALATE,
            reference=f"{_BRIEF_TABLE}: 'Imaging Review' — Stroke — 6 / 12 min",
        ),
        StageStandard(
            code=RuleCode.NOTE_OVERDUE,
            name="Note Pending + Documentation, from end of video or call (Stroke)",
            stages=[S.NOTE_PENDING, S.DOCUMENTATION],
            applies_to=["stroke"],
            clock="end_of_video_or_call",
            warning_minutes=30,
            critical_minutes=45,
            action_warning=A.CONTACT_PHYSICIAN,
            action_critical=A.CONTACT_PHYSICIAN,
            reference=f"{_BRIEF_TABLE}: 'Note Pending + Documentation' — Stroke — 30 / 45 min",
        ),
        StageStandard(
            code=RuleCode.NOTE_OVERDUE,
            name="Note Pending + Documentation, from end of video or call (General Neuro)",
            stages=[S.NOTE_PENDING, S.DOCUMENTATION],
            applies_to=["general_neuro"],
            clock="end_of_video_or_call",
            warning_minutes=45,
            critical_minutes=90,
            action_warning=A.CONTACT_PHYSICIAN,
            action_critical=A.CONTACT_PHYSICIAN,
            reference=(
                f"{_BRIEF_TABLE}: 'Note Pending + Documentation' — General Neuro — 45 / 90 min"
            ),
        ),
    ]


class OpenNotesRule(BaseModel):
    window_minutes: float = 60
    warning_min_open_notes: int = 1
    """Brief: Warning = 'Any'."""
    critical_min_open_notes: int = 2
    """Brief: Critical = '2 or more'."""
    note_stages: list[S] = Field(default_factory=lambda: [S.NOTE_PENDING, S.DOCUMENTATION])
    reference: str = (
        f"{_BRIEF_TABLE}: 'Open notes within 60 min of the physician's shift end' — All — Any / 2 "
        "or more"
    )


class AssignedUnavailableRule(BaseModel):
    """Assumption: the brief lists this situation but gives no severity or threshold."""

    critical_categories: list[ConsultCategory] = Field(default_factory=lambda: ["stroke"])
    critical_stages: list[S] = Field(
        default_factory=lambda: [
            S.ASSIGNED,
            S.PROVIDER_CONTACTED,
            S.IMAGING_PENDING,
            S.IMAGING_REVIEW,
            S.VIDEO_IN_PROGRESS,
        ]
    )
    default_severity: Severity = Severity.WARNING
    unavailable_states: list[str] = Field(default_factory=lambda: ["unavailable", "off_shift"])


class SeverityRule(BaseModel):
    severity: Severity
    reference: str


class DemandRule(BaseModel):
    window_minutes: int = 60
    requirement_increase: int = 1
    alert_severity: Severity = Severity.WARNING
    """Assumption: the brief defines the spike, not an alert severity for it."""
    reference: str = (
        "Brief, Coverage gap: 'A demand spike (trailing 60-minute consults above the "
        "hospital's p90 baseline for that hour) raises the requirement by one.'"
    )


class CoverageRule(BaseModel):
    horizon_minutes: int = 90
    chart_step_minutes: int = 5
    busy_counts_as_available: bool = True
    """Assumption: 'available' in the coverage rule means on duty and not unavailable; a
    physician on a call still counts (they free up; routing handles the moment)."""
    unavailable_persists: bool = True
    """Assumption: a Temporarily Unavailable physician stays excluded for the horizon,
    because no return time is known (persistence, not fabrication)."""
    current_gap_severity: Severity = Severity.CRITICAL
    projected_gap_severity: Severity = Severity.WARNING
    reference: str = (
        "Brief, Coverage gap: 'Each hospital has a minimum number of available, credentialed "
        "physicians per time block ... A gap exists when that number is not met, either now "
        "or at a projected time.'"
    )


class RiskConfig(BaseModel):
    consult_categories: dict[ConsultCategory, list[str]] = Field(
        default_factory=lambda: {
            "stroke": ["stroke"],
            "general_neuro": ["general_neuro", "general_neurology"],
        }
    )
    """Category -> accepted normalized consult_type labels. Unknown types match only 'all'."""
    stage_standards: list[StageStandard] = Field(default_factory=_standards)
    open_notes: OpenNotesRule = Field(default_factory=OpenNotesRule)
    assigned_unavailable: AssignedUnavailableRule = Field(default_factory=AssignedUnavailableRule)
    routing_failure: SeverityRule = Field(
        default_factory=lambda: SeverityRule(
            severity=Severity.WARNING,
            reference="Assumption: the brief defines routing_attempt_failed (no eligible "
            "physician; retries every 5 min) but no alert threshold. Any failure on a still "
            "unassigned consult is reported.",
        )
    )
    external_video: SeverityRule = Field(
        default_factory=lambda: SeverityRule(
            severity=Severity.INFO,
            reference="Brief, availability rules: camera active with no Synapse session and not "
            "In Meeting — 'Treat as busy and flag it.' Severity is an assumption.",
        )
    )
    agent_offline: SeverityRule = Field(
        default_factory=lambda: SeverityRule(
            severity=Severity.WARNING,
            reference="Brief, availability rules: agent offline — 'routing assumes the physician "
            "is available, but this is unverified. Surface the risk.' Severity is an assumption.",
        )
    )
    demand: DemandRule = Field(default_factory=DemandRule)
    coverage: CoverageRule = Field(default_factory=CoverageRule)

    def signature(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_risk_config(override_file: Path | None = None) -> RiskConfig:
    if override_file is None:
        return RiskConfig()
    override = json.loads(override_file.read_text(encoding="utf-8"))
    return RiskConfig.model_validate(_deep_merge(RiskConfig().model_dump(mode="json"), override))
