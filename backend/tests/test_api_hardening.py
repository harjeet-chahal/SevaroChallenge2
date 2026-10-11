"""Hostile or malformed input must give a 4xx with the standard error envelope (or a
row rejection), never a 500: over-long IDs, out-of-range timestamps, bad demo headers,
corrupt ZIPs, upload-wide expansion limits and an out-of-range clock / ``as_of``."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.services.dataset_import.sources import SourceError, SourceLimits, collect_files
from tests.conftest import sample_files, upload, zip_bytes

LONG_ID = "X" * 129
EVENT_HEADER = (
    "event_id,event_time,ingested_at,consult_id,event_type,physician_id,hospital_id,description"
)
OUT_OF_RANGE_TIMES = [
    "0001-01-01T00:00:00+05:00",  # no UTC equivalent (OverflowError before the fix)
    "9999-12-31T23:00:00-05:00",  # likewise, at the other end
    "1899-12-31T23:59:59Z",
    "2201-01-01T00:00:00Z",
]
COORDINATOR = {"X-Demo-Role": "coordinator"}


def _error(response) -> dict:
    body = response.json()
    assert set(body) == {"error"}, body
    return body["error"]


def _issues(response, code: str) -> list[dict]:
    return [i for i in _error(response)["details"]["issues"] if i["code"] == code]


def _event(**overrides) -> dict:
    return {
        "event_id": "HARD-E1",
        "event_type": "consult_received",
        "event_time": "2030-05-14T17:29:00-04:00",
        "consult_id": "HARD-C1",
        "hospital_id": "DEV-H01",
        "description": "Stroke consult request received",
        **overrides,
    }


def _csv(*rows: str) -> bytes:
    return "\n".join([EVENT_HEADER, *rows, ""]).encode()


# 1. IDs longer than 128 characters -----------------------------------------------------


@pytest.mark.parametrize("field", ["event_id", "consult_id", "hospital_id"])
def test_json_event_with_overlong_id_is_rejected(loaded_client, field):
    response = loaded_client.post("/api/events", json=_event(**{field: LONG_ID}))

    assert response.status_code == 422, response.text
    outcome = _error(response)["details"]["outcomes"][0]
    assert outcome["status"] == "rejected"
    assert [e["field"] for e in outcome["errors"]] == [field]
    assert "128 characters" in outcome["errors"][0]["message"]


def test_csv_append_rejects_overlong_id_row_and_keeps_the_rest(loaded_client):
    data = _csv(
        "HARD-E2,2030-05-14T17:29:00-04:00,2030-05-14T17:29:02-04:00,HARD-C2,consult_received,,"
        "DEV-H01,Stroke consult request received",
        f"HARD-E3,2030-05-14T17:29:00-04:00,2030-05-14T17:29:02-04:00,{LONG_ID},consult_received,,"
        "DEV-H01,Stroke consult request received",
    )
    response = loaded_client.post("/api/events/csv", files={"file": ("e.csv", data)})

    assert response.status_code == 201, response.text
    body = response.json()
    assert (body["accepted"], body["rejected"]) == (1, 1)
    rejected = next(o for o in body["outcomes"] if o["status"] == "rejected")
    assert rejected["errors"][0]["field"] == "consult_id"


def test_import_drops_event_row_with_overlong_id(client):
    files = sample_files()
    files["event_stream.csv"] += (
        f"HARD-E4,2030-05-14T17:00:00-04:00,2030-05-14T21:00:01Z,{LONG_ID},consult_received,,"
        "DEV-H01,Stroke consult request received,Stroke\n"
    ).encode()
    response = upload(client, files)

    assert response.status_code == 200, response.text
    assert response.json()["counts"]["events_rejected"] == 2  # the sample's own bad row + ours


@pytest.mark.parametrize(
    ("file", "old", "label"),
    [
        ("hospitals.csv", b"DEV-H05,", "hospital_id"),
        ("physicians_on_shift.csv", b"DEV-P01,", "physician_id"),
        ("physicians_off_shift_roster.csv", b"DEV-P07,", "physician_id"),
    ],
)
def test_import_with_overlong_reference_id_fails_with_a_report(client, file, old, label):
    files = sample_files()
    files[file] = files[file].replace(old, LONG_ID.encode() + b",", 1)
    response = upload(client, files)

    assert response.status_code == 422, response.text
    [issue] = _issues(response, "invalid_id")
    assert issue["column"] == label and issue["file"] == file
    attempt = client.get("/api/datasets/status").json()["last_attempt"]
    assert attempt is not None and attempt["status"] == "failed"


def test_reference_row_schema_violation_is_a_row_error(client):
    files = sample_files()
    roster = files["physicians_off_shift_roster.csv"].decode().splitlines()
    cells = roster[1].split(",")
    cells[6] = "nan"  # hours_worked_7d: passes the number parser, fails the schema (>= 0)
    roster[1] = ",".join(cells)
    files["physicians_off_shift_roster.csv"] = ("\n".join(roster) + "\n").encode()
    response = upload(client, files)

    assert response.status_code == 422, response.text
    [issue] = _issues(response, "invalid_row")
    assert "hours_worked_trailing_7d" in issue["message"]


# 2. Out-of-range timestamps --------------------------------------------------------------


@pytest.mark.parametrize("moment", OUT_OF_RANGE_TIMES)
def test_out_of_range_event_time_is_a_field_error(loaded_client, moment):
    response = loaded_client.post("/api/events", json=_event(event_time=moment))

    assert response.status_code == 422, response.text
    [error] = _error(response)["details"]["outcomes"][0]["errors"]
    assert error["field"] == "event_time"
    assert "supported range" in error["message"]


@pytest.mark.parametrize("moment", OUT_OF_RANGE_TIMES[:2])
def test_out_of_range_ingested_at_in_csv_is_a_row_rejection(loaded_client, moment):
    data = _csv(
        f"HARD-E5,2030-05-14T17:29:00-04:00,{moment},HARD-C5,consult_received,,DEV-H01,Stroke"
    )
    response = loaded_client.post("/api/events/csv", files={"file": ("e.csv", data)})

    assert response.status_code == 422, response.text
    [outcome] = _error(response)["details"]["outcomes"]
    assert outcome["errors"][0]["field"] == "ingested_at"


def test_out_of_range_roster_time_fails_the_import(client):
    files = sample_files()
    files["physicians_off_shift_roster.csv"] = files["physicians_off_shift_roster.csv"].replace(
        b"2030-05-13T20:00:00-04:00", b"0001-01-01T00:00:00+05:00", 1
    )
    response = upload(client, files)

    assert response.status_code == 422, response.text
    [issue] = _issues(response, "invalid_datetime")
    assert "supported range" in issue["message"]


def test_out_of_range_import_reference_time_fails_with_a_report(client):
    response = upload(client, sample_files(), reference_time="9999-12-31T23:00:00-05:00")

    assert response.status_code == 422, response.text
    assert _issues(response, "reference_time_invalid")


# 3. X-Demo-Actor-Id ------------------------------------------------------------------------


@pytest.mark.parametrize("actor_id", ["", "   ", "A" * 200])
def test_bad_actor_header_is_a_422(loaded_client, actor_id):
    for path, role in [("/api/interventions", "coordinator"), ("/api/offers/mine", "physician")]:
        response = loaded_client.get(
            path, headers={"X-Demo-Role": role, "X-Demo-Actor-Id": actor_id}
        )
        assert response.status_code == 422, response.text
        assert _error(response)["code"] == "actor_id_invalid"


def test_absent_or_valid_actor_header_still_works(loaded_client):
    assert loaded_client.get("/api/interventions", headers=COORDINATOR).status_code == 200
    response = loaded_client.get(
        "/api/offers/mine", headers={"X-Demo-Role": "physician", "X-Demo-Actor-Id": "DEV-P07"}
    )
    assert response.status_code == 200, response.text


# 4. Corrupt / encrypted / unsupported ZIPs ---------------------------------------------


def _stored_zip() -> bytearray:
    return bytearray(zip_bytes(sample_files()))  # ZIP_STORED: file bytes appear verbatim


def _patch_headers(data: bytearray, *, local: int, central: int, value: int, size: int) -> None:
    """Set a field in every local (PK\\3\\4) and central (PK\\1\\2) header."""
    for signature, offset in ((b"PK\x03\x04", local), (b"PK\x01\x02", central)):
        start = 0
        while (start := data.find(signature, start)) >= 0:
            data[start + offset : start + offset + size] = value.to_bytes(size, "little")
            start += 4


def _corrupt_crc() -> bytes:
    data = _stored_zip()
    index = data.find(b"hospital_id,name")
    data[index + 5] ^= 0x01
    return bytes(data)


def _encrypted_flag() -> bytes:
    data = _stored_zip()
    _patch_headers(data, local=6, central=8, value=0x1, size=2)
    return bytes(data)


def _unsupported_method() -> bytes:
    data = _stored_zip()
    _patch_headers(data, local=8, central=10, value=99, size=2)  # 99 = AES, unsupported
    return bytes(data)


@pytest.mark.parametrize(
    ("make", "code"),
    [
        (_corrupt_crc, "archive_unreadable"),
        (_encrypted_flag, "archive_encrypted"),
        (_unsupported_method, "archive_unreadable"),
        (lambda: zip_bytes(sample_files())[:-30], "archive_invalid"),
    ],
)
def test_unreadable_zip_is_a_422_with_a_report(client, make, code):
    response = upload(client, {"dataset.zip": make()})

    assert response.status_code == 422, response.text
    assert _error(response)["code"] == "dataset_invalid"
    assert _issues(response, code)
    assert client.get("/api/datasets/status").json()["last_attempt"]["status"] == "failed"


# 5. Upload-wide expansion limits -------------------------------------------------------


def test_uncompressed_limit_spans_all_archives_in_an_upload(make_client):
    files = sample_files()
    events = {"event_stream.csv": files.pop("event_stream.csv")}
    first, second = zip_bytes(events), zip_bytes(files)
    total = sum(len(v) for v in sample_files().values())
    limit = total - 1000  # each archive alone fits; together they do not
    assert max(len(v) for v in events.values()) < limit

    with make_client(max_uncompressed_bytes=limit) as small:
        response = upload(small, {"a.zip": first, "b.zip": second})

    assert response.status_code == 422, response.text
    assert _issues(response, "archive_too_large")


def test_upload_limits_are_shared_by_archives_and_plain_files():
    limits = SourceLimits(
        max_upload_bytes=10**6, max_uncompressed_bytes=10_000, max_archive_entries=3
    )
    part = zip_bytes({"a.csv": b"0" * 4_000})

    with pytest.raises(SourceError) as size:
        collect_files([("1.zip", part), ("2.zip", part), ("plain.csv", b"0" * 4_000)], limits)
    assert size.value.issues[0].code == "archive_too_large"

    two = zip_bytes({"a.csv": b"a", "b.csv": b"b"})
    with pytest.raises(SourceError) as entries:
        collect_files([("1.zip", two), ("2.zip", two)], limits)
    assert entries.value.issues[0].code == "archive_too_many_entries"

    assert len(collect_files([("1.zip", part), ("plain.csv", b"0" * 4_000)], limits)) == 2


# 6. Simulation clock and as_of -------------------------------------------------------------


@pytest.mark.parametrize("moment", ["9999-12-31T23:59:59Z", "9999-12-31T23:59:59-05:00"])
def test_extreme_clock_time_is_refused_and_analysis_keeps_working(loaded_client, moment):
    response = loaded_client.post("/api/simulation/time", json={"time": moment})

    assert response.status_code == 422, response.text
    assert _error(response)["code"] == "validation_error"
    for path in ["/api/alerts", "/api/coverage", "/api/optimization/split-shifts"]:
        assert loaded_client.get(path).status_code == 200, path
    assert loaded_client.post("/api/simulation/advance", json={"minutes": 5}).status_code == 200


def test_clock_must_stay_within_a_year_of_the_dataset(loaded_client):
    response = loaded_client.post("/api/simulation/time", json={"time": "2040-01-01T00:00:00Z"})

    assert response.status_code == 422, response.text
    error = _error(response)
    assert error["code"] == "simulation_time_out_of_range"
    assert {"earliest", "latest"} <= set(error["details"])

    # Advancing past the window is refused too; the clock stays where it was.
    latest = datetime.fromisoformat(error["details"]["latest"])
    edge = (latest - timedelta(days=1)).isoformat()
    assert loaded_client.post("/api/simulation/time", json={"time": edge}).status_code == 200
    response = loaded_client.post("/api/simulation/advance", json={"minutes": 3 * 24 * 60})
    assert response.status_code == 422, response.text
    assert _error(response)["code"] == "simulation_time_out_of_range"
    current = loaded_client.get("/api/simulation").json()["current_time"]
    assert datetime.fromisoformat(current) == datetime.fromisoformat(edge)

    assert loaded_client.post("/api/simulation/reset").status_code == 200


AS_OF_PATHS = [
    "/api/state",
    "/api/physicians",
    "/api/consultations",
    "/api/alerts",
    "/api/coverage",
    "/api/demand",
    "/api/metrics",
    "/api/optimization/input",
    "/api/optimization/assignments",
    "/api/optimization/split-shifts",
    "/api/optimization/comparison",
    "/api/events",
]


@pytest.mark.parametrize("moment", ["0001-01-01T00:00:00Z", "9999-12-31T23:59:59Z"])
def test_extreme_as_of_is_a_422_everywhere(loaded_client, moment):
    for path in AS_OF_PATHS:
        response = loaded_client.get(path, params={"as_of": moment})
        assert response.status_code == 422, (path, response.text)
        assert _error(response)["details"][0]["loc"] == ["query", "as_of"]

    response = loaded_client.post(
        "/api/optimization/simulate",
        json={"as_of": moment, "action": {"kind": "split_shift", "physician_id": "DEV-P07"}},
    )
    assert response.status_code == 422, response.text
    assert _error(response)["details"] == {"field": "as_of"}


def test_in_range_as_of_far_from_the_dataset_still_works(loaded_client):
    assert (
        loaded_client.get("/api/state", params={"as_of": "1970-01-01T00:00:00Z"}).status_code == 200
    )
