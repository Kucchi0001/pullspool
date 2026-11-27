"""System status, storage and traffic endpoints."""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import get_config, get_monitor_service, get_ready_user
from app.core.config import AppConfig
from app.core.errors import AppError, ErrorCode
from app.models.user import User
from app.services.monitor_service import MonitorService

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status")
async def system_status(
    request: Request,
    config: AppConfig = Depends(get_config),
    monitor: MonitorService = Depends(get_monitor_service),
    _: User = Depends(get_ready_user),
) -> dict:
    return await monitor.status(
        version=config.version,
        build=request.app.state.build,
        started_at=request.app.state.started_at,
    )


@router.get("/storage")
async def system_storage(
    monitor: MonitorService = Depends(get_monitor_service),
    _: User = Depends(get_ready_user),
) -> dict:
    return await monitor.storage()


@router.get("/traffic")
async def system_traffic(
    days: int = Query(7, ge=1, le=90),
    tz: str | None = Query(None, max_length=64),
    config: AppConfig = Depends(get_config),
    monitor: MonitorService = Depends(get_monitor_service),
    _: User = Depends(get_ready_user),
) -> dict:
    timezone = tz or config.timezone
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise AppError(ErrorCode.VALIDATION_ERROR, "时区不合法") from None
    return await monitor.traffic(days=days, timezone=timezone)
