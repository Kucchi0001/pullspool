"""Periodic cleanup: expired retrievals, orphan directories, stale sessions."""

from __future__ import annotations

import asyncio
import shutil
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import delete, select

from app.core.config import AppConfig
from app.core.logging import get_logger
from app.core.timeutil import now_iso, to_iso, utc_now
from app.database.session import Database
from app.models.session import AuthSession
from app.models.task import Task
from app.services.download_service import DownloadService
from app.services.event_bus import EventBus
from app.services.settings_service import SettingsService
from app.services.transfer_service import TransferService

logger = get_logger("pullspool.cleanup")

ORPHAN_DIR = ".orphan"


class CleanupService:
    def __init__(
        self,
        config: AppConfig,
        database: Database,
        events: EventBus,
        settings_service: SettingsService,
        transfers: TransferService,
        downloads: DownloadService,
    ) -> None:
        self._config = config
        self._db = database
        self._events = events
        self._settings_service = settings_service
        self._transfers = transfers
        self._downloads = downloads
        self._loop_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._config.app_env == "test":
            return
        self._loop_task = asyncio.create_task(self._loop(), name="pullspool-cleanup")

    async def stop(self) -> None:
        if self._loop_task is not None:
            self._loop_task.cancel()
            await asyncio.gather(self._loop_task, return_exceptions=True)
            self._loop_task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:  # pragma: no cover - defensive
                logger.exception("cleanup iteration failed")
            await asyncio.sleep(self._config.cleanup_interval_seconds)

    async def run_once(self) -> dict[str, int]:
        async with self._db.session() as session:
            settings = await self._settings_service.load(session)
        expired = await self._expire_tasks()
        orphans = await self._clean_orphans(settings.orphan_quarantine_hours)
        sessions = await self._clean_sessions()
        if expired or orphans or sessions:
            logger.info(
                "cleanup: %d expired, %d orphan dirs, %d sessions",
                expired,
                orphans,
                sessions,
            )
        return {"expired": expired, "orphans": orphans, "sessions": sessions}

    # ------------------------------------------------------------------ #
    async def _expire_tasks(self) -> int:
        async with self._db.session() as session:
            task_ids = list(
                (
                    await session.scalars(
                        select(Task.id).where(
                            Task.status == "completed",
                            Task.deleted_at.is_(None),
                            Task.expires_at.is_not(None),
                            Task.expires_at <= now_iso(),
                        )
                    )
                ).all()
            )
        expired = 0
        for task_id in task_ids:
            if await self._downloads.expire_task(task_id):
                expired += 1
        return expired

    async def _clean_orphans(self, quarantine_hours: int) -> int:
        root: Path = self._config.download_root
        if not root.exists():
            return 0

        async with self._db.session() as session:
            known = set((await session.scalars(select(Task.id))).all())

        orphan_root = root / ORPHAN_DIR
        moved = 0
        for entry in list(root.iterdir()):
            if entry.name.startswith(".") or not entry.is_dir():
                continue
            if entry.name in known:
                continue
            orphan_root.mkdir(parents=True, exist_ok=True)
            destination = orphan_root / f"{int(time.time())}-{entry.name}"
            try:
                shutil.move(str(entry), str(destination))
                moved += 1
                logger.warning("quarantined orphan directory %s", entry.name)
            except OSError:
                logger.exception("failed to quarantine orphan directory %s", entry)

        if orphan_root.exists():
            cutoff = time.time() - quarantine_hours * 3600
            for candidate in list(orphan_root.iterdir()):
                try:
                    if candidate.stat().st_mtime >= cutoff:
                        continue
                    if candidate.is_dir():
                        shutil.rmtree(candidate, ignore_errors=True)
                    else:
                        candidate.unlink(missing_ok=True)
                except OSError:  # pragma: no cover - best effort
                    logger.warning("failed to purge orphan %s", candidate)
        return moved

    async def _clean_sessions(self) -> int:
        cutoff = to_iso(utc_now() - timedelta(days=self._config.session_retention_days))
        async with self._db.session() as session:
            result = await session.execute(
                delete(AuthSession).where(
                    (AuthSession.expires_at < cutoff)
                    | (AuthSession.revoked_at.is_not(None) & (AuthSession.revoked_at < cutoff))
                )
            )
            await session.commit()
            return int(result.rowcount or 0)
