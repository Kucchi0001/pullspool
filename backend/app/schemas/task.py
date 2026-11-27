"""Task request/response models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.timeutil import parse_iso, utc_now


class CreateTaskRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4096)
    filename: str | None = Field(default=None, max_length=255)
    connections: int | None = Field(default=None, ge=1, le=16)
    speed_limit_kib_per_s: int | None = Field(default=None, ge=0, le=1_048_576)
    max_size_bytes: int | None = Field(default=None, ge=1024, le=100 * 1024**3)


class CancelTaskRequest(BaseModel):
    delete_files: bool = False


class AckRequest(BaseModel):
    confirm: bool = True


class IntegrityResponse(BaseModel):
    task_id: str
    sha256: str | None = None
    file_size: int | None = None
    verified_at: str | None = None
    expected_sha256: str | None = None
    matches_expected: bool | None = None
    note: str = "哈希由 VPS 对本地文件计算；不代表源站内容正确"


class DownloadTokenRequest(BaseModel):
    ttl_seconds: int | None = Field(default=None, ge=60, le=3600)


class DownloadTokenResponse(BaseModel):
    url: str
    expires_at: str
    ttl_seconds: int


class TaskOut(BaseModel):
    id: str
    url_display: str
    filename: str
    display_name: str | None = None
    status: str
    ui_status: str
    file_size: int | None = None
    downloaded_size: int = 0
    progress: float | None = None
    download_speed: int = 0
    eta_seconds: int | None = None
    sha256: str | None = None
    content_type: str | None = None
    supports_range: bool | None = None
    error_code: str | None = None
    error_message: str | None = None
    attempts: int = 0
    max_connections: int = 4
    speed_limit_bytes: int = 0
    download_bytes: int = 0
    retrieved_bytes: int = 0
    transfer_count: int = 0
    is_file_available: bool = False
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    retrieved_at: str | None = None
    deleted_at: str | None = None
    expires_at: str | None = None


class TaskListResponse(BaseModel):
    items: list[TaskOut]
    total: int
    page: int
    page_size: int
    counts: dict[str, int] = Field(default_factory=dict)


class TaskResponse(BaseModel):
    task: TaskOut


class TaskCreatedResponse(BaseModel):
    task: TaskOut
    duplicate: bool = False


SCOPE_VALUES = {"active", "ready", "history", "all"}
SORT_COLUMNS = {"created_at", "completed_at", "file_size", "filename"}


def ui_status_for(task) -> str:
    """Derive the presentation status (see docs/ARCHITECTURE.md §8.3)."""
    if task.status == "completed":
        if task.deleted_at:
            return "expired" if task.deleted_reason == "expired" else "deleted"
        if task.retrieved_at:
            return "retrieved"
        return "ready"
    return {
        "active": "downloading",
        "queued": "queued",
        "paused": "paused",
        "verifying": "verifying",
        "failed": "failed",
        "canceled": "canceled",
    }.get(task.status, task.status)


def task_to_out(task) -> TaskOut:
    progress = None
    eta = None
    if task.file_size and task.file_size > 0:
        progress = min(1.0, max(0.0, task.downloaded_size / task.file_size))
        if task.download_speed and task.download_speed > 0:
            remaining = max(0, task.file_size - task.downloaded_size)
            eta = int(remaining / task.download_speed)
    elif task.status in {"completed"}:
        progress = 1.0

    return TaskOut(
        id=task.id,
        url_display=task.url_display,
        filename=task.filename,
        display_name=task.display_name,
        status=task.status,
        ui_status=ui_status_for(task),
        file_size=task.file_size,
        downloaded_size=task.downloaded_size,
        progress=progress,
        download_speed=task.download_speed,
        eta_seconds=eta,
        sha256=task.sha256,
        content_type=task.content_type,
        supports_range=task.supports_range,
        error_code=task.error_code,
        error_message=task.error_message,
        attempts=task.attempts,
        max_connections=task.max_connections,
        speed_limit_bytes=task.speed_limit_bytes,
        download_bytes=task.download_bytes_counted,
        retrieved_bytes=task.upload_bytes_counted,
        transfer_count=task.transfer_count,
        is_file_available=task.status == "completed" and task.deleted_at is None,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        retrieved_at=task.retrieved_at,
        deleted_at=task.deleted_at,
        expires_at=task.expires_at,
    )


def seconds_until(value: str | None) -> int | None:
    if not value:
        return None
    remaining = int((parse_iso(value) - utc_now()).total_seconds())
    return max(0, remaining)


Scope = Literal["active", "ready", "history", "all"]
