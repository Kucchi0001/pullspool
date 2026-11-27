"""Runtime settings endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_config, get_db, get_ready_user, get_settings_service
from app.core.config import AppConfig
from app.models.user import User
from app.schemas.settings import (
    SettingsMeta,
    SettingsPatch,
    SettingsResponse,
    SettingsUpdateResponse,
)
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/settings", tags=["settings"])


def _meta(request: Request, config: AppConfig) -> SettingsMeta:
    return SettingsMeta(
        storage_root=str(config.download_root),
        storage_subdir=config.download_root.name,
        tls_mode=config.tls_mode,
        public_base_url=config.public_base_url,
        version=config.version,
        build=request.app.state.build,
        read_only_keys=["storage_subdir"],
    )


@router.get("", response_model=SettingsResponse)
async def read_settings(
    request: Request,
    db: AsyncSession = Depends(get_db),
    config: AppConfig = Depends(get_config),
    service: SettingsService = Depends(get_settings_service),
    _: User = Depends(get_ready_user),
) -> SettingsResponse:
    current = await service.load(db)
    return SettingsResponse(settings=current, meta=_meta(request, config))


@router.put("", response_model=SettingsUpdateResponse)
async def update_settings(
    payload: SettingsPatch,
    request: Request,
    db: AsyncSession = Depends(get_db),
    config: AppConfig = Depends(get_config),
    service: SettingsService = Depends(get_settings_service),
    _: User = Depends(get_ready_user),
) -> SettingsUpdateResponse:
    updated, applied = await service.update(db, payload)
    return SettingsUpdateResponse(settings=updated, applied=applied)
