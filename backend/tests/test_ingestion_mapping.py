"""The adapter layer: header aliases, value interpretation and their reporting.

These cover format variations the judging dataset might use (display-style headers,
time-only shifts, a matrix without ID prefixes) without guessing silently.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.services.dataset_import.mapping import DatasetMapping, load_mapping
from app.services.dataset_import.pipeline import validate_dataset
from app.services.dataset_import.sources import DatasetFile

NOW = datetime(2031, 1, 1, tzinfo=UTC)

HOSPITALS = (
    "hospital_id,name,timezone,coverage_tier\n"
    "X-001,North,America/New_York,a\n"
    "X-002,South,America/Chicago,b\n"
)
# Display-style headers as shown in the brief's tables ("Event", "Phys.", "Hosp.", ...).
EVENTS = (
    "Event,Event time,Ingested,Consult,Type,Phys.,Hosp.,Description\n"
    "E1,2031-03-02T08:00:00-05:00,2031-03-02T08:00:02-05:00,,shift_started,D1,,Shift\n"
    "E2,2031-03-02T08:05:00-05:00,2031-03-02T08:05:01-05:00,,physician_status_changed,D1,,"
    "Self-reported status: In Meeting\n"
    "E3,2031-03-02T09:00:00-05:00,2031-03-02T09:00:03-05:00,K1,consult_received,,X-002,"
    "General Neuro consult request received\n"
)
ON_SHIFT_TIME_ONLY = "ID,Physician,Shift (ET)\nD1,Dr One,08:00-20:00\nD2,Dr Two,19:00-07:00\n"
OFF_SHIFT_PARTIAL_DATES = (
    "ID,Physician,Role,Opt-in,Last shift ended,Next shift starts,"
    "Hrs 7d,Min to online,Channel,Declined 30d\n"
    "D3,Dr Three,Night,Yes,03-01 07:00,03-02 19:00,36,15,sms,1\n"
)
MATRIX_NO_PREFIX = "Physician,Name,001,002\nD1,Dr One,Y,\nD2,Dr Two,Y,Y\nD3,Dr Three,,Y\n"


def _files(**overrides: str) -> list[DatasetFile]:
    files = {
        "hospitals.csv": HOSPITALS,
        "event_stream.csv": EVENTS,
        "physicians_on_shift.csv": ON_SHIFT_TIME_ONLY,
        "physicians_off_shift_roster.csv": OFF_SHIFT_PARTIAL_DATES,
        "credentialing_matrix.csv": MATRIX_NO_PREFIX,
        **overrides,
    }
    return [DatasetFile(name=k, data=v.encode(), origin="test") for k, v in files.items() if v]


def _validate(files, mapping=None, **kwargs):
    return validate_dataset(
        files,
        mapping or DatasetMapping(),
        import_id="imp_test",
        source_name="test",
        started_at=NOW,
        **kwargs,
    )


def _codes(result):
    return {i.code for i in result.report.issues}


def test_brief_style_headers_and_partial_times_import_with_everything_reported():
    result = _validate(_files())

    assert result.ok, [i.message for i in result.report.issues if i.severity == "error"]
    events = {m.table: m.mapped for m in result.report.column_mappings}["event_stream"]
    assert events["event_id"] == "Event" and events["physician_id"] == "Phys."
    # The in-meeting status came from the description text, and that is reported.
    assert "description_fallback" in _codes(result)

    by_id = {p.id: p for p in result.physicians}
    day = by_id["D1"].schedule.current_shift
    assert day.start == datetime(2031, 3, 2, 13, 0, tzinfo=UTC)  # 08:00 ET from "Shift (ET)"
    night = by_id["D2"].schedule.current_shift
    assert (night.end - night.start).total_seconds() == 12 * 3600  # crosses midnight
    assert any(
        i.code == "datetime_interpreted" and "column header label 'et'" in i.message
        for i in result.report.issues
    )


def test_off_shift_partial_dates_use_event_stream_offset_and_warn():
    result = _validate(_files())
    d3 = next(p for p in result.physicians if p.id == "D3")

    assert d3.split_shift_opt_in is True
    assert d3.schedule.last_shift_ended_at == datetime(2031, 3, 1, 12, 0, tzinfo=UTC)
    assert d3.schedule.minutes_to_come_online == 15
    warning = next(
        i
        for i in result.report.issues
        if i.code == "datetime_interpreted" and i.file == "physicians_off_shift_roster.csv"
    )
    assert warning.severity == "warning" and "UTC-05:00" in warning.message


def test_matrix_headers_without_prefix_match_by_unique_suffix_and_are_listed():
    result = _validate(_files())
    creds = {p.id: p.credentialed_hospital_ids for p in result.physicians}

    assert creds == {"D1": ["X-001"], "D2": ["X-001", "X-002"], "D3": ["X-002"]}
    matched = [i for i in result.report.issues if i.code == "credential_header_matched"]
    assert len(matched) == 2


def test_unmatched_matrix_column_is_an_actionable_error():
    matrix = "Physician,999\nD1,Y\n"
    result = _validate(_files(**{"credentialing_matrix.csv": matrix}))

    assert not result.ok
    issue = next(i for i in result.report.issues if i.code == "unmatched_matrix_columns")
    assert "999" in issue.message and "hospital_header_prefix" in issue.hint


def test_long_format_credentials_are_supported():
    long = "physician_id,hospital_id\nD1,X-001\nD2,X-002\nD3,X-002\n"
    result = _validate(_files(**{"credentialing_matrix.csv": long}))

    assert result.ok
    assert {p.id: p.credentialed_hospital_ids for p in result.physicians}["D2"] == ["X-002"]


def test_offsetless_times_fail_without_a_zone_policy():
    events = EVENTS.replace("-05:00", "Z", 3)  # now the offsets differ: no single offset
    mapping = DatasetMapping()
    result = _validate(
        _files(
            **{
                "event_stream.csv": events,
                "physicians_on_shift.csv": "ID,Physician,Shift\nD1,Dr,08:00-20:00\n",
            }
        ),
        mapping,
    )

    assert not result.ok
    issue = next(i for i in result.report.issues if i.code == "invalid_datetime")
    assert "naive_timezone" in issue.hint


def test_json_override_adds_aliases_without_code_changes(tmp_path):
    override = tmp_path / "mapping.json"
    override.write_text(
        json.dumps(
            {"tables": {"hospitals": {"timezone": {"aliases": ["iana_zone"], "required": True}}}}
        )
    )
    hospitals = HOSPITALS.replace("timezone", "iana_zone", 1)

    default = _validate(_files(**{"hospitals.csv": hospitals}))
    custom = _validate(_files(**{"hospitals.csv": hospitals}), load_mapping(override))

    assert "missing_column" in _codes(default) and not default.ok
    assert custom.ok


def test_duplicate_reference_ids_are_errors():
    result = _validate(_files(**{"hospitals.csv": HOSPITALS + "X-001,Again,UTC,a\n"}))

    assert not result.ok and "duplicate_id" in _codes(result)


def test_unknown_physician_in_events_is_a_warning_not_a_failure():
    events = (
        EVENTS + "E9,2031-03-02T09:30:00-05:00,2031-03-02T09:30:01-05:00,,camera_active,ZZZ,,\n"
    )
    result = _validate(_files(**{"event_stream.csv": events}))

    assert result.ok and "event_unknown_physician" in _codes(result)


def test_reference_time_from_snapshot_filename_in_latest_event_offset():
    snapshot = "Consult,Current stage\nK1,Received\n"
    result = _validate(_files(**{"snapshot_consults_0915.csv": snapshot}))

    assert result.report.reference_source == "snapshot_filename"
    assert result.report.reference_time == datetime(2031, 3, 2, 14, 15, tzinfo=UTC)
