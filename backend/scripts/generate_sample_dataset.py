"""Generate the SYNTHETIC SAMPLE DATA development fixture.

    cd backend && .venv/bin/python -m scripts.generate_sample_dataset [output_dir]

Deterministic: a fixed seed drives the background consults, so the output is
byte-for-byte reproducible. Everything here is invented for development. The IDs, names,
dates and times are deliberately unlike the challenge's examples, and none of its
expected outcomes are reproduced.

The expected reference snapshot is written from the scenario script itself (what each
story is defined to be doing at the reference time), not by running the engine, so it
is an independent check of the replay.
"""

from __future__ import annotations

import csv
import json
import random
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

SEED = 20300514
OUTPUT = Path(__file__).resolve().parents[1] / "sample_data" / "synthetic_dev"
LABEL = "SYNTHETIC SAMPLE DATA — Sevaro Pulse development fixture"

REF = datetime(2030, 5, 14, 21, 30, tzinfo=UTC)  # 17:30 EDT / 16:30 CDT / 14:30 PDT
DAY = REF.date()

HOSPITALS = [
    ("DEV-H01", "Lakeshore Sample Medical Center", "America/New_York", "comprehensive"),
    ("DEV-H02", "Prairie Sample Hospital", "America/Chicago", "primary"),
    ("DEV-H03", "Mesa Sample Regional", "America/Denver", "primary"),
    ("DEV-H04", "Canyon Sample Community", "America/Phoenix", "acute_ready"),
    ("DEV-H05", "Harbor Sample General", "America/Los_Angeles", "comprehensive"),
]
HOSPITAL_TZ = {h[0]: h[2] for h in HOSPITALS}


@dataclass
class OnShift:
    id: str
    name: str
    tz: str
    start: str
    end: str
    creds: list[str]
    story_start: datetime  # background consults finish their busy phases before this


ON_SHIFT = [
    OnShift(
        "DEV-P01",
        "Dr. Avery Sample",
        "America/New_York",
        "08:00",
        "20:00",
        ["DEV-H01", "DEV-H02", "DEV-H03"],
        datetime(2030, 5, 14, 19, 50, tzinfo=UTC),
    ),
    OnShift(
        "DEV-P02",
        "Dr. Blake Sample",
        "America/New_York",
        "07:00",
        "19:00",
        ["DEV-H01", "DEV-H04", "DEV-H05"],
        datetime(2030, 5, 14, 20, 30, tzinfo=UTC),
    ),
    OnShift(
        "DEV-P03",
        "Dr. Casey Sample",
        "America/Chicago",
        "08:00",
        "20:00",
        ["DEV-H02", "DEV-H03"],
        datetime(2030, 5, 14, 20, 0, tzinfo=UTC),
    ),
    OnShift(
        "DEV-P04",
        "Dr. Devon Sample",
        "America/New_York",
        "10:00",
        "22:00",
        ["DEV-H01", "DEV-H02", "DEV-H05"],
        datetime(2030, 5, 14, 20, 45, tzinfo=UTC),
    ),
    OnShift(
        "DEV-P05",
        "Dr. Emery Sample",
        "America/Los_Angeles",
        "06:00",
        "18:00",
        ["DEV-H04", "DEV-H05"],
        datetime(2030, 5, 14, 21, 0, tzinfo=UTC),
    ),
    OnShift(
        "DEV-P06",
        "Dr. Finley Sample",
        "America/New_York",
        "09:00",
        "21:00",
        ["DEV-H03", "DEV-H05"],
        datetime(2030, 5, 14, 21, 14, tzinfo=UTC),
    ),
]
PHYSICIAN_TZ = {p.id: p.tz for p in ON_SHIFT}

