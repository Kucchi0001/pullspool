"""In-process sliding-window rate limiting.

The backend runs as a single uvicorn worker (SQLite + in-memory event bus),
so a process-local limiter is sufficient and avoids a Redis dependency.
"""

from __future__ import annotations

import time
from collections import deque

from app.core.errors import AppError, ErrorCode


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = {}

    def hit(self, key: str, limit: int, window_seconds: float) -> tuple[bool, int]:
        """Register a hit. Returns ``(allowed, retry_after_seconds)``."""
        now = time.monotonic()
        bucket = self._events.setdefault(key, deque())
        cutoff = now - window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= limit:
            retry_after = max(1, int(window_seconds - (now - bucket[0])) + 1)
            return False, retry_after
        bucket.append(now)
        return True, 0

    def reset(self, prefix: str = "") -> None:
        if not prefix:
            self._events.clear()
            return
        for key in [k for k in self._events if k.startswith(prefix)]:
            self._events.pop(key, None)

    def enforce(self, key: str, limit: int, window_seconds: float, message: str | None = None) -> None:
        allowed, retry_after = self.hit(key, limit, window_seconds)
        if not allowed:
            raise AppError(
                ErrorCode.RATE_LIMITED,
                message,
                headers={"Retry-After": str(retry_after)},
                details={"retry_after": retry_after},
            )


limiter = SlidingWindowLimiter()
