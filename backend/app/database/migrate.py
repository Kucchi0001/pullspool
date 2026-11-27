"""Run Alembic migrations on startup, with a pre-migration database backup."""

from __future__ import annotations

import asyncio
import contextlib
import sqlite3
from datetime import datetime
from pathlib import Path

from alembic.config import Config as AlembicConfig

from alembic import command
from app.core.config import AppConfig
from app.core.logging import get_logger

logger = get_logger("pullspool.migrate")

BACKEND_ROOT = Path(__file__).resolve().parents[2]
MAX_BACKUPS = 3


def _alembic_config(config: AppConfig) -> AlembicConfig:
    cfg = AlembicConfig(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", config.sync_database_url)
    # Keep the application's logging configuration (redaction, level, format).
    cfg.attributes["configure_logger"] = False
    return cfg


def _backup_database(config: AppConfig) -> None:
    db_path = config.db_path
    if not db_path.exists():
        return
    backup_dir = config.data_dir / "db" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"pullspool-{datetime.now():%Y%m%d-%H%M%S}.db"
    source = sqlite3.connect(db_path)
    try:
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
    finally:
        source.close()

    backups = sorted(backup_dir.glob("pullspool-*.db"))
    for stale in backups[:-MAX_BACKUPS]:
        with contextlib.suppress(OSError):
            stale.unlink()


def _upgrade_sync(config: AppConfig) -> None:
    _backup_database(config)
    command.upgrade(_alembic_config(config), "head")


async def run_migrations(config: AppConfig) -> None:
    try:
        await asyncio.to_thread(_upgrade_sync, config)
    except Exception:
        logger.exception("数据库迁移失败，服务将退出")
        raise
    logger.info("数据库迁移完成")
