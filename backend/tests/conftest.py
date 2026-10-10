from __future__ import annotations

import io
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "sample_data" / "synthetic_dev"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        cors_origins="http://localhost:3000",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def loaded_client(client: TestClient) -> TestClient:
    response = client.post("/api/datasets/sample")
    assert response.status_code == 200, response.text
    return client


@pytest.fixture
def make_client(settings: Settings) -> Callable[..., TestClient]:
    """Build a fresh app on the same database (simulates a backend restart)."""

    def _make(**overrides) -> TestClient:
        return TestClient(create_app(settings.model_copy(update=overrides)))

    return _make


def sample_files() -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in SAMPLE_DIR.iterdir() if p.is_file()}


def zip_bytes(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def upload(client: TestClient, files: dict[str, bytes], **form: str):
    return client.post(
        "/api/datasets/import",
        files=[("files", (name, data)) for name, data in files.items()],
        data=form,
    )