# Off-shift roster: retained for later phases (eligibility is NOT computed here).
OFF_SHIFT = [
    (
        "DEV-P07",
        "Dr. Gray Sample",
        "day",
        "yes",
        "2030-05-13T20:00:00-04:00",
        "2030-05-15T08:00:00-04:00",
        36,
        15,
        "app_push",
        1,
        ["DEV-H02", "DEV-H05"],
    ),
    (
        "DEV-P08",
        "Dr. Harper Sample",
        "night",
        "yes",
        "2030-05-14T07:00:00-04:00",
        "2030-05-14T19:00:00-04:00",
        48,
        0,
        "sms",
        2,
        ["DEV-H01", "DEV-H04"],
    ),
    (
        "DEV-P09",
        "Dr. Indigo Sample",
        "float",
        "no",
        "2030-05-13T22:00:00-05:00",
        "2030-05-16T07:00:00-05:00",
        24,
        10,
        "app_push",
        0,
        ["DEV-H01", "DEV-H02", "DEV-H03"],
    ),
    (
        "DEV-P10",
        "Dr. Jordan Sample",
        "float",
        "yes",
        "2030-05-13T19:00:00-07:00",
        "2030-05-15T07:00:00-07:00",
        58,
        30,
        "sms",
        4,
        ["DEV-H05"],
    ),
]


@dataclass
class Row:
    event_type: str
    at: datetime
    ingested: datetime
    tz: str
    consult: str = ""
    physician: str = ""
    hospital: str = ""
    description: str = ""
    consult_type: str = ""
    duplicate_of: Row | None = None
    raw_event_time: str | None = None
    event_id: str = field(default="")


class Stream:
    def __init__(self, rng: random.Random) -> None:
        self.rng = rng
        self.rows: list[Row] = []

    def add(
        self,
        event_type: str,
        at: datetime,
        *,
        ingested: datetime | None = None,
        consult: str = "",
        physician: str = "",
        hospital: str = "",
        description: str = "",
        consult_type: str = "",
        tz: str | None = None,
    ) -> Row:
        zone = tz or HOSPITAL_TZ.get(hospital) or PHYSICIAN_TZ.get(physician) or "UTC"
        lag = timedelta(seconds=round(self.rng.uniform(1, 4)))
        row = Row(
            event_type,
            at,
            ingested or at + lag,
            zone,
            consult,
            physician,
            hospital,
            description,
            consult_type,
        )
        self.rows.append(row)
        return row

    def duplicate(self, row: Row, ingested: datetime) -> None:
        self.rows.append(
            Row(
                row.event_type,
                row.at,
                ingested,
                row.tz,
                row.consult,
                row.physician,
                row.hospital,
                row.description,
                row.consult_type,
                duplicate_of=row,
            )
        )


def _m(base: datetime, minutes: float) -> datetime:
    return base + timedelta(seconds=round(minutes * 60))


def stroke_flow(s: Stream, cid: str, pid: str, hid: str, t0: datetime) -> None:
    s.add(
        "consult_received",
        t0,
        consult=cid,
        hospital=hid,
        consult_type="Stroke",
        description="Stroke consult request received",
    )
    s.add("consult_triaged", _m(t0, 2), consult=cid, hospital=hid, description="Consult triaged")
    s.add(
        "physician_assigned",
        _m(t0, 3.5),
        consult=cid,
        physician=pid,
        hospital=hid,
        description="Consult assigned",
    )
    s.add(
        "incoming_call_started",
        _m(t0, 4.5),
        consult=cid,
        physician=pid,
        hospital=hid,
        description="Hospital calls assigned physician",
    )
    s.add("imaging_requested", _m(t0, 6), consult=cid, hospital=hid, description="CT/CTA requested")
    s.add(
        "incoming_call_ended",
        _m(t0, 9.5),
        consult=cid,
        physician=pid,
        hospital=hid,
        description="Call ends",
    )
    s.add("imaging_returned", _m(t0, 18), consult=cid, hospital=hid, description="Imaging returned")
    s.add("camera_active", _m(t0, 24.5), physician=pid, description="Desktop agent: camera active")
    s.add(
        "video_started",
        _m(t0, 24.5),
        consult=cid,
        physician=pid,
        hospital=hid,
        description="Video consult begins",
    )
    s.add(
        "video_ended",
        _m(t0, 36.5),
        consult=cid,
        physician=pid,
        hospital=hid,
        description="Video consult completed",
    )
    s.add(
        "camera_inactive", _m(t0, 36.6), physician=pid, description="Desktop agent: camera inactive"
    )
    s.add(
        "note_started",
        _m(t0, 42),
        consult=cid,
        physician=pid,
        hospital=hid,
        description="Note started",
    )
    s.add(
        "note_signed",
        _m(t0, 55),
        consult=cid,
        physician=pid,
        hospital=hid,
        description="Note signed",
    )


