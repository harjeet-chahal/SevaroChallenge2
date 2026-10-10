"""Live injection, the simulation clock and state endpoints over HTTP."""

from __future__ import annotations

from tests.conftest import upload


def _physician(client, pid, **params):
    return client.get(f"/api/physicians/{pid}", params=params).json()


def _consult(client, cid, **params):
    return client.get(f"/api/consultations/{cid}", params=params).json()


def test_endpoints_require_a_dataset(client):
    response = client.get("/api/state")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_dataset"


# 14. Injected events affect operational state without restart ---------------------------


def test_injected_events_change_state_immediately(loaded_client):
    before = loaded_client.get("/api/state").json()["summary"]
    response = loaded_client.post(
        "/api/events",
        json=[
            {
                "event_id": "LIVE-1",
                "event_type": "consult_received",
                "event_time": "2030-05-14T14:29:30-07:00",
                "consult_id": "LIVE-C1",
                "hospital_id": "DEV-H05",
                "consult_type": "Stroke",
            },
            {
                "event_id": "LIVE-2",
                "event_type": "physician_status_changed",
                "event_time": "2030-05-14T17:29:40-04:00",
                "physician_id": "DEV-P06",
                "status": "Available",
            },
        ],
    )

    assert response.status_code == 201, response.text
    assert [o["status"] for o in response.json()["outcomes"]] == ["accepted", "accepted"]
    assert all(o["visible_now"] for o in response.json()["outcomes"])
    after = loaded_client.get("/api/state").json()["summary"]
    assert after["consults_open_unassigned"] == before["consults_open_unassigned"] + 1
    consult = _consult(loaded_client, "LIVE-C1")
    assert consult["stage"] == "received" and consult["hospital_name"] == "Harbor Sample General"
    assert _physician(loaded_client, "DEV-P06")["availability"] == "available"


def test_injected_duplicate_is_stored_but_not_double_counted(loaded_client):
    event = {
        "event_id": "LIVE-CALL",
        "event_type": "outgoing_call_started",
        "event_time": "2030-05-14T17:29:00-04:00",
        "physician_id": "DEV-P04",
        "consult_id": "DEV-C109",
        "hospital_id": "DEV-H05",
    }
    first = loaded_client.post("/api/events", json=event).json()
    second = loaded_client.post("/api/events", json=event).json()

    assert first["outcomes"][0]["status"] == "accepted"
    assert second["outcomes"][0]["status"] == "duplicate"
    p = _physician(loaded_client, "DEV-P04")
    assert p["calls_this_shift"] == 4  # 3 background + 1, not 2
    assert p["activity"] == "outgoing_call"


def test_injected_event_with_future_ingest_waits_for_the_clock(loaded_client):
    loaded_client.post(
        "/api/events",
        json={
            "event_id": "LIVE-LATER",
            "event_type": "agent_heartbeat_lost",
            "event_time": "2030-05-14T21:40:00Z",
            "ingested_at": "2030-05-14T21:40:02Z",
            "physician_id": "DEV-P03",
        },
    )
    assert _physician(loaded_client, "DEV-P03")["signals"]["agent_online"] is None

    loaded_client.post("/api/simulation/advance", json={"minutes": 11})
    assert _physician(loaded_client, "DEV-P03")["signals"]["agent_online"] is False


def test_csv_events_can_be_appended_in_dataset_format(loaded_client):
    csv = (
        "event_id,event_time,ingested_at,consult_id,event_type,physician_id,hospital_id,description\n"
        "CSV-1,2030-05-14T17:29:50-04:00,2030-05-14T21:29:52Z,CSV-C1,consult_received,,DEV-H02,"
        "Stroke consult request received\n"
    )
    response = loaded_client.post("/api/events/csv", files={"file": ("more.csv", csv.encode())})

    assert response.status_code == 201, response.text
    assert _consult(loaded_client, "CSV-C1")["consult_type"] == "Stroke"


# 11. Invalid event payload returns a descriptive error ---------------------------------


