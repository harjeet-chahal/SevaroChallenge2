"""Application settings, loaded from environment variables and an optional backend/.env file."""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app import __version__

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "NEUROGRID"
    app_version: str = __version__
    app_env: Literal["development", "test", "production"] = "development"

    database_url: str = "sqlite:///./data/sevaro_pulse.db"

    # Kept as a raw comma-separated string so it can be set from a plain env var.
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # Optional fixed "now" for the simulation. Must carry an explicit UTC offset.
    simulation_reference_time: AwareDatetime | None = None

    dataset_dir: Path = Field(default=Path("./data/raw"))

    # Committed SYNTHETIC SAMPLE DATA used by POST /api/datasets/sample.
    sample_dataset_dir: Path = Field(default=Path("./sample_data/synthetic_dev"))

    # Optional JSON file overriding the default CSV column/value mapping (see docs).
    dataset_mapping_file: Path | None = None

    # Optional JSON file overriding risk/coverage thresholds and policies (see docs).
    risk_rules_file: Path | None = None
    optimization_policy_file: Path | None = None
    """JSON overrides for Phase 4 optimizer policy (weights, limits, trap policy)."""
    intelligence_policy_file: Path | None = None
    """JSON overrides for the NEUROGRID intelligence policy (lead times, weights...)."""

    # Upload safety limits for dataset imports.
    max_upload_bytes: int = 50 * 1024 * 1024
    max_uncompressed_bytes: int = 200 * 1024 * 1024
    max_archive_entries: int = 200

    @field_validator(
        "simulation_reference_time",
        "dataset_mapping_file",
        "risk_rules_file",
        "optimization_policy_file",
        "intelligence_policy_file",
        mode="before",
    )
    @classmethod
    def _empty_reference_time_is_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        if isinstance(value, datetime) and value.tzinfo is None:
            raise ValueError("SIMULATION_REFERENCE_TIME must include a UTC offset")
        return value

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def resolved_database_url(self) -> str:
        """Resolve relative SQLite paths against backend/ so the CWD does not matter."""
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix) and not self.database_url.startswith(prefix + "/"):
            relative = self.database_url.removeprefix(prefix)
            if relative != ":memory:":
                return prefix + str((BACKEND_ROOT / relative).resolve())
        return self.database_url

    @property
    def resolved_dataset_dir(self) -> Path:
        return _resolve(self.dataset_dir)

    @property
    def resolved_sample_dataset_dir(self) -> Path:
        return _resolve(self.sample_dataset_dir)

    @property
    def resolved_dataset_mapping_file(self) -> Path | None:
        return _resolve(self.dataset_mapping_file) if self.dataset_mapping_file else None

    @property
    def resolved_risk_rules_file(self) -> Path | None:
        return _resolve(self.risk_rules_file) if self.risk_rules_file else None

    @property
    def resolved_optimization_policy_file(self) -> Path | None:
        return _resolve(self.optimization_policy_file) if self.optimization_policy_file else None

    @property
    def resolved_intelligence_policy_file(self) -> Path | None:
        return _resolve(self.intelligence_policy_file) if self.intelligence_policy_file else None


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else (BACKEND_ROOT / path).resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
