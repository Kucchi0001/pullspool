"""Async engine, session factory and SQLite pragmas."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.logging import get_logger

logger = get_logger("pullspool.db")

PRAGMAS = (
    "journal_mode=WAL",
    "synchronous=NORMAL",
    "busy_timeout=5000",
    "foreign_keys=ON",
    "temp_store=MEMORY",
)


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        self.engine: AsyncEngine = create_async_engine(
            url,
            echo=False,
            pool_pre_ping=True,
            connect_args={"timeout": 5},
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

    async def initialize(self) -> None:
        async with self.engine.begin() as connection:
            for pragma in PRAGMAS:
                await connection.exec_driver_sql(f"PRAGMA {pragma};")
        logger.info("database ready: %s", self.url.split("///")[0] + "///…")

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        session = self.session_factory()
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def dispose(self) -> None:
        await self.engine.dispose()
