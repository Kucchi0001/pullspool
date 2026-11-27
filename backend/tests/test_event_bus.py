"""Event bus unit tests."""

from __future__ import annotations

import asyncio

import pytest

from app.api.events import _format
from app.services.event_bus import EventBus


async def test_publish_reaches_subscribers() -> None:
    bus = EventBus()
    queue = bus.subscribe()
    bus.publish("task.updated", {"task": {"id": "1"}})

    event = await asyncio.wait_for(queue.get(), timeout=1)
    assert event.type == "task.updated"
    assert event.data["task"]["id"] == "1"
    bus.unsubscribe(queue)
    assert bus.subscriber_count == 0


async def test_overflow_drops_oldest_event() -> None:
    bus = EventBus(queue_size=2)
    queue = bus.subscribe()
    for index in range(5):
        bus.publish("progress", {"i": index})

    first = queue.get_nowait()
    second = queue.get_nowait()
    assert first.data["i"] == 3
    assert second.data["i"] == 4
    assert queue.empty()


async def test_subscriber_limit() -> None:
    bus = EventBus(max_subscribers=1)
    queue = bus.subscribe()
    with pytest.raises(RuntimeError):
        bus.subscribe()
    bus.unsubscribe(queue)
    bus.subscribe()


async def test_publish_without_subscribers_is_noop() -> None:
    bus = EventBus()
    bus.publish("task.updated", {"task": {}})
    assert bus.subscriber_count == 0


def test_sse_wire_format() -> None:
    payload = _format("task.updated", {"task": {"id": "abc"}, "changed": ["status"]})
    assert payload.startswith("event: task.updated\ndata: ")
    assert payload.endswith("\n\n")
    assert '"id": "abc"' in payload