def neuro_flow(s: Stream, cid: str, pid: str, hid: str, t0: datetime) -> None:
    s.add(
        "consult_received",
        t0,
        consult=cid,
        hospital=hid,
        consult_type="General Neuro",
        description="General Neuro consult request received",
    )
    s.add("consult_triaged", _m(t0, 3), consult=cid, hospital=hid, description="Consult triaged")
    s.add(
        "physician_assigned",
        _m(t0, 5),
        consult=cid,
        physician=pid,
        hospital=hid,
        description="Consult assigned",
    )
    s.add(
        "incoming_call_started",
        _m(t0, 7),
        consult=cid,
        physician=pid,
        hospital=hid,
        description="Hospital calls assigned physician",
    )
    s.add(
        "incoming_call_ended",
        _m(t0, 19),
        consult=cid,
        physician=pid,
        hospital=hid,
        description="Call ends",
    )
    s.add(
        "note_started",
        _m(t0, 26),
        consult=cid,
        physician=pid,
        hospital=hid,
        description="Note started",
    )
    s.add(
        "note_signed",
        _m(t0, 38),
        consult=cid,
        physician=pid,
        hospital=hid,
        description="Note signed",
    )


def shift_window(p: OnShift) -> tuple[datetime, datetime]:
    zone = ZoneInfo(p.tz)
    start = datetime.combine(DAY, datetime.strptime(p.start, "%H:%M").time(), tzinfo=zone)
    end = datetime.combine(DAY, datetime.strptime(p.end, "%H:%M").time(), tzinfo=zone)
    return start, end


