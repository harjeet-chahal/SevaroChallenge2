"""FastAPI dependencies shared by all routes."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.common import ActorRef, UserRole
from app.services.analysis import AnalysisCache


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[Session]:
    """Request-scoped session. Services commit explicitly so a failed commit surfaces as
    an error response instead of happening after a success response was already built."""
    session: Session = request.app.state.session_factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_demo_actor(
    x_demo_role: Annotated[str | None, Header()] = None,
    x_demo_actor_id: Annotated[str | None, Header()] = None,
) -> ActorRef:
    """Resolve the caller's role from demo headers.

    There is no authentication in the demo: these are clearly labelled *simulated* roles
    and identities, not production authentication. Workflow routes still depend on this
    so that role checks (e.g. only a clinical lead may approve, a physician only sees their
    own offers) are enforced server-side and can later be backed by real auth without
    changing route signatures. ``X-Demo-Actor-Id`` names the simulated person (for a
    physician: their physician ID).
    """
    if x_demo_role is None:
        raise AppError("X-Demo-Role header is required", code="role_required", status_code=401)
    try:
        role = UserRole(x_demo_role)
        if role is UserRole.SYSTEM:  # automatic policy steps only; never a caller
            raise ValueError(x_demo_role)
    except ValueError as exc:
        raise AppError(
            f"Unknown role '{x_demo_role}'",
            code="role_invalid",
            status_code=401,
            details={"allowed": [r.value for r in UserRole if r is not UserRole.SYSTEM]},
        ) from exc
    return ActorRef(role=role, actor_id=x_demo_actor_id)


def get_analysis_cache(request: Request) -> AnalysisCache:
    return request.app.state.analysis_cache


def get_optimization_cache(request: Request) -> AnalysisCache:
    return request.app.state.optimization_cache


DbSession = Annotated[Session, Depends(get_db)]
Cache = Annotated[AnalysisCache, Depends(get_analysis_cache)]
OptCache = Annotated[AnalysisCache, Depends(get_optimization_cache)]
AppSettings = Annotated[Settings, Depends(get_settings_dep)]
DemoActor = Annotated[ActorRef, Depends(get_demo_actor)]
