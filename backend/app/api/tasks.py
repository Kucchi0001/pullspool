"""Task endpoints (create, list, detail, controls)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import get_download_service, get_ready_user
from app.core.rate_limit import limiter
from app.models.user import User
from app.schemas.task import (
    CancelTaskRequest,
    CreateTaskRequest,
    TaskCreatedResponse,
    TaskListResponse,
    TaskResponse,
)
from app.services.download_service import DownloadService

router = APIRouter(prefix="/tasks", tags=["tasks"])

CREATE_LIMIT = 10
CREATE_WINDOW_SECONDS = 60


@router.post("", status_code=201, response_model=TaskCreatedResponse)
async def create_task(
    payload: CreateTaskRequest,
    response: Response,
    user: User = Depends(get_ready_user),
    service: DownloadService = Depends(get_download_service),
) -> TaskCreatedResponse:
    limiter.enforce(f"task:create:{user.id}", CREATE_LIMIT, CREATE_WINDOW_SECONDS)
    task, duplicate = await service.create(user.id, payload)
    if duplicate:
        response.status_code = 200
    return TaskCreatedResponse(task=task, duplicate=duplicate)


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    scope: str = Query("active"),
    status: str | None = Query(None),
    q: str | None = Query(None, max_length=100),
    sort: str = Query("created_at"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: User = Depends(get_ready_user),
    service: DownloadService = Depends(get_download_service),
) -> TaskListResponse:
    return await service.list_tasks(
        user.id,
        scope=scope,
        status=status,
        query=q,
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
    )


@router.get("/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    user: User = Depends(get_ready_user),
    service: DownloadService = Depends(get_download_service),
) -> TaskResponse:
    return TaskResponse(task=await service.get_task(user.id, task_id))


@router.post("/{task_id}/pause", response_model=TaskResponse)
async def pause_task(
    task_id: str,
    user: User = Depends(get_ready_user),
    service: DownloadService = Depends(get_download_service),
) -> TaskResponse:
    return TaskResponse(task=await service.pause(user.id, task_id))


@router.post("/{task_id}/resume", response_model=TaskResponse)
async def resume_task(
    task_id: str,
    user: User = Depends(get_ready_user),
    service: DownloadService = Depends(get_download_service),
) -> TaskResponse:
    return TaskResponse(task=await service.resume(user.id, task_id))


@router.post("/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(
    task_id: str,
    payload: CancelTaskRequest | None = None,
    user: User = Depends(get_ready_user),
    service: DownloadService = Depends(get_download_service),
) -> TaskResponse:
    return TaskResponse(
        task=await service.cancel(user.id, task_id, payload or CancelTaskRequest())
    )


@router.post("/{task_id}/retry", response_model=TaskResponse)
async def retry_task(
    task_id: str,
    user: User = Depends(get_ready_user),
    service: DownloadService = Depends(get_download_service),
) -> TaskResponse:
    return TaskResponse(task=await service.retry(user.id, task_id))


@router.delete("/{task_id}", response_model=TaskResponse)
async def delete_task(
    task_id: str,
    delete_files: bool = Query(True),
    user: User = Depends(get_ready_user),
    service: DownloadService = Depends(get_download_service),
) -> TaskResponse:
    return TaskResponse(
        task=await service.delete(user.id, task_id, delete_files=delete_files)
    )
