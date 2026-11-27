"""Task lifecycle: creation, scheduling, progress sync, verification, controls."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppConfig
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.timeutil import iso_plus, local_day, now_iso, to_iso, utc_now
from app.database.session import Database
from app.models.event import TaskEvent
from app.models.task import Task
from app.models.traffic import TrafficDaily
from app.schemas.task import (
    SCOPE_VALUES,
    SORT_COLUMNS,
    CancelTaskRequest,
    CreateTaskRequest,
    TaskListResponse,
    TaskOut,
    task_to_out,
)
from app.services import storage_service
from app.services.aria2_service import ARIA2_ERROR_CODES, Aria2Client, Aria2Status
from app.services.event_bus import EventBus
from app.services.preflight import preflight
from app.services.settings_service import SettingsService
from app.services.transfer_service import TransferService

logger = get_logger("pullspool.download")

ACTIVE_STATUSES = ("queued", "active", "paused", "verifying")
RUNNING_STATUSES = ("active", "verifying")
DUPLICATE_WINDOW_SECONDS = 600
SHA256_CHUNK_SIZE = 1024 * 1024
MAX_ERROR_MESSAGE = 500
QUEUE_ALERT_CODE = "QUEUE_DISK_LOW"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(SHA256_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


class DownloadService:
    def __init__(
        self,
        config: AppConfig,
        database: Database,
        aria2: Aria2Client | None,
        events: EventBus,
        settings_service: SettingsService,
        transfers: TransferService | None = None,
    ) -> None:
        self._config = config
        self._db = database
        self._aria2 = aria2
        self._events = events
        self._settings_service = settings_service
        self._transfers = transfers
        self._root = config.download_root
        self._loops: list[asyncio.Task] = []
        self._background: set[asyncio.Task] = set()
        self._scheduler_lock = asyncio.Lock()
        self._queue_paused_reason: str | None = None
        self._engine_down = False

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    async def start(self) -> None:
        self._loops = [
            asyncio.create_task(self._sync_loop(), name="pullspool-sync"),
            asyncio.create_task(self._schedule_loop(), name="pullspool-scheduler"),
        ]

    async def stop(self) -> None:
        for loop in self._loops:
            loop.cancel()
        await asyncio.gather(*self._loops, return_exceptions=True)
        self._loops.clear()
        for task in list(self._background):
            task.cancel()
        if self._background:
            await asyncio.gather(*self._background, return_exceptions=True)
        self._background.clear()

    @property
    def queue_paused_reason(self) -> str | None:
        return self._queue_paused_reason

    def _track(self, coroutine) -> None:
        task = asyncio.create_task(coroutine)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    async def _settings(self):
        async with self._db.session() as session:
            return await self._settings_service.load(session)

    async def _add_event(
        self, session: AsyncSession, task_id: str, kind: str, message: str
    ) -> None:
        session.add(
            TaskEvent(
                task_id=task_id,
                kind=kind,
                message=message[:MAX_ERROR_MESSAGE],
                created_at=now_iso(),
            )
        )

    def _publish(self, event_type: str, task: Task, changed: list[str] | None = None) -> None:
        out = task_to_out(task)
        payload: dict[str, Any] = {"task": out.model_dump(mode="json")}
        if changed:
            payload["changed"] = changed
        self._events.publish(event_type, payload)

    async def _load(self, session: AsyncSession, user_id: int, task_id: str) -> Task:
        task = await session.get(Task, task_id)
        if task is None or task.user_id != user_id:
            raise AppError(ErrorCode.TASK_NOT_FOUND)
        return task

    async def _counts(self, session: AsyncSession, user_id: int) -> dict[str, int]:
        rows = await session.execute(
            select(Task.status, func.count())
            .where(Task.user_id == user_id, Task.deleted_at.is_(None))
            .group_by(Task.status)
        )
        counts = {
            "downloading": 0,
            "queued": 0,
            "paused": 0,
            "verifying": 0,
            "ready": 0,
            "failed": 0,
            "canceled": 0,
            "total": 0,
        }
        bucket_by_status = {
            "active": "downloading",
            "completed": "ready",
            "queued": "queued",
            "paused": "paused",
            "verifying": "verifying",
            "failed": "failed",
            "canceled": "canceled",
        }
        for status, count in rows.all():
            value = int(count)
            counts["total"] += value
            bucket = bucket_by_status.get(status)
            if bucket:
                counts[bucket] += value
        return counts

    # ------------------------------------------------------------------ #
    # creation
    # ------------------------------------------------------------------ #
    async def create(self, user_id: int, payload: CreateTaskRequest) -> tuple[TaskOut, bool]:
        settings = await self._settings()

        async with self._db.session() as session:
            active_count = await session.scalar(
                select(func.count())
                .select_from(Task)
                .where(Task.user_id == user_id, Task.status.in_(ACTIVE_STATUSES))
            )
            if int(active_count or 0) >= settings.queue_max_length:
                raise AppError(
                    ErrorCode.QUEUE_FULL,
                    f"排队任务已达上限（{settings.queue_max_length}）",
                    details={"queue_max_length": settings.queue_max_length},
                )
            duplicate = await self._find_duplicate(session, user_id, payload.url)
            if duplicate is not None:
                return task_to_out(duplicate), True

        result = await preflight(
            payload.url,
            allow_private=self._config.allow_private_hosts,
            verify_tls=self._config.preflight_verify_tls,
            timeout_seconds=self._config.preflight_timeout_seconds,
            connect_timeout=self._config.preflight_connect_timeout,
            max_redirects=self._config.preflight_max_redirects,
        )

        requested_max = payload.max_size_bytes or settings.max_file_size_bytes
        max_size = min(requested_max, settings.max_file_size_bytes)
        if result.content_length and result.content_length > max_size:
            raise AppError(
                ErrorCode.FILE_TOO_LARGE,
                "文件超过允许的大小上限",
                details={"size": result.content_length, "limit": max_size},
            )

        await self._check_storage(settings, result.content_length or 0)

        raw_name = payload.filename or result.filename or "download.bin"
        filename = storage_service.sanitize_filename(raw_name)
        task_id = str(uuid4())
        task = Task(
            id=task_id,
            user_id=user_id,
            url=payload.url,
            url_display=result.url_display,
            final_url=result.url,
            final_url_display=result.url_display,
            filename=filename,
            display_name=storage_service.sanitize_filename(payload.filename) if payload.filename else None,
            status="queued",
            file_size=result.content_length,
            content_type=result.content_type,
            supports_range=result.supports_range,
            etag=result.etag,
            expected_sha256=result.expected_sha256,
            max_connections=payload.connections or settings.default_connections,
            speed_limit_bytes=(payload.speed_limit_kib_per_s or settings.default_speed_limit_kib_per_s)
            * 1024,
            max_size_bytes=max_size,
            created_at=now_iso(),
        )

        async with self._db.session() as session:
            session.add(task)
            # Flush the parent row before writing events: SQLite enforces the
            # foreign key immediately and there is no ORM relationship to order
            # the two inserts for us.
            await session.flush()
            await self._add_event(session, task_id, "created", "任务已创建")
            await session.commit()

        self._publish("task.created", task)
        logger.info("task %s created for %s", task_id, result.url_display)
        return task_to_out(task), False

    async def _find_duplicate(
        self, session: AsyncSession, user_id: int, url: str
    ) -> Task | None:
        return await session.scalar(
            select(Task)
            .where(
                Task.user_id == user_id,
                Task.url == url,
                Task.created_at >= iso_plus(-DUPLICATE_WINDOW_SECONDS),
                Task.status.not_in(("failed", "canceled")),
            )
            .order_by(Task.created_at.desc())
            .limit(1)
        )

    async def _check_storage(self, settings, incoming_bytes: int) -> None:
        used = 0
        async with self._db.session() as session:
            estimated = func.coalesce(Task.file_size, Task.downloaded_size)
            used = int(
                await session.scalar(
                    select(func.coalesce(func.sum(estimated), 0)).where(
                        Task.deleted_at.is_(None)
                    )
                )
                or 0
            )
        if used + incoming_bytes > settings.max_total_storage_bytes:
            raise AppError(
                ErrorCode.QUOTA_EXCEEDED,
                "临时存储配额不足",
                details={"used": used, "limit": settings.max_total_storage_bytes},
            )
        _, _, free = storage_service.disk_usage(self._root)
        if free - incoming_bytes < settings.min_free_disk_bytes:
            raise AppError(
                ErrorCode.DISK_FULL,
                "磁盘剩余空间不足",
                details={"free": free, "reserved": settings.min_free_disk_bytes},
            )

    # ------------------------------------------------------------------ #
    # scheduling
    # ------------------------------------------------------------------ #
    async def _schedule_loop(self) -> None:
        while True:
            try:
                await self._schedule_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - defensive
                logger.exception("scheduler iteration failed")
            await asyncio.sleep(self._config.scheduler_interval_seconds)

    async def _schedule_once(self) -> None:
        if self._aria2 is None:
            return
        settings = await self._settings()
        async with self._scheduler_lock:
            _, _, free = storage_service.disk_usage(self._root)
            if free < settings.min_free_disk_bytes:
                if self._queue_paused_reason != "disk_low":
                    self._queue_paused_reason = "disk_low"
                    self._events.publish(
                        "alert",
                        {
                            "level": "error",
                            "code": QUEUE_ALERT_CODE,
                            "message": "磁盘剩余空间不足，下载队列已暂停",
                        },
                    )
                return
            if self._queue_paused_reason == "disk_low":
                self._queue_paused_reason = None
                self._events.publish(
                    "alert",
                    {"level": "info", "code": "QUEUE_RESUMED", "message": "磁盘空间恢复，继续下载"},
                )

            async with self._db.session() as session:
                running = await session.scalar(
                    select(func.count())
                    .select_from(Task)
                    .where(Task.status.in_(RUNNING_STATUSES))
                )
                slots = settings.max_concurrent_downloads - int(running or 0)
                if slots <= 0:
                    return
                queued_ids = list(
                    (
                        await session.scalars(
                            select(Task.id)
                            .where(Task.status == "queued")
                            .order_by(Task.created_at.asc())
                            .limit(slots)
                        )
                    ).all()
                )

        for task_id in queued_ids:
            try:
                await self._start_task(task_id)
            except AppError as exc:
                await self._fail_task(task_id, exc)
            except Exception:  # pragma: no cover - defensive
                logger.exception("failed to start task %s", task_id)
                await self._fail_task(
                    task_id, AppError(ErrorCode.INTERNAL_ERROR, "启动下载失败")
                )

    async def _start_task(self, task_id: str) -> None:
        async with self._db.session() as session:
            task = await session.get(Task, task_id)
            if task is None or task.status != "queued":
                return
            directory = storage_service.task_directory(self._root, task.id)
            directory.mkdir(parents=True, exist_ok=True)
            storage_service.safe_mode(directory, 0o750)
            filename = storage_service.ensure_unique_name(directory, task.filename)

            options = {
                "dir": str(directory),
                "out": filename,
                "continue": "true",
                "auto-file-renaming": "false",
                "allow-overwrite": "true",
                "split": str(max(1, task.max_connections)),
                "max-connection-per-server": str(max(1, task.max_connections)),
                "min-split-size": "8M",
            }
            if task.speed_limit_bytes > 0:
                options["max-download-limit"] = str(task.speed_limit_bytes)

            assert self._aria2 is not None
            gid = await self._aria2.add_uri([task.final_url or task.url], options)

            task.aria2_gid = gid
            task.filename = filename
            task.stored_relpath = f"{task.id}/{filename}"
            task.status = "active"
            task.started_at = task.started_at or now_iso()
            task.error_code = None
            task.error_message = None
            await self._add_event(session, task.id, "started", "开始下载")
            await session.commit()

        self._publish("task.updated", task, ["status", "aria2_gid"])
        logger.info("task %s started (gid=%s)", task_id, gid)

    async def _fail_task(self, task_id: str, error: AppError, *, status: str = "failed") -> None:
        async with self._db.session() as session:
            task = await session.get(Task, task_id)
            if task is None:
                return
            task.status = status
            task.error_code = error.code.value
            task.error_message = error.message[:MAX_ERROR_MESSAGE]
            task.download_speed = 0
            await self._add_event(session, task.id, "failed", error.message)
            await session.commit()
        self._publish("task.updated", task, ["status", "error"])
        logger.info("task %s failed: %s", task_id, error.code.value)

    # ------------------------------------------------------------------ #
    # progress synchronisation
    # ------------------------------------------------------------------ #
    async def _sync_loop(self) -> None:
        while True:
            try:
                await self._sync_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - defensive
                logger.exception("progress sync iteration failed")
            await asyncio.sleep(self._config.task_poll_interval_seconds)

    async def _sync_once(self) -> None:
        if self._aria2 is None:
            return
        async with self._db.session() as session:
            rows = (
                await session.scalars(
                    select(Task)
                    .where(Task.status.in_(("active", "paused")), Task.aria2_gid.is_not(None))
                    .order_by(Task.created_at.asc())
                )
            ).all()
            snapshot = [(task.id, task.aria2_gid, task.status) for task in rows]

        for task_id, gid, db_status in snapshot:
            try:
                status = await self._aria2.tell_status(gid)
            except AppError as exc:
                if exc.code is ErrorCode.ARIA2_UNAVAILABLE:
                    if not self._engine_down:
                        self._engine_down = True
                        self._events.publish(
                            "alert",
                            {
                                "level": "error",
                                "code": "ARIA2_UNAVAILABLE",
                                "message": "下载引擎不可用，进度同步已暂停",
                            },
                        )
                    return
                if int(exc.details.get("aria2_code", 0)) == 1:
                    await self._requeue_missing_gid(task_id)
                continue

            self._engine_down = False
            await self._apply_status(task_id, status, db_status)

    async def _apply_status(self, task_id: str, status: Aria2Status, db_status: str) -> None:
        async with self._db.session() as session:
            task = await session.get(Task, task_id)
            if task is None:
                return

            changed: list[str] = []
            if status.total_length > 0 and not task.file_size:
                task.file_size = status.total_length
                changed.append("file_size")
            if status.completed_length != task.downloaded_size:
                task.downloaded_size = status.completed_length
                changed.append("progress")
            if status.download_speed != task.download_speed:
                task.download_speed = status.download_speed
                changed.append("speed")
            task.last_synced_at = now_iso()

            if status.status == "complete" and task.status != "verifying":
                task.status = "verifying"
                task.download_speed = 0
                changed.append("status")
                await self._add_event(session, task.id, "completed", "下载完成，开始校验")
            elif status.status == "error" and task.status != "failed":
                task.status = "failed"
                task.download_speed = 0
                task.error_code = ARIA2_ERROR_CODES.get(
                    int(status.error_code or 0), ErrorCode.ARIA2_ERROR
                ).value
                task.error_message = (status.error_message or "下载失败")[:MAX_ERROR_MESSAGE]
                changed.append("status")
                await self._add_event(session, task.id, "failed", task.error_message)
            elif status.status == "paused" and db_status != "paused":
                task.status = "paused"
                task.download_speed = 0
                changed.append("status")
            elif status.status == "active" and db_status == "paused":
                task.status = "active"
                changed.append("status")

            await session.commit()

        if changed:
            self._publish("task.updated", task, changed)
        if status.status == "complete":
            self._track(self._verify_task(task_id))

    async def _requeue_missing_gid(self, task_id: str) -> None:
        async with self._db.session() as session:
            task = await session.get(Task, task_id)
            if task is None:
                return
            task.aria2_gid = None
            task.status = "queued"
            task.download_speed = 0
            await self._add_event(session, task.id, "reconciled", "下载引擎丢失任务，已重新排队")
            await session.commit()
        self._publish("task.updated", task, ["status"])
        logger.info("task %s requeued after aria2 lost its gid", task_id)

    # ------------------------------------------------------------------ #
    # verification
    # ------------------------------------------------------------------ #
    async def _verify_task(self, task_id: str) -> None:
        settings = await self._settings()
        async with self._db.session() as session:
            task = await session.get(Task, task_id)
            if task is None or task.status != "verifying":
                return
            if not task.stored_relpath:
                await self._fail_with_session(session, task, ErrorCode.FILE_NOT_FOUND, "文件路径缺失")
                return

            try:
                path = storage_service.resolve_inside(self._root, task.stored_relpath)
            except AppError as exc:
                await self._fail_with_session(session, task, exc.code, exc.message)
                return

            if not path.exists() or path.is_symlink() or not path.is_file():
                await self._fail_with_session(
                    session, task, ErrorCode.FILE_NOT_FOUND, "下载完成但文件不存在"
                )
                return

            actual_size = path.stat().st_size
            if actual_size <= 0:
                await self._fail_with_session(
                    session, task, ErrorCode.FILE_INTEGRITY_FAILED, "文件为空"
                )
                return
            if task.file_size and actual_size != task.file_size:
                await self._fail_with_session(
                    session,
                    task,
                    ErrorCode.FILE_INTEGRITY_FAILED,
                    f"文件大小不一致（期望 {task.file_size}，实际 {actual_size}）",
                )
                return

            sha256 = await asyncio.to_thread(_sha256_file, path)
            now = utc_now()
            task.sha256 = sha256
            task.sha256_computed_at = to_iso(now)
            task.file_size = actual_size
            task.downloaded_size = actual_size
            task.download_speed = 0
            task.status = "completed"
            task.completed_at = to_iso(now)
            task.expires_at = to_iso(now + timedelta(hours=settings.retention_hours))

            delta = max(0, actual_size - task.download_bytes_counted)
            if delta:
                await self._add_traffic(session, "down", delta)
                task.download_bytes_counted = actual_size

            await self._add_event(
                session, task.id, "verified", f"校验通过，SHA-256={sha256[:16]}…"
            )
            await session.commit()

        self._publish("task.updated", task, ["status", "sha256"])
        logger.info("task %s completed (%s bytes)", task_id, actual_size)

    async def _fail_with_session(
        self, session: AsyncSession, task: Task, code: ErrorCode, message: str
    ) -> None:
        task.status = "failed"
        task.error_code = code.value
        task.error_message = message[:MAX_ERROR_MESSAGE]
        task.download_speed = 0
        await self._add_event(session, task.id, "failed", message)
        await session.commit()
        self._publish("task.updated", task, ["status", "error"])

    async def _add_traffic(self, session: AsyncSession, direction: str, delta: int) -> None:
        day = local_day(tz_name=self._config.timezone)
        row = await session.scalar(
            select(TrafficDaily).where(
                TrafficDaily.day == day, TrafficDaily.direction == direction
            )
        )
        if row is None:
            session.add(TrafficDaily(day=day, direction=direction, bytes=delta))
        else:
            row.bytes += delta
        self._events.publish(
            "traffic.updated", {"day": day, "direction": direction, "bytes": delta}
        )

    # ------------------------------------------------------------------ #
    # queries
    # ------------------------------------------------------------------ #
    async def list_tasks(
        self,
        user_id: int,
        *,
        scope: str = "active",
        status: str | None = None,
        query: str | None = None,
        sort: str = "created_at",
        order: str = "desc",
        page: int = 1,
        page_size: int = 20,
    ) -> TaskListResponse:
        if scope not in SCOPE_VALUES:
            raise AppError(ErrorCode.VALIDATION_ERROR, "scope 不合法")
        if sort not in SORT_COLUMNS:
            raise AppError(ErrorCode.VALIDATION_ERROR, "排序字段不合法")
        page = max(1, page)
        page_size = min(100, max(1, page_size))

        conditions = [Task.user_id == user_id]
        if status:
            requested = [item.strip() for item in status.split(",") if item.strip()]
            allowed = {"queued", "active", "paused", "verifying", "completed", "failed", "canceled"}
            if not requested or any(item not in allowed for item in requested):
                raise AppError(ErrorCode.VALIDATION_ERROR, "status 不合法")
            conditions.append(Task.status.in_(requested))

        if scope == "active":
            conditions.append(Task.status.in_(("queued", "active", "paused", "verifying")))
        elif scope == "ready":
            conditions.append(Task.status == "completed")
            conditions.append(Task.deleted_at.is_(None))
        elif scope == "history":
            conditions.append(
                (Task.deleted_at.is_not(None)) | (Task.status.in_(("failed", "canceled")))
            )

        if query:
            needle = query.strip()
            if needle:
                conditions.append(
                    Task.filename.contains(needle, autoescape=True)
                    | Task.url_display.contains(needle, autoescape=True)
                )

        column = getattr(Task, sort)
        ordering = column.desc() if order == "desc" else column.asc()
        id_tiebreak = Task.id.desc() if order == "desc" else Task.id.asc()

        async with self._db.session() as session:
            total = int(
                await session.scalar(select(func.count()).select_from(Task).where(*conditions)) or 0
            )
            rows = (
                await session.scalars(
                    select(Task)
                    .where(*conditions)
                    .order_by(ordering, id_tiebreak)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                )
            ).all()
            counts = await self._counts(session, user_id)

        return TaskListResponse(
            items=[task_to_out(task) for task in rows],
            total=total,
            page=page,
            page_size=page_size,
            counts=counts,
        )

    async def get_task(self, user_id: int, task_id: str) -> TaskOut:
        async with self._db.session() as session:
            task = await self._load(session, user_id, task_id)
            return task_to_out(task)

    # ------------------------------------------------------------------ #
    # controls
    # ------------------------------------------------------------------ #
    async def pause(self, user_id: int, task_id: str) -> TaskOut:
        async with self._db.session() as session:
            task = await self._load(session, user_id, task_id)
            if task.status not in {"active", "queued"}:
                raise AppError(ErrorCode.TASK_STATE_CONFLICT, details={"status": task.status})
            if task.aria2_gid and self._aria2 is not None:
                try:
                    await self._aria2.pause(task.aria2_gid)
                except AppError as exc:
                    if exc.code is not ErrorCode.ARIA2_UNAVAILABLE:
                        raise
            task.status = "paused"
            task.download_speed = 0
            await self._add_event(session, task.id, "paused", "任务已暂停")
            await session.commit()
        self._publish("task.updated", task, ["status"])
        return task_to_out(task)

    async def resume(self, user_id: int, task_id: str) -> TaskOut:
        async with self._db.session() as session:
            task = await self._load(session, user_id, task_id)
            if task.status != "paused":
                raise AppError(ErrorCode.TASK_STATE_CONFLICT, details={"status": task.status})
            if task.aria2_gid and self._aria2 is not None:
                try:
                    await self._aria2.unpause(task.aria2_gid)
                    task.status = "active"
                except AppError:
                    task.aria2_gid = None
                    task.status = "queued"
            else:
                task.status = "queued"
            await self._add_event(session, task.id, "resumed", "任务已恢复")
            await session.commit()
        self._publish("task.updated", task, ["status"])
        return task_to_out(task)

    async def cancel(
        self, user_id: int, task_id: str, payload: CancelTaskRequest
    ) -> TaskOut:
        async with self._db.session() as session:
            task = await self._load(session, user_id, task_id)
            if task.status not in {"queued", "active", "paused"}:
                raise AppError(ErrorCode.TASK_STATE_CONFLICT, details={"status": task.status})
            if task.aria2_gid and self._aria2 is not None:
                try:
                    await self._aria2.remove(task.aria2_gid, force=True)
                    await self._aria2.purge_result(task.aria2_gid)
                except AppError:
                    logger.info("aria2 remove failed for %s (already gone?)", task.id)
            if payload.delete_files and task.stored_relpath:
                try:
                    storage_service.remove_task_tree(self._root, task.id)
                except AppError:
                    logger.warning("refused to delete task directory for %s", task.id)
            task.status = "canceled"
            task.download_speed = 0
            task.aria2_gid = None
            if payload.delete_files:
                task.deleted_at = now_iso()
                task.deleted_reason = "user_cancel"
            await self._add_event(session, task.id, "canceled", "任务已取消")
            await session.commit()
        self._publish("task.updated", task, ["status"])
        return task_to_out(task)

    async def retry(self, user_id: int, task_id: str) -> TaskOut:
        settings = await self._settings()
        async with self._db.session() as session:
            task = await self._load(session, user_id, task_id)
            if task.status != "failed":
                raise AppError(ErrorCode.TASK_STATE_CONFLICT, details={"status": task.status})
            if task.attempts >= self._config.max_task_attempts:
                raise AppError(
                    ErrorCode.TASK_STATE_CONFLICT,
                    f"重试次数已达上限（{self._config.max_task_attempts}）",
                    details={"attempts": task.attempts},
                )
            result = await preflight(
                task.url,
                allow_private=self._config.allow_private_hosts,
                verify_tls=self._config.preflight_verify_tls,
                timeout_seconds=self._config.preflight_timeout_seconds,
                connect_timeout=self._config.preflight_connect_timeout,
                max_redirects=self._config.preflight_max_redirects,
            )
            if result.content_length and result.content_length > settings.max_file_size_bytes:
                raise AppError(ErrorCode.FILE_TOO_LARGE)

            task.final_url = result.url
            task.final_url_display = result.url_display
            task.file_size = result.content_length
            task.content_type = result.content_type
            task.supports_range = result.supports_range
            task.etag = result.etag
            task.attempts += 1
            task.aria2_gid = None
            task.error_code = None
            task.error_message = None
            task.downloaded_size = 0
            task.download_speed = 0
            task.status = "queued"
            await self._add_event(session, task.id, "retried", f"第 {task.attempts} 次重试")
            await session.commit()
        self._publish("task.updated", task, ["status"])
        return task_to_out(task)

    async def delete(self, user_id: int, task_id: str, *, delete_files: bool) -> TaskOut:
        async with self._db.session() as session:
            task = await self._load(session, user_id, task_id)
            if task.status in {"active", "verifying"}:
                raise AppError(ErrorCode.TASK_STATE_CONFLICT, details={"status": task.status})
            if self._transfers is not None and self._transfers.is_transferring(task.id):
                raise AppError(ErrorCode.TRANSFER_IN_PROGRESS)
            if delete_files and task.stored_relpath:
                try:
                    storage_service.remove_task_tree(self._root, task.id)
                except AppError:
                    logger.warning("refused to delete task directory for %s", task.id)
            if task.deleted_at is None:
                task.deleted_at = now_iso()
                task.deleted_reason = task.deleted_reason or "admin"
                await self._add_event(session, task.id, "deleted", "任务记录已删除")
            await session.commit()
        self._publish("task.deleted", task)
        return task_to_out(task)

    async def get_entity(self, user_id: int, task_id: str) -> Task:
        async with self._db.session() as session:
            return await self._load(session, user_id, task_id)

    async def get_entity_any(self, task_id: str) -> Task:
        """Used by token-authenticated downloads; ownership was proven by the token."""
        async with self._db.session() as session:
            task = await session.get(Task, task_id)
            if task is None:
                raise AppError(ErrorCode.TASK_NOT_FOUND)
            return task

    async def acknowledge(self, user_id: int, task_id: str) -> TaskOut:
        async with self._db.session() as session:
            task = await self._load(session, user_id, task_id)
            if task.deleted_at is not None:
                return task_to_out(task)
            if task.status != "completed":
                raise AppError(ErrorCode.TASK_STATE_CONFLICT, details={"status": task.status})
            if self._transfers is not None and self._transfers.is_transferring(task.id):
                raise AppError(ErrorCode.TRANSFER_IN_PROGRESS)
            self._remove_files(task)
            now = now_iso()
            task.retrieved_at = task.retrieved_at or now
            task.deleted_at = now
            task.deleted_reason = "user_ack"
            await self._add_event(session, task.id, "retrieved", "用户确认取回并删除")
            await session.commit()
        self._publish("task.deleted", task)
        return task_to_out(task)

    async def expire_task(self, task_id: str) -> bool:
        async with self._db.session() as session:
            task = await session.get(Task, task_id)
            if task is None or task.deleted_at is not None or task.status != "completed":
                return False
            if self._transfers is not None and self._transfers.is_transferring(task_id):
                return False
            self._remove_files(task)
            task.deleted_at = now_iso()
            task.deleted_reason = "expired"
            await self._add_event(session, task.id, "expired", "等待取回超时，已自动清理")
            await session.commit()
        self._publish("task.deleted", task)
        return True

    def _remove_files(self, task: Task) -> None:
        if not task.stored_relpath:
            return
        try:
            storage_service.remove_task_tree(self._root, task.id)
        except AppError:
            logger.warning("refused to delete task directory for %s", task.id)

    # ------------------------------------------------------------------ #
    # startup reconciliation
    # ------------------------------------------------------------------ #
    async def reconcile(self) -> None:
        if self._aria2 is None:
            async with self._db.session() as session:
                pending = (
                    await session.scalars(
                        select(Task).where(Task.status.in_(("active", "paused")))
                    )
                ).all()
                for task in pending:
                    task.aria2_gid = None
                    if task.status != "paused":
                        task.status = "queued"
                if pending:
                    await session.commit()
            if pending:
                logger.info("reconciled %d task(s) without aria2", len(pending))
            return

        verify_ids: list[str] = []
        async with self._db.session() as session:
            pending = (
                await session.scalars(
                    select(Task).where(Task.status.in_(("active", "queued", "paused", "verifying")))
                )
            ).all()
            for task in pending:
                if task.status == "verifying":
                    verify_ids.append(task.id)
                    continue
                if not task.aria2_gid:
                    # A task paused while still queued has no gid; keep it paused
                    # instead of silently resuming it after a restart.
                    if task.status != "paused":
                        task.status = "queued"
                    continue
                try:
                    status = await self._aria2.tell_status(task.aria2_gid)
                except AppError as exc:
                    if int(exc.details.get("aria2_code", 0)) == 1:
                        task.aria2_gid = None
                        task.status = "queued"
                        await self._add_event(
                            session, task.id, "reconciled", "下载引擎重启后重新排队"
                        )
                    elif exc.code is ErrorCode.ARIA2_UNAVAILABLE:
                        task.status = "queued"
                    continue
                if status.status == "complete":
                    task.status = "verifying"
                    verify_ids.append(task.id)
                elif status.status == "error":
                    task.status = "failed"
                    task.error_code = ARIA2_ERROR_CODES.get(
                        int(status.error_code or 0), ErrorCode.ARIA2_ERROR
                    ).value
                    task.error_message = (status.error_message or "下载失败")[:MAX_ERROR_MESSAGE]
                else:
                    task.downloaded_size = status.completed_length
                    if status.total_length:
                        task.file_size = status.total_length
                    if status.status == "paused":
                        task.status = "paused"

            completed = (
                await session.scalars(
                    select(Task).where(Task.status == "completed", Task.deleted_at.is_(None))
                )
            ).all()
            for task in completed:
                if not task.stored_relpath:
                    continue
                try:
                    path = storage_service.resolve_inside(self._root, task.stored_relpath)
                except AppError:
                    path = None
                if path is None or not path.exists():
                    task.status = "failed"
                    task.error_code = ErrorCode.FILE_NOT_FOUND.value
                    task.error_message = "启动检查：文件已不存在"
                    await self._add_event(
                        session, task.id, "reconciled", "启动检查发现文件缺失，标记为失败"
                    )
            await session.commit()

        for task_id in verify_ids:
            self._track(self._verify_task(task_id))
        logger.info(
            "reconciled tasks: %d pending, %d to verify", len(pending), len(verify_ids)
        )
