from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.time import NaiveDatetimeError, parse_iso_aware
from app.db.models import SimulationState
from app.db.session import build_engine, build_session_factory, init_db
from app.schemas.hospital import Hospital


def test_parse_iso_aware_accepts_offsets_and_z() -> None:
    assert parse_iso_aware("2030-06-01T08:30:00-06:00").utcoffset() == timedelta(hours=-6)
    assert parse_iso_aware("2030-06-01T08:30:00Z").utcoffset() == timedelta(0)


def test_parse_iso_aware_rejects_naive() -> None:
    with pytest.raises(NaiveDatetimeError):
        parse_iso_aware("2030-06-01T08:30:00")


def test_hospital_requires_iana_timezone() -> None:
    Hospital(id="h-1", name="Example", timezone="America/Phoenix")
    with pytest.raises(ValidationError):
        Hospital(id="h-1", name="Example", timezone="Not/AZone")


def test_utc_datetime_column_round_trips_aware_values(tmp_path) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'tz.db'}")
    init_db(engine)
    factory = build_session_factory(engine)
    offset_time = datetime(2030, 6, 1, 8, 30, tzinfo=timezone(timedelta(hours=-7)))

    with factory() as session:
        session.add(SimulationState(id=1, reference_time=offset_time, updated_at=offset_time))
        session.commit()

    with factory() as session:
        stored = session.get(SimulationState, 1)
        assert stored is not None
        assert stored.reference_time == offset_time
        assert stored.reference_time.tzinfo == UTC


def test_utc_datetime_column_rejects_naive_values(tmp_path) -> None:
    engine = build_engine(f"sqlite:///{tmp_path / 'tz.db'}")
    init_db(engine)

    with Session(engine) as session:
        session.add(SimulationState(id=1, reference_time=None, updated_at=datetime(2030, 1, 1)))
        with pytest.raises(Exception, match="naive datetime"):
            session.commit()
