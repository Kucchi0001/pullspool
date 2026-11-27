"""Alembic environment. Uses the app metadata and a synchronous SQLite URL."""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, pool

# Make ``app`` importable when alembic runs from the backend directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database.base import Base  # noqa: E402
import app.models  # noqa: E402,F401  (registers every table)

config = context.config

# Only configure logging when Alembic is run from the CLI. When the app runs
# migrations in-process, fileConfig would replace the application's redacting
# log handlers and reset the root level to WARNING.
if config.config_file_name is not None and config.attributes.get(
    "configure_logger", True
):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _database_url() -> str:
    """Prefer the URL injected by the application, then env, then default."""
    configured = config.get_main_option("sqlalchemy.url") or ""
    if configured and "driver://" not in configured:
        return configured.replace("sqlite+aiosqlite:///", "sqlite:///")

    env_url = os.environ.get("DATABASE_URL", "")
    if env_url:
        return env_url.replace("sqlite+aiosqlite:///", "sqlite:///")

    data_dir = Path(os.environ.get("DATA_DIR", "/data"))
    return f"sqlite:///{(data_dir / 'db' / 'pullspool.db').as_posix()}"


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = create_engine(_database_url(), poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
