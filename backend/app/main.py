"""FastAPI application factory.

Run locally:  uvicorn app.main:app --reload --port 8000   (from backend/)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.db.session import build_engine, build_session_factory, init_db
from app.services.analysis import AnalysisCache


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = build_engine(settings.resolved_database_url)
        init_db(engine)
        app.state.engine = engine
        app.state.session_factory = build_session_factory(engine)
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Tele-Neurology Operations Command Center API",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.analysis_cache = AnalysisCache()
    app.state.optimization_cache = AnalysisCache(maxsize=32)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app = create_app()
