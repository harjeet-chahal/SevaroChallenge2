from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, File, Query, UploadFile, status
from pydantic import AwareDatetime

from app.api.deps import AppSettings, DbSession
from app.core.errors import AppError
from app.schemas.common import ApiModel
from app.schemas.event import EventIngestResult, EventInput, EventPage, EventRejection
from app.services.events import EventFilters, EventOrder, EventService

router = APIRouter(prefix="/events", tags=["events"])


class RejectionPage(ApiModel):
    total: int
    items: list[EventRejection]


@router.get("", response_model=EventPage, summary="Event history, annotated for the given time")
def list_events(
    db: DbSession,
    settings: AppSettings,
    as_of: Annotated[AwareDatetime | None, Query()] = None,
    physician_id: str | None = None,
    consult_id: str | None = None,
    hospital_id: str | None = None,
    event_type: str | None = None,
    visibility: Literal["all", "visible", "pending"] = "all",
    dedupe: Literal["all", "canonical", "duplicates"] = "all",
    recognized: bool | None = None,
    order: EventOrder = "ingested_desc",
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EventPage:
    return EventService(db, settings).list_events(
        as_of=as_of,
        filters=EventFilters(
            physician_id=physician_id,
            consult_id=consult_id,
            hospital_id=hospital_id,
            event_type=event_type,
            visibility=visibility,
            dedupe=dedupe,
            recognized=recognized,
        ),
        order=order,
        limit=limit,
        offset=offset,
    )


@router.post(
    "",
    response_model=EventIngestResult,
    status_code=status.HTTP_201_CREATED,
    summary="Inject one event or a batch (all-or-nothing). Takes effect without restart.",
)
def inject_events(
    db: DbSession, settings: AppSettings, body: EventInput | list[EventInput]
) -> EventIngestResult:
    items = body if isinstance(body, list) else [body]
    if not items:
        raise AppError("No events provided", code="validation_error", status_code=422)
    return EventService(db, settings).ingest(items)


@router.post(
    "/csv",
    response_model=EventIngestResult,
    status_code=status.HTTP_201_CREATED,
    summary="Append event rows from a CSV in the dataset's event_stream format",
)
async def inject_events_csv(
    db: DbSession, settings: AppSettings, file: Annotated[UploadFile, File()]
) -> EventIngestResult:
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise AppError("Upload too large", code="upload_too_large", status_code=413)
    return EventService(db, settings).ingest_csv(file.filename or "events.csv", data)


@router.get("/rejections", response_model=RejectionPage)
def list_rejections(
    db: DbSession,
    settings: AppSettings,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RejectionPage:
    total, items = EventService(db, settings).rejections(limit, offset)
    return RejectionPage(total=total, items=items)