def build(rng: random.Random):
    s = Stream(rng)
    background: dict[str, int] = {}

    # Shift starts and opening status (status read from description: documented fallback).
    for p in ON_SHIFT:
        start, _ = shift_window(p)
        s.add(
            "shift_started",
            _m(start, rng.randint(0, 3)),
            physician=p.id,
            description="Shift started",
        )
        s.add(
            "physician_status_changed",
            _m(start, 4),
            physician=p.id,
            description="Self-reported status: Available",
        )

    # Background consults: seeded, all signed off well before the reference time.
    planned = []
    for p in ON_SHIFT:
        start, _ = shift_window(p)
        t0 = _m(start.astimezone(UTC), 25)
        wanted = rng.randint(3, 5)
        count = 0
        while count < wanted and _m(t0, 55) <= min(
            p.story_start - timedelta(minutes=10), REF - timedelta(minutes=10)
        ):
            planned.append((t0, p, rng.random() < 0.6, rng.choice(p.creds)))
            count += 1
            t0 = _m(t0, rng.randint(55, 75))
        background[p.id] = count
    for n, (t0, p, is_stroke, hid) in enumerate(
        sorted(planned, key=lambda x: (x[0], x[1].id)), start=1
    ):
        (stroke_flow if is_stroke else neuro_flow)(s, f"DEV-C{n:03d}", p.id, hid, t0)

    at = lambda h, m, sec=0: datetime(2030, 5, 14, h, m, sec, tzinfo=UTC)  # noqa: E731

    # P01: three open consults in three different stages; one late video_started.
    s.add(
        "consult_received",
        at(19, 50),
        consult="DEV-C103",
        hospital="DEV-H03",
        consult_type="General Neuro",
        description="General Neuro consult request received",
    )
    s.add(
        "consult_triaged",
        at(19, 53),
        consult="DEV-C103",
        hospital="DEV-H03",
        description="Consult triaged",
    )
    s.add(
        "physician_assigned",
        at(19, 55),
        consult="DEV-C103",
        physician="DEV-P01",
        hospital="DEV-H03",
    )
    s.add(
        "incoming_call_started",
        at(19, 57),
        consult="DEV-C103",
        physician="DEV-P01",
        hospital="DEV-H03",
    )
    s.add(
        "incoming_call_ended",
        at(20, 10),
        consult="DEV-C103",
        physician="DEV-P01",
        hospital="DEV-H03",
        description="Call ends; note not started",
    )
    s.add(
        "consult_received",
        at(20, 40),
        consult="DEV-C101",
        hospital="DEV-H01",
        consult_type="Stroke",
        description="Stroke consult request received",
    )
    s.add("consult_triaged", at(20, 42), consult="DEV-C101", hospital="DEV-H01")
    s.add(
        "physician_assigned",
        at(20, 43, 30),
        consult="DEV-C101",
        physician="DEV-P01",
        hospital="DEV-H01",
    )
    s.add(
        "incoming_call_started",
        at(20, 44, 30),
        consult="DEV-C101",
        physician="DEV-P01",
        hospital="DEV-H01",
    )
    s.add("imaging_requested", at(20, 46), consult="DEV-C101", hospital="DEV-H01")
    s.add(
        "incoming_call_ended",
        at(20, 49),
        consult="DEV-C101",
        physician="DEV-P01",
        hospital="DEV-H01",
    )
    s.add("imaging_returned", at(21, 4), consult="DEV-C101", hospital="DEV-H01")
    s.add(
        "consult_received",
        at(21, 0),
        consult="DEV-C102",
        hospital="DEV-H02",
        consult_type="Stroke",
        description="Stroke consult request received",
    )
    s.add("consult_triaged", at(21, 2), consult="DEV-C102", hospital="DEV-H02")
    s.add(
        "physician_assigned", at(21, 3), consult="DEV-C102", physician="DEV-P01", hospital="DEV-H02"
    )
    s.add(
        "outgoing_call_started",
        at(21, 4),
        consult="DEV-C102",
        physician="DEV-P01",
        hospital="DEV-H02",
        description="Provider calls hospital",
    )
    s.add("imaging_requested", at(21, 5, 30), consult="DEV-C102", hospital="DEV-H02")
    s.add(
        "outgoing_call_ended",
        at(21, 7),
        consult="DEV-C102",
        physician="DEV-P01",
        hospital="DEV-H02",
    )
    s.add(
        "camera_active", at(21, 12), physician="DEV-P01", description="Desktop agent: camera active"
    )
    s.add(
        "video_started",
        at(21, 12),
        ingested=at(21, 19, 30),
        consult="DEV-C101",
        physician="DEV-P01",
        hospital="DEV-H01",
        description="Video consult begins (arrives 7.5 min late)",
    )

    # P02: active call with camera on; a duplicate of the call-start event.
    s.add(
        "consult_received",
        at(20, 30),
        consult="DEV-C105",
        hospital="DEV-H05",
        consult_type="General Neuro",
        description="General Neuro consult request received",
    )
    s.add("consult_triaged", at(20, 33), consult="DEV-C105", hospital="DEV-H05")
    s.add(
        "physician_assigned",
        at(20, 35),
        consult="DEV-C105",
        physician="DEV-P02",
        hospital="DEV-H05",
    )
    s.add(
        "incoming_call_started",
        at(20, 37),
        consult="DEV-C105",
        physician="DEV-P02",
        hospital="DEV-H05",
    )
    s.add(
        "incoming_call_ended",
        at(20, 55),
        consult="DEV-C105",
        physician="DEV-P02",
        hospital="DEV-H05",
    )
    s.add("note_started", at(21, 10), consult="DEV-C105", physician="DEV-P02", hospital="DEV-H05")
    s.add(
        "consult_received",
        at(21, 20),
        consult="DEV-C104",
        hospital="DEV-H04",
        consult_type="Stroke",
        description="Stroke consult request received",
    )
    s.add("consult_triaged", at(21, 22), consult="DEV-C104", hospital="DEV-H04")
    s.add(
        "physician_assigned",
        at(21, 23, 30),
        consult="DEV-C104",
        physician="DEV-P02",
        hospital="DEV-H04",
    )
    call = s.add(
        "incoming_call_started",
        at(21, 25),
        ingested=at(21, 25, 2),
        consult="DEV-C104",
        physician="DEV-P02",
        hospital="DEV-H04",
        description="Hospital calls assigned physician",
    )
    s.duplicate(call, ingested=at(21, 25, 9))
    s.add("camera_active", at(21, 25, 30), physician="DEV-P02")

    # P03: camera on with no Synapse session; an older camera_inactive arrives last.
    s.add(
        "consult_received",
        at(20, 0),
        consult="DEV-C106",
        hospital="DEV-H02",
        consult_type="General Neuro",
        description="General Neuro consult request received",
    )
    s.add("consult_triaged", at(20, 2), consult="DEV-C106", hospital="DEV-H02")
    s.add(
        "physician_assigned", at(20, 4), consult="DEV-C106", physician="DEV-P03", hospital="DEV-H02"
    )
    s.add(
        "outgoing_call_started",
        at(20, 6),
        consult="DEV-C106",
        physician="DEV-P03",
        hospital="DEV-H02",
    )
    s.add(
        "outgoing_call_ended",
        at(20, 20),
        consult="DEV-C106",
        physician="DEV-P03",
        hospital="DEV-H02",
    )
    s.add("camera_active", at(20, 25), physician="DEV-P03")
    s.add(
        "camera_inactive",
        at(20, 31),
        ingested=at(21, 21),
        physician="DEV-P03",
        description="Desktop agent: camera inactive (arrives 50 min late)",
    )
    s.add("camera_active", at(21, 18), physician="DEV-P03")

    # P04: In Meeting + camera; the two events arrive in the opposite order to occurrence.
    s.add(
        "physician_status_changed",
        at(21, 5),
        ingested=at(21, 6, 40),
        physician="DEV-P04",
        description="Self-reported status: In Meeting",
    )
    s.add("camera_active", at(21, 4, 30), ingested=at(21, 7, 10), physician="DEV-P04")
    s.add(
        "sample_unrecognized_event",
        at(20, 45),
        physician="DEV-P04",
        description="Intentionally undocumented event type (tests unknown-type reporting)",
    )
    bad = s.add(
        "camera_inactive",
        at(20, 50),
        physician="DEV-P04",
        description="Intentionally malformed row: event_time has no UTC offset",
    )
    bad.raw_event_time = "2030-05-14 16:50:00"

    # P05: desktop agent offline; a hospital call is ringing.
    s.add(
        "agent_heartbeat_lost",
        at(21, 0),
        physician="DEV-P05",
        description="Desktop agent heartbeat lost",
    )
    s.add(
        "consult_received",
        at(21, 27),
        consult="DEV-C107",
        hospital="DEV-H05",
        consult_type="General Neuro",
        description="General Neuro consult request received",
    )
    s.add("consult_triaged", at(21, 28, 30), consult="DEV-C107", hospital="DEV-H05")
    s.add(
        "incoming_call_ringing",
        at(21, 29, 30),
        consult="DEV-C107",
        physician="DEV-P05",
        hospital="DEV-H05",
        description="Hospital call ringing; not yet answered",
    )

    # P06: temporarily unavailable with a stroke consult still assigned.
    s.add(
        "consult_received",
        at(21, 14),
        consult="DEV-C108",
        hospital="DEV-H03",
        consult_type="Stroke",
        description="Stroke consult request received",
    )
    s.add("consult_triaged", at(21, 16), consult="DEV-C108", hospital="DEV-H03")
    s.add(
        "physician_assigned",
        at(21, 18),
        consult="DEV-C108",
        physician="DEV-P06",
        hospital="DEV-H03",
    )
    s.add(
        "physician_status_changed",
        at(21, 20),
        physician="DEV-P06",
        description="Self-reported status: Temporarily Unavailable",
    )

    # Unassigned consults: repeated routing failures, and one just received.
    received = s.add(
        "consult_received",
        at(21, 15),
        ingested=at(21, 15, 2),
        consult="DEV-C109",
        hospital="DEV-H05",
        consult_type="Stroke",
        description="Stroke consult request received",
    )
    s.duplicate(received, ingested=at(21, 15, 30))
    s.add("consult_triaged", at(21, 17), consult="DEV-C109", hospital="DEV-H05")
    for minute in (18, 23, 28):
        s.add(
            "routing_attempt_failed",
            at(21, minute),
            consult="DEV-C109",
            hospital="DEV-H05",
            description="No available credentialed provider; retry scheduled",
        )
    s.add(
        "consult_received",
        at(21, 29, 10),
        consult="DEV-C110",
        hospital="DEV-H01",
        consult_type="General Neuro",
        description="General Neuro consult request received",
    )

    # Ingested after the reference time: revealed by advancing the clock.
    s.add(
        "physician_assigned",
        at(21, 30, 45),
        consult="DEV-C107",
        physician="DEV-P05",
        hospital="DEV-H05",
    )
    s.add(
        "incoming_call_started",
        at(21, 31),
        consult="DEV-C107",
        physician="DEV-P05",
        hospital="DEV-H05",
    )
    s.add("consult_triaged", at(21, 31, 30), consult="DEV-C110", hospital="DEV-H01")
    s.add(
        "physician_status_changed",
        at(21, 32, 30),
        physician="DEV-P04",
        description="Self-reported status: Available",
    )
    s.add("camera_inactive", at(21, 32, 35), physician="DEV-P04")
    s.add(
        "physician_assigned",
        at(21, 33),
        consult="DEV-C109",
        physician="DEV-P04",
        hospital="DEV-H05",
    )
    s.add("video_ended", at(21, 36), consult="DEV-C101", physician="DEV-P01", hospital="DEV-H01")
    s.add("camera_inactive", at(21, 36, 5), physician="DEV-P01")
    s.add(
        "incoming_call_ended",
        at(21, 38),
        consult="DEV-C104",
        physician="DEV-P02",
        hospital="DEV-H04",
    )
    s.add("camera_inactive", at(21, 38, 20), physician="DEV-P02")

    # Stream order is by ingested_at (as documented); ids follow that order.
    s.rows.sort(key=lambda r: (r.ingested, r.at, r.event_type, r.consult, r.physician))
    n = 0
    for row in s.rows:
        if row.duplicate_of is None:
            n += 1
            row.event_id = f"DEV-E{n:05d}"
    for row in s.rows:
        if row.duplicate_of is not None:
            row.event_id = row.duplicate_of.event_id
    return s.rows, background


