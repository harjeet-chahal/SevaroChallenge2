"""Generate the SYNTHETIC SAMPLE DATA dispatch & split-shift staffing scenario (Phase 4).

    cd backend && .venv/bin/python -m scripts.generate_staffing_dataset [output_dir]

Fully scripted (no randomness). Every time below is chosen so the optimizer results can
be worked out by hand; those hand-computed expectations live in
``tests/test_optimization_scenario.py``, not here and not from running the engine.

Reference time 2031-04-08 21:00:00Z (Tuesday; 17:00 EDT / 16:00 CDT / 15:00 MDT).

Dispatch:
- STF-C2 (General Neuro, STF-H4) waits longest; STF-C1 (Stroke, STF-H1) arrived later.
  Only Dr. Ada Staff can take C1 (Dr. Bo Staff is on video). Least-loaded routing in
  arrival order gives C2 to Ada (low volume) and strands the stroke consult; the
  optimizer gives C1 to Ada and C2 to Dr. Di Staff.
- STF-C3 is already ringing to Dr. Ed Staff; STF-C4 (Stroke, STF-H2) has no eligible
  physician (Bo on video, Cy ended a call 1 minute ago).

Staffing (planning window 21:00-01:00Z):
- STF-H1 short 22:00-23:00Z and 00:00-01:00Z, STF-H2 short 00:00-01:00Z, STF-H3 short
  22:15-22:30Z (a night physician's scheduled shift covers it from 22:30Z).
- Exactly one off-shift physician (Dr. Gil Staff) passes every rule; six others each fail
  exactly one: opt-in, rest, weekly hours, overlap, credentialing, missing data. (With the
  90-minute shortage look-ahead, STF-H2 is not short yet at 21:00Z, so Dr. Mo Staff also
  fails credentialing.)
- Gil is also credentialed at the busy, gap-free STF-H4: the split-shift trap.
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

OUTPUT = Path(__file__).resolve().parents[1] / "sample_data" / "synthetic_staffing"
LABEL = "SYNTHETIC SAMPLE DATA — dispatch & split-shift staffing scenario"
REF = datetime(2031, 4, 8, 21, 0, tzinfo=UTC)
NY, CHI, DEN = "America/New_York", "America/Chicago", "America/Denver"

HOSPITALS = [
    ("STF-H1", "Lakeside Sample Hospital", NY, "comprehensive"),
    ("STF-H2", "Prairie Sample Medical", CHI, "primary"),
    ("STF-H3", "Summit Sample Clinic", DEN, "primary"),
    ("STF-H4", "Harbor Sample Center", NY, "comprehensive"),
]
TZ = {h[0]: h[2] for h in HOSPITALS}

ON_SHIFT = [
    # id, name, start, end (EDT wall time on 2031-04-08), credentials
    ("STF-P1", "Dr. Ada Staff", "06:00", "18:00", ["STF-H1", "STF-H4"]),
    ("STF-P2", "Dr. Bo Staff", "08:00", "20:00", ["STF-H1", "STF-H2"]),
    ("STF-P3", "Dr. Cy Staff", "08:00", "20:00", ["STF-H2", "STF-H4"]),
    ("STF-P4", "Dr. Di Staff", "06:15", "18:15", ["STF-H3", "STF-H4"]),
    ("STF-P5", "Dr. Ed Staff", "09:00", "21:00", ["STF-H4"]),
]
OFF_SHIFT = [
    # id, name, role, opt_in, last ended, next start, hrs 7d, min online, channel, declined,
    # credentials. Each comment names the one rule the physician fails.
    # Fails opt-in.
    (
        "STF-P6",
        "Dr. Fay Staff",
        "day",
        "no",
        "2031-04-07T23:00:00Z",
        "2031-04-10T12:00:00Z",
        30,
        20,
        "sms",
        0,
        ["STF-H1"],
    ),
    # Eligible: rested since 10:00Z, 40 h + offer <= 60, next shift tomorrow 11:00Z.
    (
        "STF-P7",
        "Dr. Gil Staff",
        "float",
        "yes",
        "2031-04-08T10:00:00Z",
        "2031-04-09T11:00:00Z",
        40,
        15,
        "app_push",
        0,
        ["STF-H1", "STF-H3", "STF-H4"],
    ),
    # Fails rest: last shift ended 16:00Z, so 10 h only at 02:00Z (after the window).
    (
        "STF-P8",
        "Dr. Hal Staff",
        "day",
        "yes",
        "2031-04-08T16:00:00Z",
        "2031-04-09T14:00:00Z",
        20,
        10,
        "sms",
        0,
        ["STF-H3"],
    ),
    # Fails weekly hours: 59 h + 2 h > 60 h.
    (
        "STF-P9",
        "Dr. Ivy Staff",
        "day",
        "yes",
        "2031-04-07T22:00:00Z",
        "2031-04-10T11:00:00Z",
        59,
        10,
        "sms",
        1,
        ["STF-H1"],
    ),
    # Fails overlap: scheduled night shift starts 22:30Z (also counted as coverage from then).
    (
        "STF-P10",
        "Dr. Jo Staff",
        "night",
        "yes",
        "2031-04-08T08:00:00Z",
        "2031-04-08T22:30:00Z",
        36,
        0,
        "app_push",
        0,
        ["STF-H3"],
    ),
    # Fails credentialing: only credentialed at STF-H4, which has no gap.
    (
        "STF-P11",
        "Dr. Lu Staff",
        "float",
        "yes",
        "2031-04-07T20:00:00Z",
        "2031-04-10T12:00:00Z",
        24,
        10,
        "sms",
        0,
        ["STF-H4"],
    ),
    # Fails rest because the last shift end is missing (missing data never passes).
    (
        "STF-P12",
        "Dr. Mo Staff",
        "day",
        "yes",
        "",
        "2031-04-10T12:00:00Z",
        30,
        25,
        "app_push",
        0,
        ["STF-H2"],
    ),
]

EVENTS: list[dict] = []
PHYSICIAN_TZ = {p[0]: NY for p in ON_SHIFT}


def at(h: int, m: int, s: int = 0) -> datetime:
    return datetime(2031, 4, 8, h, m, s, tzinfo=UTC)


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
) -> None:
    zone = TZ.get(hospital) or PHYSICIAN_TZ.get(physician) or "UTC"
    EVENTS.append(
        {
            "event_time": when.astimezone(ZoneInfo(zone)).isoformat(timespec="seconds"),
            "ingested_at": (when + timedelta(seconds=lag)).astimezone(UTC),
            "consult_id": consult,
            "event_type": event_type,
            "physician_id": physician,
            "hospital_id": hospital,
            "description": description,
            "consult_type": consult_type,
            "_at": when,
        }
    )


def received(cid: str, hid: str, ctype: str, when: datetime) -> None:
    ev(
        "consult_received",
        when,
        consult=cid,
        hospital=hid,
        consult_type=ctype,
        description=f"{ctype} consult request received",
    )


def call(cid: str, hid: str, pid: str, start: datetime, end: datetime) -> None:
    ev("incoming_call_started", start, consult=cid, physician=pid, hospital=hid)
    ev("incoming_call_ended", end, consult=cid, physician=pid, hospital=hid)


def closed_consult(cid: str, hid: str, pid: str, ctype: str, t0: datetime) -> None:
    """Completed before the reference time: counts toward consults this shift only.
    The call ends at t0 + 16 min (that is the physician's last call if it is the latest)."""
    received(cid, hid, ctype, t0)
    ev("consult_triaged", t0 + timedelta(minutes=2), consult=cid, hospital=hid)
    ev("physician_assigned", t0 + timedelta(minutes=3), consult=cid, physician=pid, hospital=hid)
    call(cid, hid, pid, t0 + timedelta(minutes=4), t0 + timedelta(minutes=16))
    ev("note_started", t0 + timedelta(minutes=20), consult=cid, physician=pid, hospital=hid)
    ev("note_signed", t0 + timedelta(minutes=35), consult=cid, physician=pid, hospital=hid)


def open_note(cid: str, hid: str, pid: str, ctype: str, call_end: datetime) -> None:
    """Assigned this shift; call over, note not started (Note Pending, asynchronous)."""
    t0 = call_end - timedelta(minutes=16)
    received(cid, hid, ctype, t0)
    ev("consult_triaged", t0 + timedelta(minutes=2), consult=cid, hospital=hid)
    ev("physician_assigned", t0 + timedelta(minutes=3), consult=cid, physician=pid, hospital=hid)
    call(cid, hid, pid, t0 + timedelta(minutes=4), call_end)


def build() -> None:
    for pid, _, start, _, _ in ON_SHIFT:
        h, m = map(int, start.split(":"))
        begin = datetime(2031, 4, 8, h, m, tzinfo=ZoneInfo(NY)).astimezone(UTC)
        ev("shift_started", begin, physician=pid, description="Shift started")
        ev(
            "physician_status_changed",
            begin + timedelta(minutes=1),
            physician=pid,
            description="Self-reported status: Available",
        )

    # Dr. Ada Staff: 3 closed + 2 open notes = 5 consults (low volume); last call 20:20Z.
    for n, hh in enumerate((11, 13, 15)):
        closed_consult(f"STF-C1{n}0", "STF-H1", "STF-P1", "General Neuro", at(hh, 0))
    open_note("STF-C5", "STF-H1", "STF-P1", "General Neuro", at(19, 50))
    open_note("STF-C6", "STF-H4", "STF-P1", "General Neuro", at(20, 20))

    # Dr. Bo Staff: 5 closed + video in progress for STF-C10 (busy) = 6 consults.
    for n, hh in enumerate((13, 14, 15, 16, 17)):
        closed_consult(f"STF-C2{n}0", "STF-H2", "STF-P2", "General Neuro", at(hh, 0))
    received("STF-C10", "STF-H2", "Stroke", at(20, 30))
    ev("consult_triaged", at(20, 32), consult="STF-C10", hospital="STF-H2")
    ev("physician_assigned", at(20, 33), consult="STF-C10", physician="STF-P2", hospital="STF-H2")
    call("STF-C10", "STF-H2", "STF-P2", at(20, 34), at(20, 40))
    ev("video_started", at(20, 45), consult="STF-C10", physician="STF-P2", hospital="STF-H2")

    # Dr. Cy Staff: 5 closed + STF-C9 whose call ended at 20:59Z (1 minute before now).
    for n, hh in enumerate((13, 14, 15, 16, 17)):
        closed_consult(f"STF-C3{n}0", "STF-H4", "STF-P3", "General Neuro", at(hh, 30))
    open_note("STF-C9", "STF-H4", "STF-P3", "General Neuro", at(20, 59))

    # Dr. Di Staff: 7 closed consults (not low volume); last call ended 20:30Z.
    for n, (hh, mm) in enumerate(((11, 0), (12, 0), (13, 0), (14, 0), (15, 0), (16, 0), (20, 14))):
        closed_consult(f"STF-C4{n}0", "STF-H3", "STF-P4", "General Neuro", at(hh, mm))

    # Dr. Ed Staff: 4 closed consults; last call ended 20:35Z.
    for n, (hh, mm) in enumerate(((14, 0), (15, 0), (16, 0), (20, 19))):
        closed_consult(f"STF-C5{n}0", "STF-H4", "STF-P5", "General Neuro", at(hh, mm))

    # Consults that need routing at 21:00Z.
    received("STF-C2", "STF-H4", "General Neuro", at(20, 40))
    ev("consult_triaged", at(20, 42), consult="STF-C2", hospital="STF-H4")
    received("STF-C1", "STF-H1", "Stroke", at(20, 48))
    ev("consult_triaged", at(20, 50), consult="STF-C1", hospital="STF-H1")
    received("STF-C4", "STF-H2", "Stroke", at(20, 50))
    ev("consult_triaged", at(20, 52), consult="STF-C4", hospital="STF-H2")
    for minute in (53, 58):
        ev(
            "routing_attempt_failed",
            at(20, minute),
            consult="STF-C4",
            hospital="STF-H2",
            description="No available credentialed provider; retry scheduled",
        )
    received("STF-C3", "STF-H4", "General Neuro", at(20, 55))
    ev("consult_triaged", at(20, 57), consult="STF-C3", hospital="STF-H4")
    ev(
        "incoming_call_ringing",
        at(20, 59, 30),
        consult="STF-C3",
        physician="STF-P5",
        hospital="STF-H4",
        description="Hospital call ringing to intended physician",
    )

    # Ingested after the reference time: must not influence results at 21:00Z.
    ev("physician_assigned", at(21, 3), consult="STF-C1", physician="STF-P1", hospital="STF-H1")
    received("STF-C7", "STF-H3", "Stroke", at(21, 5))
    ev("shift_started", at(21, 20), physician="STF-P7", description="Shift started")


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
                f"STF-E{n:04d}",
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

    def iso(hhmm: str) -> str:
        h, m = map(int, hhmm.split(":"))
        return datetime(2031, 4, 8, h, m, tzinfo=ZoneInfo(NY)).isoformat()

    _write(
        out / "physicians_on_shift.csv",
        ["physician_id", "name", "shift_start", "shift_end", "role"],
        [[p[0], p[1], iso(p[2]), iso(p[3]), "day"] for p in ON_SHIFT],
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
    creds = {p[0]: (p[1], p[4]) for p in ON_SHIFT} | {r[0]: (r[1], r[10]) for r in OFF_SHIFT}
    _write(
        out / "credentialing_matrix.csv",
        ["physician_id", "physician_name", *ids],
        [
            [pid, name, *("Y" if h in hs else "" for h in ids)]
            for pid, (name, hs) in sorted(creds.items())
        ],
    )
    means = {"STF-H1": (1.0, 3.0), "STF-H2": (1.0, 3.0), "STF-H3": (0.5, 2.0), "STF-H4": (4.0, 6.0)}
    _write(
        out / "baseline_hourly_volume.csv",
        ["hospital_id", "hour", "mean", "p90", "day_type"],
        [[hid, hour, *means[hid], "weekday"] for hid in ids for hour in range(24)],
    )
    _write(
        out / "coverage_requirements.csv",
        ["hospital_id", "block_start", "block_end", "min_available_physicians"],
        [
            ["STF-H1", "07:00", "19:00", 2],
            ["STF-H1", "19:00", "07:00", 1],
            ["STF-H2", "00:00", "00:00", 1],
            ["STF-H3", "00:00", "00:00", 1],
            ["STF-H4", "00:00", "00:00", 1],
        ],
    )
    (out / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "label": LABEL,
                "synthetic": True,
                "reference_time": REF.astimezone(ZoneInfo(NY)).isoformat(),
                "generator": "backend/scripts/generate_staffing_dataset.py",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (out / "README.md").write_text(
        "# SYNTHETIC SAMPLE DATA — dispatch & split-shift staffing scenario\n\n"
        "**Everything here is invented.** Scripted to exercise Phase 4: a stroke consult that "
        "least-loaded routing strands, a ringing call, a consult with no eligible physician, "
        "and a projected gap that exactly one off-shift physician can cover while six others "
        "each fail one split-shift rule. The eligible physician is also credentialed at a busy "
        "hospital without a gap (the split-shift trap).\n\n"
        "Regenerate: `cd backend && .venv/bin/python -m scripts.generate_staffing_dataset`\n\n"
        "Load: `POST /api/datasets/sample?name=synthetic_staffing` or the UI sample picker.\n\n"
        "Hand-computed expectations: `backend/tests/test_optimization_scenario.py`.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT
    write_dataset(target)
    print(f"Wrote SYNTHETIC SAMPLE DATA to {target}")
