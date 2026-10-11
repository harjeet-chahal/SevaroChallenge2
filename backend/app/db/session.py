"""Engine and session factory construction.

The engine lives on ``app.state`` (created in the app lifespan) rather than as a module
global, so tests can run against an isolated database without monkeypatching.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, MetaData, create_engine, event, inspect
from sqlalchemy.orm import Session, sessionmaker

import app.db.models  # noqa: F401  (registers models on Base.metadata)
from app.db.base import Base

logger = logging.getLogger(__name__)


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _: Any) -> None:
    """Foreign keys on every connection; WAL journal (readers never block the single
    writer) and a busy timeout so a short write lock waits instead of failing."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
    except Exception:  # pragma: no cover - e.g. :memory: databases keep their own mode
        pass
    cursor.close()


def build_engine(database_url: str) -> Engine:
    connect_args: dict[str, Any] = {}
    if database_url.startswith("sqlite"):
        # FastAPI may touch a session from a different thread than the one that opened it.
        connect_args["check_same_thread"] = False
        db_path = database_url.removeprefix("sqlite:///")
        if db_path and db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    pool: dict[str, Any] = {}
    if database_url.startswith("sqlite") and ":memory:" not in database_url:
        # Size the pool to uvicorn's worker threadpool (40) so a burst of page loads waits
        # for CPU rather than failing with a pool timeout. SQLite connections are cheap.
        pool = {"pool_size": 10, "max_overflow": 40}
    engine = create_engine(database_url, connect_args=connect_args, **pool)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


SCHEMA_VERSION = "2"
"""Bump whenever an ORM model changes shape. A mismatching database is rebuilt."""


def init_db(engine: Engine) -> None:
    """Create tables, rebuilding the database if it was made by an older schema version.

    Hackathon trade-off: no migrations. All operational data comes from re-importable
    datasets, so a rebuild only costs a re-import. It is logged loudly.
    """
    from app.db.models import AppMeta

    with Session(engine) as session:
        try:
            row = session.get(AppMeta, "schema_version")
            found = row.value if row else None
        except Exception:  # table missing or unreadable: an older or foreign schema
            session.rollback()
            found = None
        has_tables = bool(inspect(engine).get_table_names())

    if has_tables and found != SCHEMA_VERSION:
        logger.warning(
            "Database schema version %s != %s; rebuilding tables (re-import the dataset).",
            found,
            SCHEMA_VERSION,
        )
        metadata = MetaData()
        metadata.reflect(engine)
        metadata.drop_all(engine)

    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.merge(AppMeta(key="schema_version", value=SCHEMA_VERSION))
        session.commit()
