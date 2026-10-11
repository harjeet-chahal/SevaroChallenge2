"""Event history and live event injection (no restart needed: state is replayed per request)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from fastapi import status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.core.time import to_utc, utc_now
from app.engines.event_processing import (
    EventValidationError,
    annotate_event_log,
    is_visible,
    normalize_event,
)
from app.repositories import EventRepository, ReferenceRepository, SystemRepository
from app.schemas.event import (
    DedupeStatus,
    EventIngestOutcome,
    EventIngestResult,
    EventInput,
    EventPage,
    EventSource,
    EventView,
    FieldIssue,
    KnownEventType,
    NormalizedEvent,
)
from app.services.dataset_import.csv_table import read_csv
from app.services.dataset_import.issues import IssueLog
from app.services.dataset_import.mapping import load_mapping
from app.services.dataset_import.parsers import ParseContext, parse_event_rows
from app.services.simulation import SimulationService

EventOrder = Literal["ingested_desc", "ingested_asc", "event_time_desc", "event_time_asc"]


@dataclass
class EventFilters:
    physician_id: str | None = None
    consult_id: str | None = None
    hospital_id: str | None = None
    event_type: str | None = None
    visibility: Literal["all", "visible", "pending"] = "all"
    dedupe: Literal["all", "canonical", "duplicates"] = "all"
    recognized: bool | None = None


@dataclass
class _Rejected:
    index: int
    event_id: str | None
    event_type: str | None
    errors: list[FieldIssue]
    raw: dict
    source_file: str | None = None
    source_row: int | None = None


MAX_CLOCK_ADVANCE = timedelta(hours=12)
"""Monotonic clock policy: an import may move "now" forward to its latest event, but never
backward and never by more than this (a mistyped date cannot jump the scenario by days)."""


def advance_to_latest(now_sim: datetime, events: list[NormalizedEvent]) -> tuple[datetime, str]:
    """Monotonic clock policy for imports: now = max(now, latest event_time / ingested_at).

    A late event (event_time in the past) changes past state without moving time backward.
    """
    latest = max((max(e.event_time, e.ingested_at) for e in events), default=now_sim)
    if latest <= now_sim:
        return now_sim, (
            "Clock unchanged: every imported event is at or before the current simulation "
            "time (late events update past state; time never moves backward)."
        )
    if latest - now_sim > MAX_CLOCK_ADVANCE:
        return now_sim, (
            f"Clock unchanged: the latest event is {latest.isoformat()}, more than "
            f"{MAX_CLOCK_ADVANCE} ahead; advance the clock explicitly if intended."
        )
    return latest, f"Clock advanced to the latest imported event ({latest.isoformat()})."


class EventService:
    def __init__(self, session: Session, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.repo = EventRepository(session)
        self.simulation = SimulationService(session, settings)

    # --- history ---------------------------------------------------------------

    def list_events(
        self,
        *,
        as_of: datetime | None,
        filters: EventFilters,
        order: EventOrder,
        limit: int,
        offset: int,
    ) -> EventPage:
        current = self.simulation.require_current_time()
        moment = to_utc(as_of) if as_of else current
        views: list[EventView] = []
        for a in annotate_event_log(self.repo.load_all()):
            e = a.event
            visible = is_visible(e, moment)
            view = EventView(
                **e.model_dump(),
                recognized=e.is_known_type,
                dedupe_status=a.dedupe_status,
                duplicate_of_sequence=a.duplicate_of_sequence,
                ingest_lag_seconds=a.ingest_lag_seconds,
                arrived_out_of_order=a.arrived_out_of_order,
                visible=visible,
                applied=visible and a.dedupe_status is DedupeStatus.CANONICAL and e.is_known_type,
            )
            if self._keep(view, filters):
                views.append(view)

        key = {
            "ingested_desc": (lambda v: (v.ingested_at, v.sequence), True),
            "ingested_asc": (lambda v: (v.ingested_at, v.sequence), False),
            "event_time_desc": (lambda v: (v.event_time, v.ingested_at, v.sequence), True),
            "event_time_asc": (lambda v: (v.event_time, v.ingested_at, v.sequence), False),
        }[order]
        views.sort(key=key[0], reverse=key[1])
        return EventPage(
            as_of=moment,
            total=len(views),
            offset=offset,
            limit=limit,
            items=views[offset : offset + limit],
        )

    @staticmethod
    def _keep(v: EventView, f: EventFilters) -> bool:
        if f.physician_id and v.physician_id != f.physician_id:
            return False
        if f.consult_id and v.consult_id != f.consult_id:
            return False
        if f.hospital_id and v.hospital_id != f.hospital_id:
            return False
        if f.event_type and v.event_type != f.event_type:
            return False
        if f.visibility == "visible" and not v.visible:
            return False
        if f.visibility == "pending" and v.visible:
            return False
        if f.dedupe == "canonical" and v.dedupe_status is not DedupeStatus.CANONICAL:
            return False
        if f.dedupe == "duplicates" and v.dedupe_status is DedupeStatus.CANONICAL:
            return False
        return not (f.recognized is not None and v.recognized != f.recognized)

    # --- injection -------------------------------------------------------------

    def ingest(self, inputs: list[EventInput]) -> EventIngestResult:
        now_sim = self.simulation.require_current_time()
        rules = load_mapping(self.settings.resolved_dataset_mapping_file).events
        accepted: list[tuple[int, NormalizedEvent, list[str]]] = []
        rejected: list[_Rejected] = []
        for index, item in enumerate(inputs):
            fields = item.model_dump(exclude={"payload"})
            try:
                result = normalize_event(
                    fields,
                    source=EventSource.LIVE_INGEST,
                    rules=rules,
                    extra=item.payload,
                    raw=item.model_dump(exclude_none=True),
                    default_ingested_at=now_sim,
                )
            except EventValidationError as exc:
                rejected.append(
                    _Rejected(
                        index,
                        exc.event_id,
                        exc.event_type,
                        exc.issues,
                        item.model_dump(exclude_none=True),
                    )
                )
                continue
            accepted.append((index, result.event, result.warnings))
        return self._store(accepted, rejected, now_sim, total=len(inputs))

    def ingest_csv(
        self, filename: str, data: bytes, *, advance_clock: bool = False
    ) -> EventIngestResult:
        now_sim = self.simulation.require_current_time()
        mapping = load_mapping(self.settings.resolved_dataset_mapping_file)
        log = IssueLog(mapping.max_reported_issues)
        table = read_csv(filename, data, log)
        ctx = ParseContext(mapping=mapping, log=log)
        parsed = (
            parse_event_rows(ctx, table, source=EventSource.LIVE_INGEST, report_summary=False)
            if table
            else None
        )
        row_level = {"too_many_invalid_events", "no_valid_events"}
        structural = [
            i for i in log.issues if i.severity.value == "error" and i.code not in row_level
        ]
        if parsed is None or structural:
            raise AppError(
                "The CSV could not be read as event rows; nothing was stored.",
                code="event_csv_invalid",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                details={"issues": [i.model_dump(mode="json") for i in log.issues]},
            )
        accepted = [(e.source_row or i, e, []) for i, e in enumerate(parsed.events, start=1)]
        rejected = [
            _Rejected(
                r.source_row, r.event_id, r.event_type, r.errors, r.raw, r.source_file, r.source_row
            )
            for r in parsed.rejected
        ]
        return self._store(
            accepted, rejected, now_sim, total=parsed.rows_read, advance_clock=advance_clock
        )

    def _store(
        self,
        accepted: list[tuple[int, NormalizedEvent, list[str]]],
        rejected: list[_Rejected],
        now_sim: datetime,
        *,
        total: int,
        advance_clock: bool = False,
    ) -> EventIngestResult:
        if rejected:
            for r in rejected:
                self.repo.add_rejection(
                    source=EventSource.LIVE_INGEST,
                    import_id=None,
                    source_file=r.source_file,
                    source_row=r.source_row,
                    event_id=r.event_id,
                    event_type=r.event_type,
                    errors=r.errors,
                    raw=r.raw,
                    recorded_at=utc_now(),
                )
            self.session.commit()
            outcomes = [
                EventIngestOutcome(
                    index=r.index, event_id=r.event_id, status="rejected", errors=r.errors
                )
                for r in rejected
            ]
            raise AppError(
                f"{len(rejected)} of {total} event(s) failed validation; nothing was stored. "
                "Rejections are recorded in GET /api/events/rejections.",
                code="event_invalid",
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                details={"outcomes": [o.model_dump(mode="json") for o in outcomes]},
            )

        reference = ReferenceRepository(self.session).load()
        physicians = {p.id for p in reference.physicians}
        hospitals = {h.id for h in reference.hospitals}
        known_consults = self.repo.known_consult_ids()
        existing = self.repo.hashes_by_event_id(e.event_id for _, e, _ in accepted)

        outcomes: list[EventIngestOutcome] = []
        duplicates = 0
        for index, event, warnings in accepted:
            warnings = list(warnings)
            hashes = existing.setdefault(event.event_id, [])
            if hashes:
                outcome_status = (
                    "duplicate" if event.content_hash in hashes else "conflicting_duplicate"
                )
                duplicates += 1
            else:
                outcome_status = "accepted"
            hashes.append(event.content_hash)
            if event.physician_id and event.physician_id not in physicians:
                warnings.append(f"physician '{event.physician_id}' is not in the rosters")
            if event.hospital_id and event.hospital_id not in hospitals:
                warnings.append(f"hospital '{event.hospital_id}' is not in hospitals")
            if event.consult_id and event.consult_id not in known_consults:
                if event.event_type != KnownEventType.CONSULT_RECEIVED:
                    warnings.append(f"consult '{event.consult_id}' has no earlier events")
            known_consults.add(event.consult_id or "")
            outcomes.append(
                EventIngestOutcome(
                    index=index,
                    event_id=event.event_id,
                    status=outcome_status,  # type: ignore[arg-type]
                    warnings=warnings,
                    visible_now=event.ingested_at <= now_sim and event.event_time <= now_sim,
                )
            )

        self.repo.add((e for _, e, _ in accepted), import_id=None)
        state = SystemRepository(self.session).get_or_create_simulation_state(utc_now())
        state.data_version = (state.data_version or 0) + 1
        state.updated_at = utc_now()
        new_time, note = (
            advance_to_latest(now_sim, [e for _, e, _ in accepted])
            if advance_clock
            else (now_sim, None)
        )
        if new_time != now_sim:
            state.current_time = new_time
            for (_, e, _), o in zip(accepted, outcomes, strict=True):
                o.visible_now = e.ingested_at <= new_time and e.event_time <= new_time
        self.session.commit()
        return EventIngestResult(
            received=total,
            accepted=len(accepted) - duplicates,
            duplicates=duplicates,
            rejected=0,
            simulation_time=new_time,
            outcomes=outcomes,
            clock_before=now_sim if advance_clock else None,
            clock_note=note,
        )

    def rejections(self, limit: int, offset: int):
        return self.repo.list_rejections(limit, offset)
