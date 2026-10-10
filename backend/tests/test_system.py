from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app


def test_health_reports_ok_with_database(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == {"status": "ok", "detail": None}
    assert body["environment"] == "test"
    checked_at = datetime.fromisoformat(body["checked_at"])
    assert checked_at.tzinfo is not None


def test_config_reports_no_dataset_and_no_simulation_time(client: TestClient) -> None:
    response = client.get("/api/config")

    assert response.status_code == 200
    body = response.json()
    assert body["app_name"] == "Sevaro Pulse"
    assert body["dataset_loaded"] is False
    assert body["simulation_time"] is None
    assert body["simulation_time_source"] == "unset"


def test_config_uses_simulation_time_from_environment(settings: Settings) -> None:
    configured = settings.model_copy(
        update={"simulation_reference_time": datetime(2030, 1, 1, 17, 0, tzinfo=UTC)}
    )
    with TestClient(create_app(configured)) as client:
        body = client.get("/api/config").json()

    assert body["simulation_time_source"] == "environment"
    assert datetime.fromisoformat(body["simulation_time"]) == datetime(
        2030, 1, 1, 17, 0, tzinfo=UTC
    )


def test_naive_simulation_time_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, simulation_reference_time="2030-01-01T12:00:00")


def test_unknown_route_uses_standard_error_envelope(client: TestClient) -> None:
    response = client.get("/api/does-not-exist")

    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "Not Found", "details": None}
    }


def test_cors_allows_configured_origin(client: TestClient) -> None:
    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
