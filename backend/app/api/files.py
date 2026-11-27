"""File retrieval, download tokens, acknowledgement and integrity."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query, Request
from starlette.responses import StreamingResponse

from app.api.deps import (
    get_config,
    get_download_service,
    get_optional_user,
    get_ready_user,
    get_runtime_settings,
    get_transfer_service,
)
from app.core.config import AppConfig
from app.core.errors import AppError, ErrorCode
from app.core.rate_limit import limiter
from app.core.security import issue_download_token, verify_download_token
from app.core.timeutil import to_iso
from app.models.user import User
from app.schemas.settings import RuntimeSettings
from app.schemas.task import (
    AckRequest,
    DownloadTokenRequest,
    DownloadTokenResponse,
    IntegrityResponse,
    TaskResponse,
)
from app.services.download_service import DownloadService
from app.services.transfer_service import TransferService

router = APIRouter(prefix="/tasks", tags=["files"])

TOKEN_ISSUE_LIMIT = 20
TOKEN_ISSUE_WINDOW_SECONDS = 60


@router.get("/{task_id}/file")
async def download_file(
    task_id: str,
    request: Request,
    token: str | None = Query(None),
    config: AppConfig = Depends(get_config),
    settings: RuntimeSettings = Depends(get_runtime_settings),
    service: DownloadService = Depends(get_download_service),
    transfers: TransferService = Depends(get_transfer_service),
) -> StreamingResponse:
    if token:
        payload = verify_download_token(token, config.download_token_secret)
        if payload.get("tid") != task_id:
            raise AppError(ErrorCode.FORBIDDEN, "下载令牌与任务不匹配")
        task = await service.get_entity_any(task_id)
    else:
        user = await get_optional_user(request)
        if user is None:
            raise AppError(ErrorCode.AUTH_REQUIRED)
        task = await service.get_entity(user.id, task_id)

    if task.status != "completed" or task.deleted_at is not None:
        raise AppError(ErrorCode.FILE_NOT_FOUND, "文件不存在或已被清理")

    return await transfers.prepare(task, request)


@router.post("/{task_id}/download-token", response_model=DownloadTokenResponse)
async def create_download_token(
    task_id: str,
    request: Request,
    payload: DownloadTokenRequest | None = None,
    config: AppConfig = Depends(get_config),
    settings: RuntimeSettings = Depends(get_runtime_settings),
    service: DownloadService = Depends(get_download_service),
    user: User = Depends(get_ready_user),
) -> DownloadTokenResponse:
    limiter.enforce(
        f"token:{user.id}", TOKEN_ISSUE_LIMIT, TOKEN_ISSUE_WINDOW_SECONDS
    )
    task = await service.get_entity(user.id, task_id)
    if task.status != "completed" or task.deleted_at is not None:
        raise AppError(ErrorCode.FILE_NOT_FOUND, "文件不存在或已被清理")

    ttl = payload.ttl_seconds if payload and payload.ttl_seconds else settings.download_token_ttl_seconds
    token, expires_at = issue_download_token(task.id, config.download_token_secret, ttl)
    base = config.public_base_url or str(request.base_url).rstrip("/")
    return DownloadTokenResponse(
        url=f"{base}/api/tasks/{task.id}/file?token={token}",
        expires_at=to_iso(datetime.fromtimestamp(expires_at, tz=UTC)),
        ttl_seconds=ttl,
    )


@router.post("/{task_id}/ack", response_model=TaskResponse)
async def acknowledge_task(
    task_id: str,
    payload: AckRequest | None = None,
    service: DownloadService = Depends(get_download_service),
    user: User = Depends(get_ready_user),
) -> TaskResponse:
    if payload is not None and payload.confirm is False:
        raise AppError(ErrorCode.VALIDATION_ERROR, "需要确认后才能删除文件")
    return TaskResponse(task=await service.acknowledge(user.id, task_id))


@router.get("/{task_id}/integrity", response_model=IntegrityResponse)
async def task_integrity(
    task_id: str,
    service: DownloadService = Depends(get_download_service),
    user: User = Depends(get_ready_user),
) -> IntegrityResponse:
    task = await service.get_entity(user.id, task_id)
    if task.sha256 is None:
        raise AppError(ErrorCode.TASK_STATE_CONFLICT, "文件尚未完成校验")

    matches = None
    if task.expected_sha256 and task.sha256:
        matches = task.expected_sha256.lower() == task.sha256.lower()
    return IntegrityResponse(
        task_id=task.id,
        sha256=task.sha256,
        file_size=task.file_size,
        verified_at=task.sha256_computed_at,
        expected_sha256=task.expected_sha256,
        matches_expected=matches,
    )
