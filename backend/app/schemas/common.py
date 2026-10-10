"""Shared schema building blocks.

IDs are opaque strings: never parse meaning out of an ID or assume a prefix/format.
Datetimes are ``AwareDatetime``: naive datetimes are rejected at the API boundary.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any

from pydantic import AfterValidator, BaseModel, ConfigDict, StringConstraints

from app.core.time import validate_timezone

EntityId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
"""Opaque identifier for physicians, hospitals, consults, events, etc."""

IanaTimezone = Annotated[str, AfterValidator(validate_timezone)]
"""IANA zone name such as 'America/Denver'. Abbreviations like 'ET' are not accepted."""


class ApiModel(BaseModel):
    """Base for all API schemas. ``from_attributes`` lets services return ORM rows directly."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class UserRole(StrEnum):
    COORDINATOR = "coordinator"
    CLINICAL_LEAD = "clinical_lead"
    PHYSICIAN = "physician"
    SYSTEM = "system"
    """Automatic steps under a documented simulation policy (expiry, activation). Never
    accepted from a request header."""


class Severity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ActorRef(ApiModel):
    """Who performed an action. In the demo there is no auth, so ``actor_id`` is optional."""

    role: UserRole
    actor_id: EntityId | None = None


class ApiErrorBody(ApiModel):
    code: str
    message: str
    details: Any = None


class ApiErrorResponse(ApiModel):
    error: ApiErrorBody
