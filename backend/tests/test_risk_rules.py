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
from tests.analysis_helpers import Scenario, alerts_by_id, hospital_coverage, utc

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


def test_open_notes_stay_flagged_after_the_shift_has_ended():
    # The shift ended 5 min ago with one note still open: critical, not silently dropped.
    analysis = _notes_scenario(1, -5).analyze(m(0))

    assert severity(analysis, RuleCode.OPEN_NOTES_NEAR_SHIFT_END, "physician:P1") == "critical"
    alert = alerts_by_id(analysis)[f"{RuleCode.OPEN_NOTES_NEAR_SHIFT_END.value}:physician:P1"]
    assert "shift ended" in alert.title and alert.assumptions


def _left_with_a_stroke_consult(session_for_this_consult: bool) -> Scenario:
    """P1's shift ends at -5 while still on a video; P1 owns stroke consult C1 (imaging)."""
    s = Scenario().hospital("H1").on_shift("P1", ["H1"], m(-600), m(-5))
    s.requirement("H1", "00:00", "00:00", 1)
    s.event("consult_received", m(-40), consult_id="C1", hospital_id="H1", consult_type="Stroke")
    s.event("physician_assigned", m(-39), consult_id="C1", hospital_id="H1", physician_id="P1")
    s.event("imaging_requested", m(-30), consult_id="C1", hospital_id="H1", physician_id="P1")
    other = "C1" if session_for_this_consult else "X"
    s.event("video_started", m(-10), consult_id=other, hospital_id="H1", physician_id="P1")
    return s


def test_a_consult_owned_by_a_physician_whose_shift_ended_is_flagged_even_while_busy():
    alerts = alerts_by_id(_left_with_a_stroke_consult(False).analyze(m(0)))
    alert = alerts[f"{RuleCode.ASSIGNED_PHYSICIAN_UNAVAILABLE.value}:consult:C1"]

    assert alert.severity.value == "critical"
    assert "off shift" in alert.title and "shift ended" in alert.summary
    # Still in a session for this very consult: they are working on it, not flagged.
    still_working = alerts_by_id(_left_with_a_stroke_consult(True).analyze(m(0)))
    assert f"{RuleCode.ASSIGNED_PHYSICIAN_UNAVAILABLE.value}:consult:C1" not in still_working


def test_a_consult_assigned_to_a_physician_not_yet_on_shift_says_so():
    s = base().off_shift("N1", ["H1"], next_start=m(40))
    s.event("physician_assigned", m(-1), consult_id="C1", hospital_id="H1", physician_id="N1")
    alert = alerts_by_id(s.analyze(m(0)))[
        f"{RuleCode.ASSIGNED_PHYSICIAN_UNAVAILABLE.value}:consult:C1"
    ]

    assert "not on shift" in alert.summary and "Temporarily Unavailable" not in alert.summary


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
    # P1 is H1's only physician: nobody can take a reassignment, so escalate.
    assert alert.recommended_action_type.value == "escalate"
    assert "no other credentialed physician" in alert.recommended_action_reason
    assert alert.condition_since == m(0)


def test_reassignment_is_recommended_only_when_someone_is_free_to_take_it():
    def scenario(colleague_busy: bool):
        s = base().on_shift("P2", ["H1"], m(-300), m(600))
        s.event("consult_triaged", m(-1.5), consult_id="C1", hospital_id="H1")
        s.event("physician_assigned", m(-1), consult_id="C1", hospital_id="H1", physician_id="P1")
        s.event(
            "physician_status_changed", m(0), physician_id="P1", status="Temporarily Unavailable"
        )
        if colleague_busy:
            s.event("video_started", m(0.5), consult_id="X", hospital_id="H1", physician_id="P2")
        alert = alerts_by_id(s.analyze(m(1)))[
            f"{RuleCode.ASSIGNED_PHYSICIAN_UNAVAILABLE.value}:consult:C1"
        ]
        return alert.recommended_action_type.value, alert.recommended_action_reason

    action, reason = scenario(colleague_busy=False)
    assert action == "reassign_consult" and "Free to take it now" in reason and "P2" in reason
    action, reason = scenario(colleague_busy=True)
    assert action == "escalate" and "video" in reason


def test_a_quiet_helper_app_is_flagged_even_for_a_busy_or_in_meeting_physician():
    s = base().on_shift("P2", ["H1"], m(-300), m(600))
    s.event("incoming_call_started", m(-5), consult_id="X", hospital_id="H1", physician_id="P1")
    s.event("agent_heartbeat_lost", m(-3), physician_id="P1")
    s.event("physician_status_changed", m(-4), physician_id="P2", status="In Meeting")
    s.event("agent_heartbeat_lost", m(-2), physician_id="P2")
    analysis = s.analyze(m(0))
    alerts = alerts_by_id(analysis)

    for pid in ("P1", "P2"):  # P1 busy on a call, P2 "In Meeting"
        assert f"{RuleCode.SIGNAL_AGENT_OFFLINE.value}:physician:{pid}" in alerts
    contributors = {c.physician_id: c for c in hospital_coverage(analysis, "H1").contributors}
    assert contributors["P1"].certainty == "uncertain"
    assert contributors["P2"].certainty == "uncertain"


