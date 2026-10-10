"""Dataset import over HTTP: formats, validation, atomicity and persistence."""

from __future__ import annotations

import filecmp
import zipfile
from io import BytesIO

from app.repositories.events import EventRepository
from scripts.generate_sample_dataset import write_dataset
from tests.conftest import SAMPLE_DIR, sample_files, upload, zip_bytes


def _issues(response, code=None):
    issues = response.json()["error"]["details"]["issues"]
    return [i for i in issues if code is None or i["code"] == code]


def test_sample_dataset_loads_and_syncs_config(loaded_client):
    config = loaded_client.get("/api/config").json()
    status = loaded_client.get("/api/datasets/status").json()

    assert config["dataset_loaded"] is True
    assert config["simulation_time"] == "2030-05-14T21:30:00Z"
    assert config["simulation_time_source"] == "dataset"
    assert status["active"]["synthetic"] is True
    assert "SYNTHETIC SAMPLE DATA" in status["active"]["label"]
    assert status["active"]["counts"]["hospitals"] == 5
    assert status["active"]["rejected_events"] == 1  # the deliberately malformed row


def test_zip_upload_imports_the_same_dataset(client):
    response = upload(client, {"dataset.zip": zip_bytes(sample_files())})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["counts"]["events"] == 293
    assert body["reference_source"] == "dataset_manifest"
    mapped = {m["table"]: m["mapped"] for m in body["column_mappings"]}
    assert mapped["event_stream"]["event_time"] == "event_time"


def test_individual_csv_upload_with_reference_time_override(client):
    files = {k: v for k, v in sample_files().items() if k != "dataset_manifest.json"}
    response = upload(client, files, reference_time="2030-05-14T16:00:00-05:00")

    assert response.status_code == 200, response.text
    assert response.json()["reference_time"] == "2030-05-14T21:00:00Z"
    assert response.json()["reference_source"] == "import_option"


def test_reference_time_derived_from_latest_ingest_when_not_given(client):
    files = {k: v for k, v in sample_files().items() if k != "dataset_manifest.json"}
    body = upload(client, files).json()

    assert body["reference_source"] == "latest_ingested_at"
    assert any(i["code"] == "reference_time_derived" for i in body["issues"])


def test_missing_required_file_is_actionable(client):
    files = {k: v for k, v in sample_files().items() if not k.startswith("hospitals")}
    response = upload(client, files)

    assert response.status_code == 422
    missing = _issues(response, "missing_file")
    assert missing and "hospitals" in missing[0]["message"] and missing[0]["hint"]


def test_missing_required_column_lists_found_headers_and_fix(client):
    files = sample_files()
    files["hospitals.csv"] = files["hospitals.csv"].replace(b"timezone", b"zone_name", 1)
    response = upload(client, files)

    assert response.status_code == 422
    issue = _issues(response, "missing_column")[0]
    assert "zone_name" in issue["message"] and "DATASET_MAPPING_FILE" in issue["hint"]


# 12. Invalid timestamps / time zones are rejected --------------------------------------


def test_invalid_hospital_timezone_is_rejected(client):
    files = sample_files()
    files["hospitals.csv"] = files["hospitals.csv"].replace(b"America/Denver", b"Mars/Olympus", 1)
    response = upload(client, files)

    assert response.status_code == 422
    issue = _issues(response, "invalid_timezone")[0]
    assert issue["value"] == "Mars/Olympus" and issue["row"] == 3


def test_timezone_labels_are_mapped_and_reported(client):
    files = sample_files()
    files["hospitals.csv"] = files["hospitals.csv"].replace(b"America/Chicago", b"Central", 1)
    body = upload(client, files).json()

    assert any(i["code"] == "timezone_label_mapped" for i in body["issues"])


def test_naive_event_timestamp_row_is_rejected_and_recorded(loaded_client):
    rejections = loaded_client.get("/api/events/rejections").json()

    assert rejections["total"] == 1
    error = rejections["items"][0]["errors"][0]
    assert error["field"] == "event_time" and "no UTC offset" in error["message"]


# 13. Failed imports do not corrupt the previous dataset --------------------------------


def test_failed_validation_keeps_previous_dataset(loaded_client):
    before = loaded_client.get("/api/state").json()
    status_before = loaded_client.get("/api/datasets/status").json()

    files = sample_files()
    files["hospitals.csv"] = files["hospitals.csv"].replace(b"America/Denver", b"Nowhere/Zone", 1)
    assert upload(loaded_client, files).status_code == 422

    after = loaded_client.get("/api/state").json()
    status_after = loaded_client.get("/api/datasets/status").json()
    assert after == before
    assert status_after["active"]["import_id"] == status_before["active"]["import_id"]
    assert status_after["last_attempt"]["status"] == "failed"


def test_storage_failure_mid_import_rolls_back(loaded_client, monkeypatch):
    before = loaded_client.get("/api/state").json()

    def explode(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(EventRepository, "add", explode)
    response = loaded_client.post("/api/datasets/sample")
    monkeypatch.undo()

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "dataset_persist_failed"
    assert loaded_client.get("/api/state").json() == before


# 15. Dataset state survives a backend restart -------------------------------------------


def test_dataset_and_clock_survive_restart(make_client):
    with make_client() as first:
        assert first.post("/api/datasets/sample").status_code == 200
        first.post("/api/simulation/advance", json={"minutes": 3})
        first.post(
            "/api/events",
            json={
                "event_id": "RESTART-1",
                "event_type": "physician_status_changed",
                "event_time": "2030-05-14T17:32:00-04:00",
                "physician_id": "DEV-P06",
                "status": "Available",
            },
        )
        state_before = first.get("/api/state").json()

    with make_client() as second:
        config = second.get("/api/config").json()
        state_after = second.get("/api/state").json()

    assert config["dataset_loaded"] is True
    assert config["simulation_time"] == "2030-05-14T21:33:00Z"
    assert state_after == state_before


# ZIP safety ----------------------------------------------------------------------------


def test_zip_path_traversal_is_rejected(client):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("../../etc/hospitals.csv", "hospital_id,timezone\n")
    response = upload(client, {"evil.zip": buffer.getvalue()})

    assert response.status_code == 422
    assert _issues(response, "archive_path_traversal")


def test_oversized_upload_is_rejected(make_client):
    with make_client(max_upload_bytes=1024) as small:
        response = upload(small, {"dataset.zip": zip_bytes(sample_files())})

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "upload_too_large"


def test_zip_bomb_style_expansion_is_capped(make_client):
    big = {"event_stream.csv": b"x" * 50_000}
    with make_client(max_uncompressed_bytes=10_000) as small:
        response = upload(small, {"dataset.zip": zip_bytes(big)})

    assert response.status_code == 422
    assert _issues(response, "archive_too_large")


# Fixtures and verification ------------------------------------------------------------


def test_snapshot_verification_reports_no_mismatches_for_sample(loaded_client):
    report = loaded_client.get("/api/datasets/verification").json()

    assert report["available"] is True
    assert report["compared_entities"] == 16
    assert report["mismatches"] == []


def test_fixture_generator_is_reproducible(tmp_path):
    write_dataset(tmp_path)

    names = sorted(p.name for p in SAMPLE_DIR.iterdir() if p.suffix in {".csv", ".json"})
    match, mismatch, errors = filecmp.cmpfiles(SAMPLE_DIR, tmp_path, names, shallow=False)
    assert mismatch == [] and errors == [], "committed fixture is stale: re-run the generator"
