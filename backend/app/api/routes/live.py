"""Live updates: a small Server-Sent Events stream of version counters.

Each connection polls the database once a second and emits an event whenever the data
version (dataset, events, staffing-relevant workflow decisions), the workflow version
(any workflow transition) or the simulation time changes. Clients refetch what they need
with the existing keyed-resource mechanism. No extra infrastructure; polling of
``/api/config`` remains the fallback.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from starlette.concurrency import run_in_threadpool

from app.services.workflow import WorkflowService

router = APIRouter(tags=["live"])

HEARTBEAT_SECONDS = 15.0
MAX_STREAM_SECONDS = 20.0
"""Each stream ends after this long and the browser's EventSource reconnects (``retry``).
An endless stream would block uvicorn's graceful shutdown, e.g. ``--reload`` waiting
forever for the connection to close."""


def _snapshot(request: Request) -> dict:
    app = request.app
    with app.state.session_factory() as session:
        summary = WorkflowService(
            session, app.state.settings, app.state.analysis_cache, app.state.optimization_cache
        ).summary()
    return summary.model_dump(mode="json")


@router.get("/live", summary="Server-Sent Events: version counters for live refresh")
async def live(request: Request, once: bool = False) -> StreamingResponse:
    async def stream():
        last = None
        idle = elapsed = 0.0
        yield "retry: 1000\n\n"
        while elapsed < MAX_STREAM_SECONDS:
            if await request.is_disconnected():
                break
            snap = await run_in_threadpool(_snapshot, request)
            if snap != last:
                last = snap
                idle = 0.0
                yield f"event: versions\ndata: {json.dumps(snap)}\n\n"
            elif idle >= HEARTBEAT_SECONDS:
                idle = 0.0
                yield ": keep-alive\n\n"
            if once:
                break
            await asyncio.sleep(1.0)
            idle += 1.0
            elapsed += 1.0

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
