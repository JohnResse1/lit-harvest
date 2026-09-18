"""Server-Sent Events for dashboard state updates."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter()


async def event_stream(request: Request) -> AsyncIterator[str]:
    container = request.app.state.container
    previous = ""
    heartbeat = 0
    while not await request.is_disconnected():
        overview = container.dashboard.overview()
        current = json.dumps(
            {
                "papers": overview["papers"],
                "jobs": overview["jobs"],
                "failures": overview["failures"][:5],
                "queue": overview["queue"],
            },
            sort_keys=True,
            default=str,
        )
        if current != previous:
            event = {
                "type": "state_update",
                "generated_at": datetime.now(UTC).isoformat(),
                "data": {
                    "papers": overview["papers"],
                    "jobs": overview["jobs"],
                    "failures": overview["failures"][:5],
                    "queue": overview["queue"],
                },
            }
            yield f"event: message\ndata: {json.dumps(event, default=str)}\n\n"
            previous = current
            heartbeat = 0
        else:
            heartbeat += 1
            if heartbeat >= 15:
                yield ": keep-alive\n\n"
                heartbeat = 0
        await asyncio.sleep(2)


@router.get("/events")
async def events(request: Request) -> StreamingResponse:
    return StreamingResponse(
        event_stream(request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
