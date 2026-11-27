"""Runtime settings models.

The full model doubles as the validator for stored values; ``SettingsPatch``
is what the HTTP layer accepts (partial updates only).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class RuntimeSettings(BaseModel):
    # downloads
    max_concurrent_downloads: int = Field(default=2, ge=1, le=6)
    default_connections: int = Field(default=4, ge=1, le=16)
    default_speed_limit_kib_per_s: int = Field(default=0, ge=0, le=1_048_576)
    global_speed_limit_kib_per_s: int = Field(default=0, ge=0, le=1_048_576)
    max_file_size_bytes: int = Field(default=8 * 1024**3, ge=1024**2, le=100 * 1024**3)
    max_total_storage_bytes: int = Field(default=15 * 1024**3, ge=1024**3, le=10 * 1024**4)
    min_free_disk_bytes: int = Field(default=2 * 1024**3, ge=0, le=100 * 1024**3)
    queue_max_length: int = Field(default=50, ge=1, le=1000)

    # retention / cleanup
    retention_hours: int = Field(default=24, ge=1, le=720)
    orphan_quarantine_hours: int = Field(default=24, ge=1, le=720)

    # transfer
    download_token_ttl_seconds: int = Field(default=1800, ge=60, le=3600)
    max_transfer_concurrency: int = Field(default=2, ge=1, le=4)

    # sessions / login
    session_idle_days: int = Field(default=7, ge=1, le=30)
    session_absolute_days: int = Field(default=30, ge=1, le=180)
    login_max_attempts: int = Field(default=5, ge=3, le=20)
    login_window_minutes: int = Field(default=15, ge=1, le=120)
    login_lock_minutes: int = Field(default=15, ge=1, le=1440)

    # ui
    density: Literal["comfortable", "compact"] = "comfortable"
    theme: Literal["system", "light", "dark"] = "system"
    locale: Literal["zh-CN"] = "zh-CN"


class SettingsPatch(BaseModel):
    """Partial update accepted over HTTP.

    Value bounds are enforced by :class:`RuntimeSettings` so that range errors
    surface as ``SETTINGS_INVALID`` with the offending key, as documented.
    """

    model_config = {"extra": "forbid"}

    max_concurrent_downloads: int | None = None
    default_connections: int | None = None
    default_speed_limit_kib_per_s: int | None = None
    global_speed_limit_kib_per_s: int | None = None
    max_file_size_bytes: int | None = None
    max_total_storage_bytes: int | None = None
    min_free_disk_bytes: int | None = None
    queue_max_length: int | None = None
    retention_hours: int | None = None
    orphan_quarantine_hours: int | None = None
    download_token_ttl_seconds: int | None = None
    max_transfer_concurrency: int | None = None
    session_idle_days: int | None = None
    session_absolute_days: int | None = None
    login_max_attempts: int | None = None
    login_window_minutes: int | None = None
    login_lock_minutes: int | None = None
    density: Literal["comfortable", "compact"] | None = None
    theme: Literal["system", "light", "dark"] | None = None
    locale: Literal["zh-CN"] | None = None

    def as_changes(self) -> dict[str, object]:
        return self.model_dump(exclude_none=True)


class SettingsMeta(BaseModel):
    storage_root: str
    storage_subdir: str
    tls_mode: str
    public_base_url: str
    version: str
    build: str
    read_only_keys: list[str] = []


class SettingsResponse(BaseModel):
    settings: RuntimeSettings
    meta: SettingsMeta


class SettingsUpdateResponse(BaseModel):
    settings: RuntimeSettings
    applied: list[str]
