"""File streaming with HTTP Range support and per-byte traffic accounting."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from fastapi import Request
from sqlalchemy import select
from starlette.responses import StreamingResponse

from app.core.config import AppConfig
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.timeutil import local_day, now_iso
from app.database.session import Database
from app.models.task import Task
from app.models.traffic import TrafficDaily
from app.services import storage_service
from app.services.event_bus import EventBus
from app.services.settings_service import SettingsService

logger = get_logger("pullspool.transfer")


@dataclass(slots=True)
class RangeSpec:
    start: int
    end: int  # inclusive

    @property
    def length(self) -> int:
        return self.end - self.start + 1


def parse_range_header(value: str | None, size: int) -> tuple[RangeSpec | None, str]:
    """Return ``(spec, state)`` with state in ``none``/``satisfiable``/``unsatisfiable``."""
    if not value or not value.strip().lower().startswith("bytes="):
        return None, "none"
    raw = value.strip()[6:].strip()
    if "," in raw:
        raw = raw.split(",", 1)[0].strip()
    if "-" not in raw:
        return None, "none"
    start_raw, _, end_raw = raw.partition("-")
    start_raw, end_raw = start_raw.strip(), end_raw.strip()
    try:
        if not start_raw:
            if not end_raw:
                return None, "none"
            suffix = int(end_raw)
            if suffix <= 0:
                return None, "unsatisfiable"
            start = max(0, size - suffix)
            end = size - 1
        else:
            start = int(start_raw)
            end = int(end_raw) if end_raw else size - 1
    except ValueError:
        return None, "none"
    if start < 0:
        return None, "none"
    if start >= size:
        return None, "unsatisfiable"
    if end < start:
        return None, "none"
    return RangeSpec(start=start, end=min(end, size - 1)), "satisfiable"


def content_disposition(filename: str) -> str:
    safe = "".join(char for char in filename if 0x20 <= ord(char) < 0x7F and char not in '"\\')
    fallback = safe.strip() or "download.bin"
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"


def build_etag(task: Task, size: int) -> str:
    digest = (task.sha256 or "unknown")[:16]
    return f'"{digest}-{size}"'


def _consume_result(task: asyncio.Task[None]) -> None:
    """Callback for fire-and-forget recording tasks: never leak exceptions."""
    with contextlib.suppress(Exception):
        task.result()


class TransferService:
    """Tracks in-flight retrievals and streams files out of the download root."""

    def __init__(
        self,
        config: AppConfig,
        database: Database,
        events: EventBus,
        settings_service: SettingsService,
    ) -> None:
        self._config = config
        self._db = database
        self._events = events
        self._settings_service = settings_service
        self._active: dict[str, int] = {}
        self._total = 0

    @property
    def total_active(self) -> int:
        return self._total

    def is_transferring(self, task_id: str) -> bool:
        return self._active.get(task_id, 0) > 0

    def _acquire(self, task_id: str, limit: int) -> bool:
        if self._total >= max(1, limit):
            return False
        self._active[task_id] = self._active.get(task_id, 0) + 1
        self._total += 1
        return True

    def _release(self, task_id: str) -> None:
        current = self._active.get(task_id, 0)
        if current <= 1:
            self._active.pop(task_id, None)
        else:
            self._active[task_id] = current - 1
        self._total = max(0, self._total - 1)

    async def prepare(self, task: Task, request: Request) -> StreamingResponse:
        async with self._db.session() as session:
            settings = await self._settings_service.load(session)

        if not self._acquire(task.id, settings.max_transfer_concurrency):
            raise AppError(
                ErrorCode.RATE_LIMITED,
                "同时回传的任务数已达上限，请稍后再试",
                headers={"Retry-After": "5"},
            )

        try:
            if not task.stored_relpath:
                raise AppError(ErrorCode.FILE_NOT_FOUND)
            path = storage_service.resolve_inside(self._config.download_root, task.stored_relpath)
            if not path.exists() or path.is_symlink() or not path.is_file():
                raise AppError(ErrorCode.FILE_NOT_FOUND, "文件已不存在")

            size = path.stat().st_size
            etag = build_etag(task, size)

            range_header = request.headers.get("range")
            if_range = request.headers.get("if-range")
            if if_range and if_range.strip() != etag:
                range_header = None

            spec, state = parse_range_header(range_header, size)
            if state == "unsatisfiable":
                raise AppError(
                    ErrorCode.RANGE_NOT_SATISFIABLE,
                    headers={"Content-Range": f"bytes */{size}"},
                )

            start = spec.start if spec else 0
            length = spec.length if spec else size
            status_code = 206 if spec else 200

            headers = {
                "Content-Type": "application/octet-stream",
                "Content-Length": str(length),
                "Accept-Ranges": "bytes",
                "ETag": etag,
                "Content-Disposition": content_disposition(task.filename),
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
            }
            if spec:
                headers["Content-Range"] = f"bytes {spec.start}-{spec.end}/{size}"

            generator = self._stream(task.id, path, start, length, size, spec is None)
        except BaseException:
            self._release(task.id)
            raise

        return StreamingResponse(generator, status_code=status_code, headers=headers)

    async def _stream(
        self,
        task_id: str,
        path: Path,
        start: int,
        length: int,
        full_size: int,
        is_full: bool,
    ):
        chunk_size = self._config.transfer_chunk_size
        flush_threshold = self._config.traffic_flush_bytes
        sent = 0
        pending = 0
        completed = False
        try:
            with path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(chunk_size, remaining))
                    if not chunk:
                        break
                    yield chunk
                    sent += len(chunk)
                    pending += len(chunk)
                    remaining -= len(chunk)
                    if pending >= flush_threshold:
                        await self._record(task_id, pending, completed=False)
                        pending = 0
            completed = is_full and sent == full_size
        except (BrokenPipeError, ConnectionResetError, asyncio.CancelledError):
            logger.info("transfer for task %s interrupted after %s bytes", task_id, sent)
            raise
        finally:
            # Final accounting must not be lost when the client disconnects:
            # schedule it and let it finish even if this generator is cancelled.
            recorder: asyncio.Task[None] | None = None
            if pending or completed:
                recorder = asyncio.create_task(
                    self._record(task_id, pending, completed=completed)
                )
            try:
                if recorder is not None:
                    await asyncio.shield(recorder)
            except asyncio.CancelledError:
                logger.info(
                    "transfer for task %s cancelled after %s bytes; accounting continues",
                    task_id,
                    sent,
                )
                if recorder is not None:
                    recorder.add_done_callback(_consume_result)
            except Exception:
                logger.exception(
                    "failed to record final transfer bytes for task %s", task_id
                )
            finally:
                self._release(task_id)
            logger.info(
                "transfer for task %s finished: %s bytes (complete=%s)",
                task_id,
                sent,
                completed,
            )

    async def _record(self, task_id: str, delta: int, *, completed: bool) -> None:
        if delta <= 0 and not completed:
            return
        try:
            async with self._db.session() as session:
                task = await session.get(Task, task_id)
                if delta > 0:
                    day = local_day(tz_name=self._config.timezone)
                    row = await session.scalar(
                        select(TrafficDaily).where(
                            TrafficDaily.day == day, TrafficDaily.direction == "up"
                        )
                    )
                    if row is None:
                        session.add(TrafficDaily(day=day, direction="up", bytes=delta))
                    else:
                        row.bytes += delta
                if task is not None:
                    task.upload_bytes_counted += max(0, delta)
                    if completed:
                        task.transfer_count += 1
                    task.last_synced_at = now_iso()
                await session.commit()
            if delta > 0:
                self._events.publish("traffic.updated", {"direction": "up", "bytes": delta})
        except Exception:  # pragma: no cover - never break a transfer over accounting
            logger.exception("failed to record transfer bytes for task %s", task_id)
