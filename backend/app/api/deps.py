"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppConfig
from app.core.errors import AppError, ErrorCode
from app.database.session import Database
from app.models.user import User
from app.schemas.settings import RuntimeSettings
from app.services.auth_service import resolve_session
from app.services.download_service import DownloadService
from app.services.monitor_service import MonitorService
from app.services.settings_service import SettingsService
from app.services.transfer_service import TransferService


def get_config(request: Request) -> AppConfig:
    return request.app.state.config


def get_settings_service(request: Request) -> SettingsService:
    return request.app.state.settings_service


def get_download_service(request: Request) -> DownloadService:
    service = getattr(request.app.state, "downloads", None)
    if service is None:
        raise AppError(ErrorCode.ARIA2_UNAVAILABLE, "下载服务尚未就绪")
    return service


def get_transfer_service(request: Request) -> TransferService:
    service = getattr(request.app.state, "transfers", None)
    if service is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, "回传服务尚未就绪")
    return service


def get_monitor_service(request: Request) -> MonitorService:
    service = getattr(request.app.state, "monitor", None)
    if service is None:
        raise AppError(ErrorCode.INTERNAL_ERROR, "监控服务尚未就绪")
    return service


async def get_db(request: Request) -> AsyncIterator[AsyncSession]:
    database: Database = request.app.state.db
    async with database.session() as session:
        yield session


async def get_runtime_settings(
    request: Request, db: AsyncSession = Depends(get_db)
) -> RuntimeSettings:
    service: SettingsService = request.app.state.settings_service
    return await service.load(db)


def client_ip(request: Request, config: AppConfig) -> str:
    """Resolve the caller IP.

    Only Caddy/nginx can reach the backend (port 8000 is never published), so
    trusting ``X-Forwarded-For`` is safe when ``TRUST_PROXY_HEADERS`` is on.
    """
    if config.trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            candidate = forwarded.split(",")[0].strip()
            if candidate:
                return candidate
    if request.client is not None:
        return request.client.host
    return "unknown"


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
    config: AppConfig = Depends(get_config),
    settings: RuntimeSettings = Depends(get_runtime_settings),
) -> User:
    token = request.cookies.get(config.cookie_name)
    resolved = await resolve_session(db, token, settings)
    if resolved is None:
        raise AppError(ErrorCode.SESSION_EXPIRED if token else ErrorCode.AUTH_REQUIRED)
    user, session_row = resolved
    request.state.session_token = token
    request.state.session_id = session_row.id
    return user


async def get_optional_user(request: Request) -> User | None:
    """Resolve the session cookie if present; never raises for anonymous callers."""
    db: Database = request.app.state.db
    config: AppConfig = request.app.state.config
    service: SettingsService = request.app.state.settings_service
    async with db.session() as session:
        settings = await service.load(session)
        token = request.cookies.get(config.cookie_name)
        resolved = await resolve_session(session, token, settings)
    return resolved[0] if resolved is not None else None


async def get_ready_user(user: User = Depends(get_current_user)) -> User:
    """Authenticated user that already completed the mandatory password change."""
    if user.must_change_password:
        raise AppError(ErrorCode.PASSWORD_CHANGE_REQUIRED)
    return user
