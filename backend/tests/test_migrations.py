"""The Alembic baseline must create every table the application expects."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from app.core.config import AppConfig
from app.database.migrate import run_migrations

EXPECTED_TABLES = {
    "users",
    "sessions",
    "tasks",
    "task_events",
    "traffic_daily",
    "settings",
    "alembic_version",
}


def test_alembic_upgrade_creates_schema(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    db_path = tmp_path / "migrated.db"
    config = AppConfig(
        app_env="test",
        data_dir=data_dir,
        download_root=data_dir / "downloads",
        database_url=f"sqlite+aiosqlite:///{db_path.as_posix()}",
        tls_mode="off",
        log_level="ERROR",
    )

    asyncio.run(run_migrations(config))

    assert db_path.exists()
    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        version = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        indexes = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
        }

    assert tables >= EXPECTED_TABLES
    assert version is not None and version[0] == "0001"
    assert "ix_tasks_expires_pending" in indexes
    assert "ix_tasks_user_status" in indexes

def test_migrations_do_not_reset_application_logging(tmp_path: Path) -> None:
    import logging

    from app.core.logging import RedactingFormatter, setup_logging

    root = logging.getLogger()
    previous_handlers = list(root.handlers)
    previous_level = root.level
    try:
        setup_logging("INFO", "text")
        config = AppConfig(
            app_env="test",
            data_dir=tmp_path / "data2",
            download_root=tmp_path / "data2" / "downloads",
            database_url=f"sqlite+aiosqlite:///{(tmp_path / 'logging.db').as_posix()}",
            tls_mode="off",
            log_level="INFO",
        )
        asyncio.run(run_migrations(config))
        assert root.level == logging.INFO
        assert any(isinstance(handler.formatter, RedactingFormatter) for handler in root.handlers)
    finally:
        root.handlers[:] = previous_handlers
        root.setLevel(previous_level)
