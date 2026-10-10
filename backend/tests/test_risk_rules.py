"""Alert rules at their exact documented thresholds, plus ranking and identity.

Thresholds come from the brief's Operational Standards table; expected values below are
written by hand from that table, not computed by the engine.
"""

from __future__ import annotations

import random
from datetime import timedelta

import pytest

from app.engines.analysis import analyze
from app.schemas.alert import RuleCode
from tests.analysis_helpers import Scenario, alerts_by_id, utc

T0 = utc(2031, 2, 3, 15, 0)  # 09:00 CST at an America/Chicago hospital
SEC = timedelta(seconds=1)


def m(minutes: float):
    return T0 + timedelta(minutes=minutes)


def base(consult_type: str = "Stroke") -> Scenario:
    s = Scenario().hospital("H1").on_shift("P1", ["H1"], m(-300), m(600))
    s.requirement("H1", "00:00", "00:00", 1)
    s.event("consult_received", m(-2), consult_id="C1", hospital_id="H1", consult_type=consult_type)
    return s


def severity(analysis, rule: RuleCode, entity: str = "consult:C1"):
    alert = alerts_by_id(analysis).get(f"{rule.value}:{entity}")
    return alert.severity.value if alert else None


# 1 & 2. Exact thresholds: fires AT the threshold, not one second before ------------------


def test_triaged_unassigned_thresholds_exact():
    s = base().event("consult_triaged", m(0), consult_id="C1", hospital_id="H1")
    rule = RuleCode.STAGE_TRIAGED_UNASSIGNED

    assert severity(s.analyze(m(5) - SEC), rule) is None
    assert severity(s.analyze(m(5)), rule) == "warning"
    assert severity(s.analyze(m(10) - SEC), rule) == "warning"
    assert severity(s.analyze(m(10)), rule) == "critical"


@pytest.mark.parametrize(
    ("consult_type", "setup", "rule", "warning", "critical"),
    [
        ("Stroke", ["assigned"], RuleCode.STAGE_ASSIGNED_NOT_CONTACTED, 3, 8),
        (
            "Stroke",
            ["assigned", "call", "imaging_requested"],
            RuleCode.STAGE_IMAGING_PENDING,
            12,
            20,
        ),
        (
            "Stroke",
            ["assigned", "call", "imaging_requested", "imaging_returned"],
            RuleCode.STAGE_IMAGING_REVIEW,
            6,
            12,
        ),
        ("Stroke", ["assigned", "call", "call_end"], RuleCode.NOTE_OVERDUE, 30, 45),
        ("General Neuro", ["assigned", "call", "call_end"], RuleCode.NOTE_OVERDUE, 45, 90),
    ],
)
def test_stage_standards_at_documented_thresholds(consult_type, setup, rule, warning, critical):
    s = base(consult_type).event("consult_triaged", m(-1.5), consult_id="C1", hospital_id="H1")
    steps = {
        "assigned": ("physician_assigned", {"physician_id": "P1"}),
        "call": ("incoming_call_started", {"physician_id": "P1"}),
        "imaging_requested": ("imaging_requested", {}),
        "imaging_returned": ("imaging_returned", {}),
        "call_end": ("incoming_call_ended", {"physician_id": "P1"}),
    }
    # Earlier steps happen before T0; the last one (the stage under test) happens at T0.
    for i, name in enumerate(setup):
        event_type, extra = steps[name]
        when = m(0) if i == len(setup) - 1 else m(-1 + i * 0.1)
        s.event(event_type, when, consult_id="C1", hospital_id="H1", **extra)

    assert severity(s.analyze(m(warning) - SEC), rule) is None
    assert severity(s.analyze(m(warning)), rule) == "warning"
    assert severity(s.analyze(m(critical) - SEC), rule) == "warning"
    assert severity(s.analyze(m(critical)), rule) == "critical"


def test_stroke_only_standards_do_not_apply_to_general_neuro():
    s = base("General Neuro").event("consult_triaged", m(-1), consult_id="C1", hospital_id="H1")
    s.event("physician_assigned", m(0), consult_id="C1", hospital_id="H1", physician_id="P1")

    assert severity(s.analyze(m(30)), RuleCode.STAGE_ASSIGNED_NOT_CONTACTED) is None


