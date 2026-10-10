"""Event-log rules: identity, duplicates, visibility and deterministic ordering.

Policy (documented in docs/event-processing.md):

* **Identity** is ``event_id``. Among copies of one id, the *canonical* copy is the
  earliest by ``(ingested_at, sequence)``. Later copies are duplicates — or
  *conflicting* duplicates when their content differs — and are never applied.
* **Visibility** at simulation time T: ``ingested_at <= T`` and ``event_time <= T``.
* **Replay order**: ``(event_time, ingested_at, event_id, sequence)``. Arrival order
  never decides state, so a late event slots into its true place in the timeline.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from app.schemas.event import DedupeStatus, StoredEvent


def replay_sort_key(event: StoredEvent) -> tuple[datetime, datetime, str, int]:
    return (event.event_time, event.ingested_at, event.event_id, event.sequence)


def ingestion_sort_key(event: StoredEvent) -> tuple[datetime, int]:
    return (event.ingested_at, event.sequence)


def is_visible(event: StoredEvent, as_of: datetime) -> bool:
    return event.ingested_at <= as_of and event.event_time <= as_of


@dataclass(frozen=True)
class AnnotatedEvent:
    event: StoredEvent
    dedupe_status: DedupeStatus
    duplicate_of_sequence: int | None
    arrived_out_of_order: bool
    ingest_lag_seconds: float


def annotate_event_log(events: Sequence[StoredEvent]) -> list[AnnotatedEvent]:
    """Classify every stored event. Returned in ingestion order. Pure and deterministic."""
    canonical_by_id: dict[str, StoredEvent] = {}
    latest_event_time: datetime | None = None
    annotated: list[AnnotatedEvent] = []

    for event in sorted(events, key=ingestion_sort_key):
        canonical = canonical_by_id.get(event.event_id)
        if canonical is None:
            canonical_by_id[event.event_id] = event
            status = DedupeStatus.CANONICAL
            duplicate_of = None
        else:
            status = (
                DedupeStatus.DUPLICATE
                if canonical.content_hash == event.content_hash
                else DedupeStatus.CONFLICTING_DUPLICATE
            )
            duplicate_of = canonical.sequence

        out_of_order = False
        if status is DedupeStatus.CANONICAL:
            out_of_order = latest_event_time is not None and event.event_time < latest_event_time
            if latest_event_time is None or event.event_time > latest_event_time:
                latest_event_time = event.event_time

        annotated.append(
            AnnotatedEvent(
                event=event,
                dedupe_status=status,
                duplicate_of_sequence=duplicate_of,
                arrived_out_of_order=out_of_order,
                ingest_lag_seconds=(event.ingested_at - event.event_time).total_seconds(),
            )
        )
    return annotated
