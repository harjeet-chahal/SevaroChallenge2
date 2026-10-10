"""Repositories: thin, rule-free wrappers around SQLAlchemy queries."""

from app.repositories.events import EventRepository
from app.repositories.reference import ReferenceRepository
from app.repositories.system import SystemRepository

__all__ = ["EventRepository", "ReferenceRepository", "SystemRepository"]