# Expected state at REF, written from the scenario above (not computed by the engine).
STORY_EXPECTED_PHYSICIANS = {
    # id: (derived state label, extra consults, extra calls, open consults)
    "DEV-P01": ("Video Consult In Progress", 3, 3, 3),
    "DEV-P02": ("Incoming Hospital Call", 2, 2, 2),
    "DEV-P03": ("Camera Active - No Synapse Session", 1, 1, 1),
    "DEV-P04": ("In Meeting", 0, 0, 0),
    "DEV-P05": ("Available", 0, 0, 0),
    "DEV-P06": ("Temporarily Unavailable", 1, 0, 1),
}
EXPECTED_CONSULTS = [
    # consult, hospital, physician, type, stage label, entered (UTC h, m, s)
    ("DEV-C101", "DEV-H01", "DEV-P01", "Stroke", "Video Consult In Progress", (21, 12, 0)),
    ("DEV-C102", "DEV-H02", "DEV-P01", "Stroke", "CT/CTA or Imaging Pending", (21, 5, 30)),
    ("DEV-C103", "DEV-H03", "DEV-P01", "General Neuro", "Note Pending", (20, 10, 0)),
    ("DEV-C104", "DEV-H04", "DEV-P02", "Stroke", "Provider Contacted", (21, 25, 0)),
    ("DEV-C105", "DEV-H05", "DEV-P02", "General Neuro", "Documentation", (21, 10, 0)),
    ("DEV-C106", "DEV-H02", "DEV-P03", "General Neuro", "Note Pending", (20, 20, 0)),
    ("DEV-C107", "DEV-H05", "Unassigned", "General Neuro", "Triaged", (21, 28, 30)),
    ("DEV-C108", "DEV-H03", "DEV-P06", "Stroke", "Assigned", (21, 18, 0)),
    ("DEV-C109", "DEV-H05", "Unassigned", "Stroke", "Triaged", (21, 17, 0)),
    ("DEV-C110", "DEV-H01", "Unassigned", "General Neuro", "Received", (21, 29, 10)),
]


