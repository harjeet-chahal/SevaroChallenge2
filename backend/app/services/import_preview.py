"""Supplemental CSV import preview: validate and replay on a branch, change nothing.

The CSV goes through the exact ingest path used by ``POST /api/events/csv`` (header and
row validation, normalisation, dedupe, conflict detection), but against a throw-away copy
of the database. The response lists every row outcome and the effect on alerts, demand
and coverage, so the operator sees the impact before applying it. Applying is a separate
call; a failed preview never touches live state.
"""

from __future__ import annotations

from collections import Counter

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.schemas.intelligence import ImportPreview
from app.services.analysis import AnalysisService
from app.services.branch import fresh_caches, open_branch
from app.services.chaos import _alerts, _deltas
from app.services.events import EventService
from app.services.simulation import SimulationService


def preview_csv(
    session: Session, settings: Settings, filename: str, data: bytes, *, advance_clock: bool
) -> ImportPreview:
    SimulationService(session, settings).require_current_time()
    with open_branch(session) as branch:
        before = AnalysisService(branch, settings, fresh_caches()[0]).analysis()
        clock_before = before.state.as_of
        errors: list[dict] = []
        outcomes: list[dict] = []
        valid = True
        result = None
        try:
            result = EventService(branch, settings).ingest_csv(
                filename, data, advance_clock=advance_clock
            )
            outcomes = [o.model_dump(mode="json") for o in result.outcomes]
        except AppError as exc:
            valid = False
            details = exc.details or {}
            errors = list(details.get("outcomes") or details.get("issues") or [])
            if not errors:
                errors = [{"message": str(exc), "code": exc.code}]
        after = AnalysisService(branch, settings, fresh_caches()[0]).analysis()
        statuses = Counter(o["status"] for o in outcomes)
        return ImportPreview(
            filename=filename,
            valid=valid,
            received=result.received if result else len(errors),
            accepted=statuses.get("accepted", 0),
            duplicates=statuses.get("duplicate", 0),
            conflicting_duplicates=statuses.get("conflicting_duplicate", 0),
            rejected=0
            if valid
            else sum(1 for e in errors if e.get("status") == "rejected") or len(errors),
            unknown_event_types={
                k: v
                for k, v in after.state.diagnostics.unknown_event_types.items()
                if v != before.state.diagnostics.unknown_event_types.get(k)
            },
            outcomes=outcomes,
            errors=errors,
            clock_before=clock_before,
            clock_after=after.state.as_of,
            deltas=_deltas(before, after),
            alerts_new=sorted(_alerts(after) - _alerts(before)),
            alerts_resolved=sorted(_alerts(before) - _alerts(after)),
            note="Preview only: replayed on an isolated branch. Nothing has been applied."
            if valid
            else "Validation failed: nothing would be stored. Fix the listed rows and retry.",
        )
