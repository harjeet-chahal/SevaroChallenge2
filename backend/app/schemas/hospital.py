from __future__ import annotations

from typing import Any

from pydantic import Field

from app.schemas.common import ApiModel, EntityId, IanaTimezone


class HospitalRef(ApiModel):
    """Minimal hospital reference safe to show to any role (no operational detail)."""

    id: EntityId
    name: str


class Hospital(HospitalRef):
    timezone: IanaTimezone
    coverage_tier: str | None = None
    """Dataset-defined tier label. Interpreted by coverage rules, never by the frontend."""
    attributes: dict[str, Any] = Field(default_factory=dict)
    """Extra source columns preserved verbatim from the dataset."""