def test_note_clock_runs_from_end_of_call_not_from_note_start():
    s = base("General Neuro").event("consult_triaged", m(-1.8), consult_id="C1", hospital_id="H1")
    s.event("physician_assigned", m(-1.6), consult_id="C1", hospital_id="H1", physician_id="P1")
    s.event("incoming_call_started", m(-1.4), consult_id="C1", hospital_id="H1", physician_id="P1")
    s.event("incoming_call_ended", m(0), consult_id="C1", hospital_id="H1", physician_id="P1")
    s.event("note_started", m(20), consult_id="C1", hospital_id="H1", physician_id="P1")

    alert = alerts_by_id(s.analyze(m(45)))[f"{RuleCode.NOTE_OVERDUE.value}:consult:C1"]

    assert alert.severity.value == "warning"  # 45 min since the call ended, not 25
    assert alert.elapsed_seconds == 45 * 60


def test_unknown_consult_type_is_reported_not_guessed():
    s = base("").event("consult_triaged", m(-1), consult_id="C1", hospital_id="H1")
    s.event("physician_assigned", m(0), consult_id="C1", hospital_id="H1", physician_id="P1")

    analysis = s.analyze(m(30))

    assert severity(analysis, RuleCode.STAGE_ASSIGNED_NOT_CONTACTED) is None
    assert any("Consult type unknown for C1" in n for n in analysis.alerts.notes)


# Open notes within 60 min of shift end (brief: warning 'Any', critical '2 or more') ------


def _notes_scenario(n_notes: int, shift_end_minutes: float) -> Scenario:
    s = Scenario().hospital("H1").on_shift("P1", ["H1"], m(-600), m(shift_end_minutes))
    s.requirement("H1", "00:00", "00:00", 1)
    for i in range(n_notes):
        cid = f"N{i}"
        s.event(
            "consult_received", m(-30 + i), consult_id=cid, hospital_id="H1", consult_type="Stroke"
        )
        s.event(
            "physician_assigned", m(-29 + i), consult_id=cid, hospital_id="H1", physician_id="P1"
        )
        s.event(
            "incoming_call_started", m(-28 + i), consult_id=cid, hospital_id="H1", physician_id="P1"
        )
        s.event(
            "incoming_call_ended", m(-20 + i), consult_id=cid, hospital_id="H1", physician_id="P1"
        )
    return s


@pytest.mark.parametrize(
    ("notes", "end", "expected"),
    [
        (1, 60, "warning"),  # exactly 60 min left: inside the window
        (2, 60, "critical"),
        (3, 10, "critical"),
        (2, 61, None),  # 61 min left: outside the window
        (0, 30, None),
    ],
)
def test_open_notes_near_shift_end(notes, end, expected):
    analysis = _notes_scenario(notes, end).analyze(m(0))

    assert severity(analysis, RuleCode.OPEN_NOTES_NEAR_SHIFT_END, "physician:P1") == expected


# Assigned physician unavailable, routing failures, signals ------------------------------


def test_assigned_physician_temporarily_unavailable():
    s = base().event("consult_triaged", m(-1.5), consult_id="C1", hospital_id="H1")
    s.event("physician_assigned", m(-1), consult_id="C1", hospital_id="H1", physician_id="P1")
    s.event("physician_status_changed", m(0), physician_id="P1", status="Temporarily Unavailable")

    alert = alerts_by_id(s.analyze(m(1)))[
        f"{RuleCode.ASSIGNED_PHYSICIAN_UNAVAILABLE.value}:consult:C1"
    ]

    assert alert.severity.value == "critical"  # stroke, before documentation (assumption)
    assert alert.rule_source == "assumption"
    assert alert.recommended_action_type.value == "reassign_consult"
    assert alert.condition_since == m(0)


def test_routing_failure_alert_lists_the_credentialed_pool():
    s = base().event("consult_triaged", m(0), consult_id="C1", hospital_id="H1")
    s.event("video_started", m(0.5), consult_id="X", hospital_id="H1", physician_id="P1")
    s.event("routing_attempt_failed", m(1), consult_id="C1", hospital_id="H1")
    s.event("routing_attempt_failed", m(6), consult_id="C1", hospital_id="H1")

    alert = alerts_by_id(s.analyze(m(7)))[f"{RuleCode.ROUTING_FAILURE.value}:consult:C1"]

    assert "2 failed attempts" in alert.summary
    assert "Dr P1 (busy, video_consult)" in alert.summary


