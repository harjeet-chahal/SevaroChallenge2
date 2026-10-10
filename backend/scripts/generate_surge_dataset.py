"""Generate the SYNTHETIC SAMPLE DATA surge / coverage-shortfall scenario.

    cd backend && .venv/bin/python -m scripts.generate_surge_dataset [output_dir]

Fully scripted (no randomness): every event time below is chosen so the expected Phase 3
results can be worked out by hand. Those hand-computed expectations live in
``tests/test_surge_scenario.py``, not in this file and not from running the engine.

Reference time 2030-09-10 22:35:00Z (18:35 EDT / 17:35 CDT / 15:35 PDT).

Scenario:
- SRG-H1 (New York): 4 consults in the last 60 min vs an 18:00 p90 of 2.0 -> demand spike,
  requirement 2 + 1. Two physicians' shifts end at 19:00 EDT with 3 open notes between
  them; the spike persists past 19:00 on known arrivals -> projected gap 19:00-19:15 EDT.
- SRG-H2 (Los Angeles): the only other credentialed physician is Temporarily Unavailable
  with a stroke consult assigned -> projected gap when the shared physician leaves.
- SRG-H3 (Chicago): no credentialed physician on shift and no baseline rows -> coverage gap
  now, demand spike not evaluable, a consult failing to route repeatedly.
- Events ingested after the reference time exist and must not leak into forecasts.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

OUTPUT = Path(__file__).resolve().parents[1] / "sample_data" / "synthetic_surge"
LABEL = "SYNTHETIC SAMPLE DATA — surge & coverage-shortfall scenario"
REF = datetime(2030, 9, 10, 22, 35, tzinfo=UTC)

HOSPITALS = [
    ("SRG-H1", "Northgate Sample Hospital", "America/New_York", "comprehensive"),
    ("SRG-H2", "Bayside Sample Medical", "America/Los_Angeles", "primary"),
    ("SRG-H3", "Ridge Sample Clinic", "America/Chicago", "primary"),
]
TZ = {h[0]: h[2] for h in HOSPITALS}
NY, LA = "America/New_York", "America/Los_Angeles"

ON_SHIFT = [
    # id, name, zone, start, end (local wall time on 2030-09-10), credentials
    ("SRG-P1", "Dr. Quinn Surge", NY, "07:00", "19:00", ["SRG-H1", "SRG-H2"]),
    ("SRG-P2", "Dr. Reese Surge", NY, "07:00", "19:00", ["SRG-H1"]),
    ("SRG-P3", "Dr. Sawyer Surge", NY, "11:00", "23:00", ["SRG-H1"]),
    ("SRG-P4", "Dr. Taylor Surge", LA, "08:00", "20:00", ["SRG-H2"]),
]
PHYSICIAN_TZ = {p[0]: p[2] for p in ON_SHIFT}
OFF_SHIFT = [
    # id, name, role, opt_in, last ended, next start, hrs 7d, min online, channel, declined, creds
    (
        "SRG-P5",
        "Dr. Umber Surge",
        "night",
        "yes",
        "2030-09-10T07:30:00-04:00",
        "2030-09-10T19:30:00-04:00",
        36,
        10,
        "sms",
        0,
        ["SRG-H1"],
    ),
    (
        "SRG-P6",
        "Dr. Vale Surge",
        "float",
        "yes",
        "2030-09-09T19:00:00-05:00",
        "2030-09-12T07:00:00-05:00",
        24,
        20,
        "app_push",
        0,
        ["SRG-H3"],
    ),
    (
        "SRG-P7",
        "Dr. Wren Surge",
        "day",
        "no",
        "2030-09-09T20:00:00-07:00",
        "2030-09-11T08:00:00-07:00",
        40,
        30,
        "sms",
        1,
        ["SRG-H2", "SRG-H3"],
    ),
]

EVENTS: list[dict] = []


def at(h: int, m: int, s: int = 0) -> datetime:
    return datetime(2030, 9, 10, h, m, s, tzinfo=UTC)


def ev(
    event_type: str,
    when: datetime,
    *,
    consult: str = "",
    physician: str = "",
    hospital: str = "",
    description: str = "",
    consult_type: str = "",
    lag: int = 2,
    ingested: datetime | None = None,
) -> None:
    zone = TZ.get(hospital) or PHYSICIAN_TZ.get(physician) or "UTC"
    EVENTS.append(
        {
            "event_time": when.astimezone(ZoneInfo(zone)).isoformat(timespec="seconds"),
            "ingested_at": (ingested or when + timedelta(seconds=lag)).astimezone(UTC),
            "consult_id": consult,
            "event_type": event_type,
            "physician_id": physician,
            "hospital_id": hospital,
            "description": description,
            "consult_type": consult_type,
            "_at": when,
        }
    )


def received(cid: str, hid: str, ctype: str, when: datetime, **kw) -> None:
    ev(
        "consult_received",
        when,
        consult=cid,
        hospital=hid,
        consult_type=ctype,
        description=f"{ctype} consult request received",
        **kw,
    )


def closed_consult(cid: str, hid: str, pid: str, ctype: str, t0: datetime) -> None:
    """A consult fully completed well before the reference time (shift counts only)."""
    received(cid, hid, ctype, t0)
    ev("consult_triaged", t0 + timedelta(minutes=2), consult=cid, hospital=hid)
    ev("physician_assigned", t0 + timedelta(minutes=3), consult=cid, physician=pid, hospital=hid)
    ev("incoming_call_started", t0 + timedelta(minutes=4), consult=cid, physician=pid, hospital=hid)
    ev("incoming_call_ended", t0 + timedelta(minutes=16), consult=cid, physician=pid, hospital=hid)
    ev("note_started", t0 + timedelta(minutes=20), consult=cid, physician=pid, hospital=hid)
    ev("note_signed", t0 + timedelta(minutes=35), consult=cid, physician=pid, hospital=hid)


def build() -> None:
    for pid, _, zone, start, _, _ in ON_SHIFT:
        h, m = map(int, start.split(":"))
        begin = datetime(2030, 9, 10, h, m, tzinfo=ZoneInfo(zone)).astimezone(UTC)
        ev("shift_started", begin, physician=pid, description="Shift started")
        ev(
            "physician_status_changed",
            begin + timedelta(minutes=2),
            physician=pid,
            description="Self-reported status: Available",
        )

    closed_consult("SRG-C101", "SRG-H1", "SRG-P1", "General Neuro", at(13, 0))
    closed_consult("SRG-C102", "SRG-H2", "SRG-P1", "Stroke", at(15, 0))
    closed_consult("SRG-C103", "SRG-H1", "SRG-P2", "General Neuro", at(14, 0))
    closed_consult("SRG-C104", "SRG-H1", "SRG-P3", "Stroke", at(17, 0))
    closed_consult("SRG-C105", "SRG-H2", "SRG-P4", "General Neuro", at(17, 30))

    # SRG-H1 — outside the trailing window (21:20 <= 21:35): note pending since 21:40.
    received("SRG-C200", "SRG-H1", "General Neuro", at(21, 20))
    ev("consult_triaged", at(21, 22), consult="SRG-C200", hospital="SRG-H1")
    ev("physician_assigned", at(21, 24), consult="SRG-C200", physician="SRG-P1", hospital="SRG-H1")
    ev(
        "incoming_call_started",
        at(21, 26),
        consult="SRG-C200",
        physician="SRG-P1",
        hospital="SRG-H1",
    )
    ev("incoming_call_ended", at(21, 40), consult="SRG-C200", physician="SRG-P1", hospital="SRG-H1")
    # Four arrivals inside (21:35, 22:35]: 21:50, 22:05, 22:15, 22:25.
    received("SRG-C201", "SRG-H1", "Stroke", at(21, 50))
    ev("consult_triaged", at(21, 52), consult="SRG-C201", hospital="SRG-H1")
    ev("physician_assigned", at(21, 53), consult="SRG-C201", physician="SRG-P1", hospital="SRG-H1")
    ev(
        "incoming_call_started",
        at(21, 54),
        consult="SRG-C201",
        physician="SRG-P1",
        hospital="SRG-H1",
    )
    ev("imaging_requested", at(21, 56), consult="SRG-C201", hospital="SRG-H1")
    ev("incoming_call_ended", at(22, 0), consult="SRG-C201", physician="SRG-P1", hospital="SRG-H1")
    ev("imaging_returned", at(22, 12), consult="SRG-C201", hospital="SRG-H1")
    ev("video_started", at(22, 15), consult="SRG-C201", physician="SRG-P1", hospital="SRG-H1")
    ev("video_ended", at(22, 27), consult="SRG-C201", physician="SRG-P1", hospital="SRG-H1")
    received("SRG-C202", "SRG-H1", "General Neuro", at(22, 5))
    ev("consult_triaged", at(22, 7), consult="SRG-C202", hospital="SRG-H1")
    ev("physician_assigned", at(22, 8), consult="SRG-C202", physician="SRG-P2", hospital="SRG-H1")
    ev(
        "incoming_call_started",
        at(22, 10),
        consult="SRG-C202",
        physician="SRG-P2",
        hospital="SRG-H1",
    )
    ev("incoming_call_ended", at(22, 22), consult="SRG-C202", physician="SRG-P2", hospital="SRG-H1")
    ev("note_started", at(22, 30), consult="SRG-C202", physician="SRG-P2", hospital="SRG-H1")
    received("SRG-C203", "SRG-H1", "Stroke", at(22, 15))
    ev("consult_triaged", at(22, 17), consult="SRG-C203", hospital="SRG-H1")
    ev("physician_assigned", at(22, 18), consult="SRG-C203", physician="SRG-P3", hospital="SRG-H1")
    ev(
        "incoming_call_started",
        at(22, 19),
        consult="SRG-C203",
        physician="SRG-P3",
        hospital="SRG-H1",
    )
    ev("imaging_requested", at(22, 20), consult="SRG-C203", hospital="SRG-H1")
    ev("incoming_call_ended", at(22, 28), consult="SRG-C203", physician="SRG-P3", hospital="SRG-H1")
    received("SRG-C204", "SRG-H1", "Stroke", at(22, 25))
    ev("consult_triaged", at(22, 28), consult="SRG-C204", hospital="SRG-H1")
    # Why routing fails: P1 on a call, P2 camera on with no Synapse, P3 ended a call < 2 min ago.
    ev("camera_active", at(22, 26), physician="SRG-P2", description="Desktop agent: camera active")
    ev(
        "outgoing_call_started",
        at(22, 28),
        consult="SRG-C200",
        physician="SRG-P1",
        hospital="SRG-H1",
        description="Provider calls hospital about pending note",
    )
    ev(
        "routing_attempt_failed",
        at(22, 29),
        consult="SRG-C204",
        hospital="SRG-H1",
        description="No available credentialed provider; retry scheduled",
    )
    ev(
        "outgoing_call_started",
        at(22, 33),
        consult="SRG-C203",
        physician="SRG-P3",
        hospital="SRG-H1",
        description="Provider calls hospital to check CT/CTA status",
    )
    ev(
        "routing_attempt_failed",
        at(22, 34),
        consult="SRG-C204",
        hospital="SRG-H1",
        description="No available credentialed provider; retry scheduled",
    )

    # SRG-H2 — stroke consult assigned to a physician who then goes unavailable.
    received("SRG-C210", "SRG-H2", "Stroke", at(22, 20))
    ev("consult_triaged", at(22, 22), consult="SRG-C210", hospital="SRG-H2")
    ev("physician_assigned", at(22, 24), consult="SRG-C210", physician="SRG-P4", hospital="SRG-H2")
    ev(
        "physician_status_changed",
        at(22, 27),
        physician="SRG-P4",
        description="Self-reported status: Temporarily Unavailable",
    )

    # SRG-H3 — nobody credentialed is on shift; routing keeps failing.
    received("SRG-C220", "SRG-H3", "General Neuro", at(22, 10))
    ev("consult_triaged", at(22, 12), consult="SRG-C220", hospital="SRG-H3")
    for minute in (13, 18, 23, 28, 33):
        ev(
            "routing_attempt_failed",
            at(22, minute),
            consult="SRG-C220",
            hospital="SRG-H3",
            description="No available credentialed provider; retry scheduled",
        )

    # Ingested after the reference time: must not influence analysis at the reference time.
    received("SRG-C205", "SRG-H1", "Stroke", at(22, 40))
    ev("shift_started", at(22, 50), physician="SRG-P5", description="Shift started early")
    ev("outgoing_call_ended", at(22, 36), consult="SRG-C200", physician="SRG-P1", hospital="SRG-H1")
    ev("outgoing_call_ended", at(22, 38), consult="SRG-C203", physician="SRG-P3", hospital="SRG-H1")
    ev("physician_assigned", at(22, 39), consult="SRG-C204", physician="SRG-P3", hospital="SRG-H1")


def _write(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def write_dataset(out: Path) -> None:
    EVENTS.clear()
    build()
    out.mkdir(parents=True, exist_ok=True)
    EVENTS.sort(key=lambda e: (e["ingested_at"], e["_at"], e["event_type"], e["consult_id"]))
    _write(
        out / "event_stream.csv",
        [
            "event_id",
            "event_time",
            "ingested_at",
            "consult_id",
            "event_type",
            "physician_id",
            "hospital_id",
            "description",
            "consult_type",
        ],
        [
            [
                f"SRG-E{n:04d}",
                e["event_time"],
                e["ingested_at"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                e["consult_id"],
                e["event_type"],
                e["physician_id"],
                e["hospital_id"],
                e["description"],
                e["consult_type"],
            ]
            for n, e in enumerate(EVENTS, start=1)
        ],
    )
    _write(
        out / "hospitals.csv",
        ["hospital_id", "name", "timezone", "coverage_tier"],
        [list(h) for h in HOSPITALS],
    )

    def iso(zone: str, hhmm: str) -> str:
        h, m = map(int, hhmm.split(":"))
        return datetime(2030, 9, 10, h, m, tzinfo=ZoneInfo(zone)).isoformat()

    _write(
        out / "physicians_on_shift.csv",
        ["physician_id", "name", "shift_start", "shift_end", "role"],
        [[p[0], p[1], iso(p[2], p[3]), iso(p[2], p[4]), "day"] for p in ON_SHIFT],
    )
    _write(
        out / "physicians_off_shift_roster.csv",
        [
            "physician_id",
            "name",
            "role",
            "opt_in",
            "last_shift_ended",
            "next_shift_starts",
            "hours_worked_7d",
            "minutes_to_online",
            "channel",
            "declined_30d",
        ],
        [list(r[:10]) for r in OFF_SHIFT],
    )
    ids = [h[0] for h in HOSPITALS]
    creds = {p[0]: (p[1], p[5]) for p in ON_SHIFT} | {r[0]: (r[1], r[10]) for r in OFF_SHIFT}
    _write(
        out / "credentialing_matrix.csv",
        ["physician_id", "physician_name", *ids],
        [
            [pid, name, *("Y" if h in hs else "" for h in ids)]
            for pid, (name, hs) in sorted(creds.items())
        ],
    )
    baseline = []
    for hour in range(24):
        p90_h1 = {18: 2.0, 19: 1.5}.get(hour, 3.0)
        baseline.append(["SRG-H1", hour, round(p90_h1 / 2, 2), p90_h1, "weekday"])
        baseline.append(["SRG-H2", hour, 1.2, 2.5, "weekday"])
        # SRG-H3 deliberately has no baseline rows (missing data must be flagged, not filled).
    _write(
        out / "baseline_hourly_volume.csv",
        ["hospital_id", "hour", "mean", "p90", "day_type"],
        baseline,
    )
    _write(
        out / "coverage_requirements.csv",
        ["hospital_id", "block_start", "block_end", "min_available_physicians"],
        [
            ["SRG-H1", "07:00", "19:00", 2],
            ["SRG-H1", "19:00", "07:00", 1],
            ["SRG-H2", "07:00", "19:00", 1],
            ["SRG-H2", "19:00", "07:00", 1],
            ["SRG-H3", "00:00", "00:00", 1],
        ],
    )
    (out / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "label": LABEL,
                "synthetic": True,
                "reference_time": REF.astimezone(ZoneInfo(NY)).isoformat(),
                "generator": "backend/scripts/generate_surge_dataset.py",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "README.md").write_text(
        "# SYNTHETIC SAMPLE DATA — surge & coverage-shortfall scenario\n\n"
        "**Everything here is invented.** Scripted to exercise Phase 3: a demand spike, shift "
        "ends producing a projected gap, a hospital with no credentialed physician on shift, "
        "a missing baseline, and events ingested after the reference time.\n\n"
        "Regenerate: `cd backend && .venv/bin/python -m scripts.generate_surge_dataset`\n\n"
        "Load: `POST /api/datasets/sample?name=synthetic_surge` or the UI sample picker.\n\n"
        "Hand-computed expectations: `backend/tests/test_surge_scenario.py`.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT
    write_dataset(target)
    print(f"Wrote SYNTHETIC SAMPLE DATA to {target}")
