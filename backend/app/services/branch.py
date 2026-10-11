"""Isolated scenario branches: a throw-away copy of the live database.

``open_branch`` copies the live SQLite database with SQLite's online backup API into a
temporary file and yields a session bound to the copy. Every real service (event ingest,
replay, analysis, optimizers, workflow) can then run against the branch unchanged. The
file is deleted afterwards, so nothing a Chaos Lab scenario or an import preview does can
reach the baseline.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.db.session import build_engine, build_session_factory
from app.services.analysis import AnalysisCache


class BranchUnavailableError(AppError):
    status_code = 501
    code = "branch_unavailable"


@contextmanager
def open_branch(live: Session) -> Iterator[Session]:
    connection = live.connection()
    if connection.dialect.name != "sqlite":  # pragma: no cover - SQLite is the only store
        raise BranchUnavailableError("Scenario branches need the SQLite store.")
    source = connection.connection.driver_connection
    folder = Path(tempfile.mkdtemp(prefix="neurogrid-branch-"))
    path = folder / "branch.db"
    target = sqlite3.connect(path)
    try:
        source.backup(target)
    finally:
        target.close()
    live.rollback()  # release the read snapshot taken for the copy
    engine = build_engine(f"sqlite:///{path}")
    session = build_session_factory(engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        shutil.rmtree(folder, ignore_errors=True)


def fresh_caches() -> tuple[AnalysisCache, AnalysisCache]:
    """Branch services must never share caches with the live app."""
    return AnalysisCache(), AnalysisCache(maxsize=32)
