"""Server-Sent Events stream for live task updates."""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, Depends, Request
from starlette.responses import StreamingResponse

from app.api.deps import get_current_user
from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.services.event_bus import Event, EventBus

router = APIRouter(tags=["events"])

HEARTBEAT_SECONDS = 15.0


def _format(event_type: str, data: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/events")
async def stream_events(
    request: Request,
    _: User = Depends(get_current_user),
) -> StreamingResponse:
    bus: EventBus = request.app.state.events
    try:
        queue = bus.subscribe()
    except RuntimeError:
        raise AppError(
            ErrorCode.RATE_LIMITED,
            "实时连接数已达上限，请关闭其他页面后重试",
            headers={"Retry-After": "5"},
        ) from None

    async def generator():
        try:
            yield "retry: 3000\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event: Event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield _format("ping", {"t": int(time.time())})
                    continue
                yield _format(event.type, event.data)
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