def test_signal_alerts_for_camera_and_offline_agent():
    s = Scenario().hospital("H1").on_shift("P1", ["H1"], m(-60), m(600))
    s.on_shift("P2", ["H1"], m(-60), m(600)).requirement("H1", "00:00", "00:00", 1)
    s.event("physician_status_changed", m(-5), physician_id="P1", status="Available")
    s.event("camera_active", m(-4), physician_id="P1")
    s.event("agent_heartbeat_lost", m(-3), physician_id="P2")

    found = alerts_by_id(s.analyze(m(0)))

    assert found[f"{RuleCode.SIGNAL_EXTERNAL_VIDEO.value}:physician:P1"].severity.value == "info"
    assert found[f"{RuleCode.SIGNAL_AGENT_OFFLINE.value}:physician:P2"].severity.value == "warning"


# Ranking --------------------------------------------------------------------------------


def _ranking_scenario() -> Scenario:
    s = Scenario().hospital("H1").hospital("H2").on_shift("P1", ["H1"], m(-300), m(600))
    s.requirement("H1", "00:00", "00:00", 1).requirement("H2", "00:00", "00:00", 1)
    # Stroke unassigned 12 min (critical), GN unassigned 15 min (critical, but not stroke),
    # stroke unassigned 6 min (warning). H2 has nobody credentialed: coverage gap now.
    for cid, ctype, triaged in (
        ("S1", "Stroke", -12),
        ("G1", "General Neuro", -15),
        ("S2", "Stroke", -6),
    ):
        s.event(
            "consult_received", m(triaged - 1), consult_id=cid, hospital_id="H1", consult_type=ctype
        )
        s.event("consult_triaged", m(triaged), consult_id=cid, hospital_id="H1")
    return s


def test_ranking_puts_hard_safety_first_and_explains_itself():
    alerts = _ranking_scenario().analyze(m(0)).alerts.alerts
    order = [a.alert_id for a in alerts]

    # Hand-derived: critical stroke delay > current coverage gap > critical non-stroke delay
    # > warning stroke delay.
    assert order == [
        "STAGE_TRIAGED_UNASSIGNED:consult:S1",
        "COVERAGE_GAP_NOW:hospital:H2",
        "STAGE_TRIAGED_UNASSIGNED:consult:G1",
        "STAGE_TRIAGED_UNASSIGNED:consult:S2",
    ]
    assert [a.priority for a in alerts] == [1, 2, 3, 4]
    top = alerts[0]
    assert top.priority_reasons[0].startswith("critical severity")
    assert "stroke" in top.priority_reasons[1]
    assert "1.20× the critical standard" in top.priority_reasons[2]


def test_alert_identity_is_stable_as_severity_escalates():
    s = _ranking_scenario()
    early = alerts_by_id(s.analyze(m(-6) + timedelta(minutes=5)))
    later = alerts_by_id(s.analyze(m(10)))

    alert_id = "STAGE_TRIAGED_UNASSIGNED:consult:S2"
    assert early[alert_id].severity.value == "warning"
    assert later[alert_id].severity.value == "critical"


# 16. Repeated calculation yields identical output ---------------------------------------


def test_analysis_is_deterministic_and_order_independent():
    s = _ranking_scenario()
    first = s.analyze(m(0))
    second = s.analyze(m(0))
    shuffled = list(s.events)
    random.Random(3).shuffle(shuffled)
    third = analyze(shuffled, s.reference, m(0))

    for a, b in ((first, second), (first, third)):
        assert a.alerts.model_dump() == b.alerts.model_dump()
        assert a.coverage.model_dump() == b.coverage.model_dump()
        assert a.demand.model_dump() == b.demand.model_dump()


def test_rules_are_overridable_from_json(tmp_path):
    from app.engines.rules import load_risk_config

    override = tmp_path / "rules.json"
    override.write_text(
        '{"routing_failure": {"severity": "critical"},'
        ' "coverage": {"projected_gap_severity": "critical", "horizon_minutes": 120}}'
    )
    config = load_risk_config(override)
    s = base().event("consult_triaged", m(0), consult_id="C1", hospital_id="H1")
    s.event("routing_attempt_failed", m(1), consult_id="C1", hospital_id="H1")

    analysis = s.analyze(m(2), config)

    assert config.coverage.horizon_minutes == 120
    assert analysis.coverage.horizon_minutes == 120
    assert severity(analysis, RuleCode.ROUTING_FAILURE) == "critical"
    assert config.stage_standards[0].warning_minutes == 5  # untouched defaults survive
