"""In-process publish/subscribe used to fan out SSE events.

Single-process by design (SQLite + one uvicorn worker). Slow clients are
protected by a bounded queue: when full, the oldest event is dropped instead of
blocking the publisher.
"""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class Event:
    type: str
    data: dict[str, Any]


class EventBus:
    def __init__(self, queue_size: int = 128, max_subscribers: int = 8) -> None:
        self._queues: set[asyncio.Queue[Event]] = set()
        self._queue_size = queue_size
        self._max_subscribers = max_subscribers

    @property
    def subscriber_count(self) -> int:
        return len(self._queues)

    def subscribe(self) -> asyncio.Queue[Event]:
        if len(self._queues) >= self._max_subscribers:
            raise RuntimeError("too many SSE subscribers")
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._queue_size)
        self._queues.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        self._queues.discard(queue)

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        if not self._queues:
            return
        event = Event(type=event_type, data=data)
        for queue in list(self._queues):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                with contextlib.suppress(asyncio.QueueEmpty):
                    queue.get_nowait()
                with contextlib.suppress(asyncio.QueueFull):
                    queue.put_nowait(event)

    def reset(self) -> None:
        self._queues.clear()
