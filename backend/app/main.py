"""Application factory."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import AppConfig
from app.core.errors import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.middleware import (
    ApiRateLimitMiddleware,
    BodySizeLimitMiddleware,
    OriginCheckMiddleware,
    RequestContextMiddleware,
)
from app.core.timeutil import now_iso
from app.database.base import Base
from app.database.migrate import run_migrations
from app.database.session import Database
from app.services import auth_service
from app.services.aria2_service import Aria2Client
from app.services.cleanup_service import CleanupService
from app.services.download_service import DownloadService
from app.services.event_bus import EventBus
from app.services.monitor_service import MonitorService
from app.services.settings_service import SettingsService
from app.services.transfer_service import TransferService

BUILD = "2026.11.26"
ARIA2_SECRET_WAIT_ATTEMPTS = 5
logger = get_logger("pullspool")


async def _create_aria2_client(config: AppConfig) -> Aria2Client | None:
    """Wait briefly for the secret file written by the aria2 container."""
    attempts = 1 if config.app_env == "test" else ARIA2_SECRET_WAIT_ATTEMPTS
    for attempt in range(attempts):
        secret = config.aria2_secret_value
        if secret:
            return Aria2Client(
                config.aria2_rpc_url, secret, timeout_seconds=config.aria2_timeout_seconds
            )
        if attempt < attempts - 1:
            await asyncio.sleep(1)
    return None


def create_app(config: AppConfig | None = None) -> FastAPI:
    cfg = config or AppConfig()
    # Keep database, token and downloaded files private to the service user.
    os.umask(0o077)
    setup_logging(cfg.log_level, cfg.log_format)
    cfg.ensure_directories()

    database = Database(cfg.database_url)
    settings_service = SettingsService()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Re-apply logging once uvicorn has finished configuring its own
        # handlers; otherwise uvicorn.access can re-enable itself and write raw
        # query strings (download tokens) to the logs.
        setup_logging(cfg.log_level, cfg.log_format)
        await database.initialize()

        if cfg.app_env == "test":
            async with database.engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
        elif cfg.run_migrations_on_startup:
            await run_migrations(cfg)

        app.state.started_at = now_iso()
        async with database.session() as session:
            await settings_service.ensure_defaults(session)
            created = await auth_service.ensure_bootstrap_admin(session, cfg)
            if created:
                app.state.bootstrap_created = True

        aria2_client = await _create_aria2_client(cfg)
        if aria2_client is None:
            logger.warning("aria2 RPC 密钥不可用，下载功能将返回 ARIA2_UNAVAILABLE")
        app.state.aria2 = aria2_client

        transfers = TransferService(cfg, database, app.state.events, settings_service)
        downloads = DownloadService(
            cfg, database, app.state.aria2, app.state.events, settings_service, transfers
        )
        monitor = MonitorService(
            cfg, database, app.state.aria2, downloads, transfers, settings_service
        )
        cleanup = CleanupService(
            cfg, database, app.state.events, settings_service, transfers, downloads
        )
        app.state.transfers = transfers
        app.state.downloads = downloads
        app.state.monitor = monitor
        app.state.cleanup = cleanup

        await downloads.reconcile()
        await downloads.start()
        await cleanup.start()

        logger.info(
            "PullSpool %s 启动完成（env=%s，tls=%s）", cfg.version, cfg.app_env, cfg.tls_mode
        )
        try:
            yield
        finally:
            await cleanup.stop()
            await downloads.stop()
            aria2_client = getattr(app.state, "aria2", None)
            if aria2_client is not None:
                await aria2_client.close()
            await database.dispose()
            logger.info("PullSpool 已停止")

    app = FastAPI(
        title="PullSpool",
        version=cfg.version,
        lifespan=lifespan,
        docs_url=None if cfg.is_production else "/docs",
        redoc_url=None,
        openapi_url=None if cfg.is_production else "/openapi.json",
    )

    app.state.config = cfg
    app.state.db = database
    app.state.settings_service = settings_service
    app.state.events = EventBus()
    app.state.downloads = None
    app.state.transfers = None
    app.state.monitor = None
    app.state.cleanup = None
    app.state.build = BUILD
    app.state.started_at = now_iso()
    app.state.aria2 = None
    app.state.bootstrap_created = False

    register_exception_handlers(app)

    # Order matters: the last added middleware is the outermost one.
    app.add_middleware(
        ApiRateLimitMiddleware,
        limit_per_minute=cfg.api_rate_limit_per_minute,
        trust_proxy=cfg.trust_proxy_headers,
    )
    app.add_middleware(
        OriginCheckMiddleware,
        allowed_origins=[cfg.public_base_url] if cfg.public_base_url else [],
    )
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=cfg.max_json_body_bytes)
    app.add_middleware(RequestContextMiddleware)

    app.include_router(api_router)
    return app


# The container starts uvicorn with ``--factory`` so that configuration errors
# surface as a clear startup message instead of an import-time traceback.