def _write(path: Path, header: list[str], rows: list[list[object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def write_dataset(out: Path) -> None:
    rng = random.Random(SEED)
    out.mkdir(parents=True, exist_ok=True)
    rows, background = build(rng)

    def local(moment: datetime, tz: str) -> str:
        return moment.astimezone(ZoneInfo(tz)).isoformat(timespec="seconds")

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
                r.event_id,
                r.raw_event_time or local(r.at, r.tz),
                r.ingested.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                r.consult,
                r.event_type,
                r.physician,
                r.hospital,
                r.description,
                r.consult_type,
            ]
            for r in rows
        ],
    )
    _write(
        out / "hospitals.csv",
        ["hospital_id", "name", "timezone", "coverage_tier"],
        [list(h) for h in HOSPITALS],
    )
    _write(
        out / "physicians_on_shift.csv",
        ["physician_id", "name", "shift_start", "shift_end", "role"],
        [
            [p.id, p.name, *(t.isoformat(timespec="seconds") for t in shift_window(p)), "day"]
            for p in ON_SHIFT
        ],
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
    hospital_ids = [h[0] for h in HOSPITALS]
    creds = {p.id: (p.name, p.creds) for p in ON_SHIFT} | {r[0]: (r[1], r[10]) for r in OFF_SHIFT}
    _write(
        out / "credentialing_matrix.csv",
        ["physician_id", "physician_name", *hospital_ids],
        [
            [pid, name, *("Y" if h in hs else "" for h in hospital_ids)]
            for pid, (name, hs) in sorted(creds.items())
        ],
    )
    profile = [
        0.3,
        0.2,
        0.2,
        0.2,
        0.3,
        0.4,
        0.6,
        0.9,
        1.2,
        1.4,
        1.5,
        1.5,
        1.4,
        1.4,
        1.5,
        1.5,
        1.4,
        1.3,
        1.1,
        0.9,
        0.8,
        0.6,
        0.5,
        0.4,
    ]
    baseline = []
    for hid, _, _, tier in HOSPITALS:
        scale = rng.uniform(0.6, 1.4) * (1.3 if tier == "comprehensive" else 1.0)
        for hour, weight in enumerate(profile):
            mean = round(weight * scale, 2)
            baseline.append(
                [hid, hour, mean, round(mean * rng.uniform(1.8, 2.4) + 0.5, 1), "weekday"]
            )
    _write(
        out / "baseline_hourly_volume.csv",
        ["hospital_id", "hour", "mean", "p90", "day_type"],
        baseline,
    )
    coverage = []
    for hid, _, _, tier in HOSPITALS:
        coverage.append([hid, "07:00", "19:00", 2 if tier == "comprehensive" else 1])
        coverage.append([hid, "19:00", "07:00", 1])
    _write(
        out / "coverage_requirements.csv",
        ["hospital_id", "block_start", "block_end", "min_available_physicians"],
        coverage,
    )

    _write(
        out / "snapshot_physicians_ref.csv",
        ["physician_id", "derived_state", "consults", "calls", "open_consults"],
        [
            [pid, label, background[pid] + extra_c, background[pid] + extra_calls, open_n]
            for pid, (label, extra_c, extra_calls, open_n) in STORY_EXPECTED_PHYSICIANS.items()
        ],
    )
    _write(
        out / "snapshot_consults_ref.csv",
        ["consult_id", "hospital_id", "physician_id", "consult_type", "stage", "minutes_in_stage"],
        [
            [
                cid,
                hid,
                pid,
                ctype,
                stage,
                int((REF - datetime(2030, 5, 14, *hms, tzinfo=UTC)).total_seconds() // 60),
            ]
            for cid, hid, pid, ctype, stage, hms in EXPECTED_CONSULTS
        ],
    )
    (out / "dataset_manifest.json").write_text(
        json.dumps(
            {
                "label": LABEL,
                "synthetic": True,
                "reference_time": REF.astimezone(ZoneInfo("America/New_York")).isoformat(),
                "generator": "backend/scripts/generate_sample_dataset.py",
                "seed": SEED,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else OUTPUT
    write_dataset(target)
    print(f"Wrote SYNTHETIC SAMPLE DATA to {target}")