def test_invalid_payload_returns_field_level_errors_and_stores_nothing(loaded_client):
    before = loaded_client.get("/api/events", params={"limit": 1}).json()["total"]
    response = loaded_client.post(
        "/api/events",
        json=[
            {
                "event_id": "BAD-1",
                "event_type": "physician_status_changed",
                "event_time": "2030-05-14T21:29:00Z",
                "physician_id": "DEV-P01",
            },
            {
                "event_id": "BAD-2",
                "event_type": "video_started",
                "event_time": "2030-05-14T21:29:00Z",
                "physician_id": "DEV-P01",
            },
            {
                "event_id": "OK-3",
                "event_type": "camera_active",
                "event_time": "2030-05-14T21:29:00Z",
                "physician_id": "DEV-P01",
            },
        ],
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "event_invalid"
    outcomes = {o["event_id"]: o for o in error["details"]["outcomes"]}
    assert outcomes["BAD-1"]["errors"][0]["field"] == "status"
    assert "require consult_id" in outcomes["BAD-2"]["errors"][0]["message"]
    assert loaded_client.get("/api/events", params={"limit": 1}).json()["total"] == before
    assert loaded_client.get("/api/events/rejections").json()["total"] == 1 + 2


def test_unknown_status_label_lists_accepted_values(loaded_client):
    response = loaded_client.post(
        "/api/events",
        json={
            "event_id": "BAD-S",
            "event_type": "physician_status_changed",
            "event_time": "2030-05-14T21:29:00Z",
            "physician_id": "DEV-P01",
            "status": "Napping",
        },
    )

    message = response.json()["error"]["details"]["outcomes"][0]["errors"][0]["message"]
    assert "Napping" in message and "in_meeting" in message


def test_naive_injected_timestamp_is_rejected(loaded_client):
    response = loaded_client.post(
        "/api/events",
        json={
            "event_id": "NAIVE",
            "event_type": "camera_active",
            "event_time": "2030-05-14 17:29:00",
            "physician_id": "DEV-P01",
        },
    )

    assert response.status_code == 422
    assert "no UTC offset" in response.text


def test_unknown_event_type_is_stored_and_reported_not_applied(loaded_client):
    response = loaded_client.post(
        "/api/events",
        json={
            "event_id": "ODD-1",
            "event_type": "vendor_specific_ping",
            "event_time": "2030-05-14T21:29:00Z",
            "physician_id": "DEV-P01",
        },
    )

    assert response.status_code == 201
    warnings = response.json()["outcomes"][0]["warnings"]
    assert any("unknown event_type" in w for w in warnings)
    diagnostics = loaded_client.get("/api/state").json()["diagnostics"]
    assert diagnostics["unknown_event_types"]["vendor_specific_ping"] == 1


# 6. Clock control and state over time -------------------------------------------------


def test_clock_advance_reveals_future_events_and_reset_returns(loaded_client):
    clock = loaded_client.get("/api/simulation").json()
    assert clock["events_pending_ingestion"] == 10
    assert clock["server_time"] != clock["current_time"]
    assert _physician(loaded_client, "DEV-P01")["activity"] == "video_consult"

    advanced = loaded_client.post("/api/simulation/advance", json={"minutes": 10}).json()
    assert advanced["current_time"] == "2030-05-14T21:40:00Z"
    assert _physician(loaded_client, "DEV-P01")["activity"] == "available"
    assert _consult(loaded_client, "DEV-C101")["stage"] == "note_pending"
    assert loaded_client.get("/api/config").json()["simulation_time_source"] == "manual"

    reset = loaded_client.post("/api/simulation/reset").json()
    assert reset["current_time"] == reset["reference_time"]
    assert _physician(loaded_client, "DEV-P01")["activity"] == "video_consult"


def test_set_time_and_as_of_queries_do_not_depend_on_wall_clock(loaded_client):
    loaded_client.post("/api/simulation/time", json={"time": "2030-05-14T17:15:00-04:00"})
    c101 = _consult(loaded_client, "DEV-C101")

    assert c101["stage"] == "imaging_review"  # late video_started not yet ingested
    assert _consult(loaded_client, "DEV-C101", as_of="2030-05-14T21:20:00Z")["stage"] == (
        "video_in_progress"
    )


def test_set_time_rejects_naive_datetime(loaded_client):
    response = loaded_client.post("/api/simulation/time", json={"time": "2030-05-14T17:15:00"})

    assert response.status_code == 422


def test_event_history_annotations(loaded_client):
    page = loaded_client.get(
        "/api/events", params={"consult_id": "DEV-C101", "order": "event_time_asc"}
    ).json()
    late = next(e for e in page["items"] if e["event_type"] == "video_started")
    dupes = loaded_client.get("/api/events", params={"dedupe": "duplicates"}).json()
    pending = loaded_client.get("/api/events", params={"visibility": "pending"}).json()

    assert late["arrived_out_of_order"] is True and late["ingest_lag_seconds"] == 450
    assert late["event_time_raw"].endswith("-04:00") and late["raw"]["event_id"] == late["event_id"]
    assert dupes["total"] == 2 and all(not e["applied"] for e in dupes["items"])
    assert pending["total"] == 10


def test_filters_on_state_endpoints(loaded_client):
    on_shift = loaded_client.get("/api/physicians", params={"on_shift": True}).json()
    open_p01 = loaded_client.get(
        "/api/consultations", params={"open": True, "physician_id": "DEV-P01"}
    ).json()

    assert len(on_shift) == 6
    assert {c["stage"] for c in open_p01} == {
        "video_in_progress",
        "imaging_pending",
        "note_pending",
    }


def test_import_replaces_live_events(loaded_client):
    loaded_client.post(
        "/api/events",
        json={
            "event_id": "GONE",
            "event_type": "camera_active",
            "event_time": "2030-05-14T21:29:00Z",
            "physician_id": "DEV-P05",
        },
    )
    upload(loaded_client, {})  # an empty upload fails validation and changes nothing
    assert loaded_client.get("/api/datasets/status").json()["active"]["live_events"] == 1

    loaded_client.post("/api/datasets/sample")
    assert loaded_client.get("/api/datasets/status").json()["active"]["live_events"] == 0
