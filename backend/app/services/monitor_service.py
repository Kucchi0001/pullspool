"""Host metrics, storage accounting and traffic aggregation."""

from __future__ import annotations

import os
import shutil
from datetime import date, timedelta
from pathlib import Path

import psutil
from sqlalchemy import func, select

from app.core.config import AppConfig
from app.core.timeutil import local_day, parse_iso, utc_now
from app.database.session import Database
from app.models.task import Task
from app.models.traffic import TrafficDaily
from app.services import storage_service
from app.services.aria2_service import Aria2Client
from app.services.download_service import DownloadService
from app.services.settings_service import SettingsService
from app.services.transfer_service import TransferService

TRAFFIC_NOTE = "应用层统计：仅统计 PullSpool 下载与回传字节，不等于运营商计费流量"


class MonitorService:
    def __init__(
        self,
        config: AppConfig,
        database: Database,
        aria2: Aria2Client | None,
        downloads: DownloadService,
        transfers: TransferService,
        settings_service: SettingsService,
    ) -> None:
        self._config = config
        self._db = database
        self._aria2 = aria2
        self._downloads = downloads
        self._transfers = transfers
        self._settings_service = settings_service

    # ------------------------------------------------------------------ #
    async def status(self, *, version: str, build: str, started_at: str) -> dict:
        async with self._db.session() as session:
            settings = await self._settings_service.load(session)
            counts = await self._counts(session)

        memory = psutil.virtual_memory()
        disk = shutil.disk_usage(self._config.download_root)
        load_avg: list[float] | None = None
        if hasattr(os, "getloadavg"):  # POSIX only
            try:
                load_avg = list(os.getloadavg())
            except OSError:  # pragma: no cover - defensive
                load_avg = None

        uptime = max(0, int((utc_now() - parse_iso(started_at)).total_seconds()))
        reachable = await self._aria2.is_alive() if self._aria2 is not None else False

        return {
            "server": {
                "version": version,
                "build": build,
                "started_at": started_at,
                "uptime_seconds": uptime,
            },
            "host": {
                "cpu_percent": psutil.cpu_percent(interval=0.05),
                "load_1": load_avg[0] if load_avg else None,
                "load_5": load_avg[1] if load_avg else None,
                "load_15": load_avg[2] if load_avg else None,
                "mem_total": memory.total,
                "mem_used": memory.used,
                "mem_percent": round(memory.percent, 1),
                "disk_total": disk.total,
                "disk_used": disk.used,
                "disk_free": disk.free,
            },
            "storage": {
                "root": str(self._config.download_root),
                "used_bytes": disk.used,
                "quota_bytes": settings.max_total_storage_bytes,
                "free_bytes": disk.free,
                "min_free_bytes": settings.min_free_disk_bytes,
                "orphan_count": self._orphan_count(),
            },
            "aria2": {
                "reachable": reachable,
                "guarded": self._guard_state(),
                "active": counts.get("downloading", 0),
                "waiting": counts.get("queued", 0),
                "stopped": counts.get("failed", 0),
            },
            "queue": {
                "active": counts.get("downloading", 0) + counts.get("verifying", 0),
                "max_concurrent": settings.max_concurrent_downloads,
                "paused_reason": self._downloads.queue_paused_reason,
                "transferring": self._transfers.total_active,
            },
            "counts": counts,
            "public_ip": self._config.public_ip or None,
        }

    async def storage(self) -> dict:
        disk = shutil.disk_usage(self._config.download_root)
        async with self._db.session() as session:
            settings = await self._settings_service.load(session)
            downloads_bytes = int(
                await session.scalar(
                    select(func.coalesce(func.sum(Task.downloaded_size), 0)).where(
                        Task.deleted_at.is_(None)
                    )
                )
                or 0
            )
            rows = (
                await session.scalars(
                    select(Task)
                    .where(Task.deleted_at.is_(None))
                    .order_by(Task.downloaded_size.desc())
                    .limit(20)
                )
            ).all()

        return {
            "root": str(self._config.download_root),
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
            "downloads_bytes": downloads_bytes,
            "quota_bytes": settings.max_total_storage_bytes,
            "min_free_bytes": settings.min_free_disk_bytes,
            "tasks": [
                {"id": task.id, "filename": task.filename, "bytes": task.downloaded_size}
                for task in rows
            ],
            "orphans": self._orphan_entries(),
        }

    async def traffic(self, *, days: int, timezone: str) -> dict:
        days = max(1, min(90, days))
        today = date.fromisoformat(local_day(tz_name=timezone))
        start = today - timedelta(days=days - 1)

        async with self._db.session() as session:
            rows = (
                await session.scalars(
                    select(TrafficDaily).where(TrafficDaily.day >= start.isoformat())
                )
            ).all()
            all_down = int(
                await session.scalar(
                    select(func.coalesce(func.sum(TrafficDaily.bytes), 0)).where(
                        TrafficDaily.direction == "down"
                    )
                )
                or 0
            )
            all_up = int(
                await session.scalar(
                    select(func.coalesce(func.sum(TrafficDaily.bytes), 0)).where(
                        TrafficDaily.direction == "up"
                    )
                )
                or 0
            )

        buckets: dict[str, dict[str, int]] = {}
        for row in rows:
            bucket = buckets.setdefault(row.day, {"download_bytes": 0, "upload_bytes": 0})
            if row.direction == "down":
                bucket["download_bytes"] += row.bytes
            else:
                bucket["upload_bytes"] += row.bytes

        series = []
        for offset in range(days):
            day = (start + timedelta(days=offset)).isoformat()
            bucket = buckets.get(day, {"download_bytes": 0, "upload_bytes": 0})
            series.append(
                {
                    "date": day,
                    "download_bytes": bucket["download_bytes"],
                    "upload_bytes": bucket["upload_bytes"],
                }
            )

        today_key = today.isoformat()
        month_prefix = today_key[:7]
        month_down = sum(
            bucket["download_bytes"] for day, bucket in buckets.items() if day.startswith(month_prefix)
        )
        month_up = sum(
            bucket["upload_bytes"] for day, bucket in buckets.items() if day.startswith(month_prefix)
        )

        nic = psutil.net_io_counters()
        return {
            "days": series,
            "totals": {
                "today_download_bytes": buckets.get(today_key, {}).get("download_bytes", 0),
                "today_upload_bytes": buckets.get(today_key, {}).get("upload_bytes", 0),
                "month_download_bytes": month_down,
                "month_upload_bytes": month_up,
                "all_download_bytes": all_down,
                "all_upload_bytes": all_up,
            },
            "nic": {
                "rx_bytes": nic.bytes_recv,
                "tx_bytes": nic.bytes_sent,
                "collected_at": local_day(tz_name=timezone),
            },
            "note": TRAFFIC_NOTE,
        }

    # ------------------------------------------------------------------ #
    async def _counts(self, session) -> dict[str, int]:
        rows = await session.execute(
            select(Task.status, func.count())
            .where(Task.deleted_at.is_(None))
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

    def _orphan_count(self) -> int:
        directory: Path = self._config.download_root / ".orphan"
        if not directory.exists():
            return 0
        try:
            return sum(1 for _ in directory.iterdir())
        except OSError:  # pragma: no cover - defensive
            return 0

    def _orphan_entries(self) -> list[dict]:
        directory: Path = self._config.download_root / ".orphan"
        if not directory.exists():
            return []
        entries: list[dict] = []
        for item in sorted(directory.iterdir())[:50]:
            try:
                size = storage_service.directory_size(item) if item.is_dir() else item.stat().st_size
                entries.append(
                    {
                        "path": f".orphan/{item.name}",
                        "bytes": size,
                        "quarantined_at": item.stat().st_mtime,
                    }
                )
            except OSError:  # pragma: no cover - defensive
                continue
        return entries

    def _guard_state(self) -> str:
        try:
            value = self._config.aria2_guard_status_file.read_text(encoding="utf-8").strip()
        except OSError:
            return "not_configured" if self._aria2 is None else "unknown"
        return value if value in {"ok", "failed", "disabled"} else "unknown"