def test_a_repeat_call_moves_the_consult_up_within_its_class():
    s = base()  # C1 received at -2
    s.event("consult_triaged", m(-12), consult_id="C1", hospital_id="H1")
    s.event("consult_received", m(-13), consult_id="C2", hospital_id="H1", consult_type="Stroke")
    s.event("consult_triaged", m(-13), consult_id="C2", hospital_id="H1")

    def order(analysis):
        return [
            a.consult_id for a in analysis.alerts.alerts if a.rule_code.value.startswith("STAGE")
        ]

    assert order(s.analyze(m(0)))[0] == "C2"  # C2 has waited longer in triage
    s.event("consult_received", m(-1), consult_id="C1", hospital_id="H1", consult_type="Stroke")
    analysis = s.analyze(m(0))
    first = next(a for a in analysis.alerts.alerts if a.consult_id == "C1")

    assert order(analysis)[0] == "C1"  # the hospital called again about C1
    assert first.rank.repeat_requests == 1
    assert any("called again" in r for r in first.priority_reasons)
    assert first.elapsed_seconds == 12 * 60  # the clock was not restarted


def test_a_ring_stops_when_the_consult_is_answered_by_someone_else_or_times_out():
    s = base().on_shift("P2", ["H1"], m(-300), m(600))
    s.event("incoming_call_ringing", m(-1), consult_id="C1", hospital_id="H1", physician_id="P1")
    s.event("incoming_call_started", m(-0.5), consult_id="C1", hospital_id="H1", physician_id="P2")
    s.event("consult_received", m(-7), consult_id="C2", hospital_id="H1", consult_type="Stroke")
    s.event("incoming_call_ringing", m(-6), consult_id="C2", hospital_id="H1", physician_id="P1")
    p1 = next(p for p in s.analyze(m(0)).state.physicians if p.physician_id == "P1")

    # C1 was answered by P2; C2 has rung unanswered for 6 min (> 5 min): P1 is not ringing.
    assert p1.signals.ringing == []


def test_a_consult_routed_without_a_triage_event_is_timed_as_waiting_for_a_doctor():
    s = base()  # C1 received at -2, never triaged
    s.event("consult_received", m(-9), consult_id="C2", hospital_id="H1", consult_type="Stroke")
    s.event("incoming_call_ringing", m(-6), consult_id="C2", hospital_id="H1", physician_id="P1")
    alerts = alerts_by_id(s.analyze(m(0)))

    alert = alerts[f"{RuleCode.STAGE_TRIAGED_UNASSIGNED.value}:consult:C2"]
    assert alert.severity.value == "warning"
    assert alert.elapsed_seconds == 6 * 60  # from the first ring, not from receipt
    assert alert.assumptions and "no triage event" in alert.assumptions[0]
    # C1 has had no routing activity yet: "received, not triaged" has no standard.
    assert f"{RuleCode.STAGE_TRIAGED_UNASSIGNED.value}:consult:C1" not in alerts


def _stroke_after_scans() -> Scenario:
    """C1: call at +3..+5 (provisional Note Pending), then scans +6..+16 supersede it."""
    s = base()
    s.event("consult_triaged", m(0), consult_id="C1", hospital_id="H1")
    s.event("physician_assigned", m(1), consult_id="C1", hospital_id="H1", physician_id="P1")
    s.event("incoming_call_started", m(3), consult_id="C1", hospital_id="H1", physician_id="P1")
    s.event("incoming_call_ended", m(5), consult_id="C1", hospital_id="H1", physician_id="P1")
    s.event("imaging_requested", m(6), consult_id="C1", hospital_id="H1", physician_id="P1")
    s.event("imaging_returned", m(16), consult_id="C1", hospital_id="H1", physician_id="P1")
    return s


def test_a_phone_only_consult_after_scans_reaches_note_pending_at_the_call_end():
    s = _stroke_after_scans()
    s.event("outgoing_call_started", m(18), consult_id="C1", hospital_id="H1", physician_id="P1")
    s.event("outgoing_call_ended", m(20), consult_id="C1", hospital_id="H1", physician_id="P1")
    s.event("note_started", m(21), consult_id="C1", hospital_id="H1", physician_id="P1")
    analysis = s.analyze(m(40))

    # Note clock from the call-back (+20): 20 min, below the 30-min stroke warning. Before,
    # the superseded +5 Note Pending made it 35 min.
    assert severity(analysis, RuleCode.NOTE_OVERDUE) is None
    assert severity(analysis, RuleCode.STAGE_IMAGING_REVIEW) is None
    assert severity(_with_note_at(s, 51), RuleCode.NOTE_OVERDUE) == "warning"  # 31 min


def _with_note_at(s: Scenario, minute: float):
    return s.analyze(m(minute))


def test_a_superseded_note_pending_never_starts_the_note_clock():
    s = _stroke_after_scans()  # video_ended record missing below
    s.event("video_started", m(18), consult_id="C1", hospital_id="H1", physician_id="P1")
    s.event("note_started", m(30), consult_id="C1", hospital_id="H1", physician_id="P1")
    analysis = s.analyze(m(40))

    assert severity(analysis, RuleCode.NOTE_OVERDUE) is None  # 10 min from note start
    later = alerts_by_id(s.analyze(m(61)))[f"{RuleCode.NOTE_OVERDUE.value}:consult:C1"]
    assert later.elapsed_seconds == 31 * 60 and "note start" in later.assumptions[0]


def test_a_shift_started_after_the_scheduled_end_puts_the_physician_back_on_shift():
    s = Scenario().hospital("H1").on_shift("P1", ["H1"], m(-600), m(-10))
    s.requirement("H1", "00:00", "00:00", 1)
    s.event("shift_started", m(-5), physician_id="P1")
    analysis = s.analyze(m(0))
    p1 = next(p for p in analysis.state.physicians if p.physician_id == "P1")

    assert p1.on_shift is True and p1.minutes_to_shift_end is None
    assert "shift_restarted" in {f.code for f in p1.flags}
    assert hospital_coverage(analysis, "H1").metrics.deficit_now == 0


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
