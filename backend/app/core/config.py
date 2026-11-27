"""Application configuration.

All values come from environment variables (or a local ``.env`` for development).
The container entrypoint passes the ``.env`` values through ``docker-compose.yml``.
"""

from __future__ import annotations

import contextlib
import os
import secrets
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LOG_LEVELS = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}

SQLITE_PREFIXES = ("sqlite+aiosqlite:///", "sqlite:///")


def _chmod_600(path: Path) -> None:
    """Best-effort 0600 on POSIX; Windows only supports read-only toggling."""
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)


class AppConfig(BaseSettings):
    """Runtime configuration. Field names map to upper-case env variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        populate_by_name=True,
    )

    # --- runtime -----------------------------------------------------------
    app_env: Literal["development", "test", "production"] = "development"
    version: str = "1.0.0"

    # --- paths -------------------------------------------------------------
    data_dir: Path = Path("/data")
    download_root: Path | None = None
    database_url: str | None = None

    # --- logging -----------------------------------------------------------
    log_level: str = "INFO"
    log_format: Literal["text", "json"] = "text"

    # --- public addressing -------------------------------------------------
    public_base_url: str = ""
    public_ip: str = ""
    domain: str = ""
    tls_mode: Literal["off", "internal", "acme"] = "internal"

    # --- secrets -----------------------------------------------------------
    download_token_secret: str = ""

    # --- aria2 (used from P3 onwards) --------------------------------------
    aria2_rpc_url: str = "http://aria2:6800/jsonrpc"
    aria2_rpc_secret: str = ""
    aria2_timeout_seconds: float = 5.0

    # --- outbound policy / preflight ---------------------------------------
    # Test-only escape hatch: allows loopback/private targets. Refused in production.
    allow_private_hosts: bool = False
    preflight_verify_tls: bool = True
    preflight_timeout_seconds: float = 12.0
    preflight_connect_timeout: float = 5.0
    preflight_max_redirects: int = 5

    # --- auth / bootstrap --------------------------------------------------
    bootstrap_username: str = Field(
        default="admin",
        validation_alias=AliasChoices("BOOTSTRAP_ADMIN_USERNAME", "BOOTSTRAP_USERNAME"),
    )
    bootstrap_password: str = Field(
        default="admin",
        validation_alias=AliasChoices("BOOTSTRAP_ADMIN_PASSWORD", "BOOTSTRAP_PASSWORD"),
    )
    cookie_name: str = "ps_session"

    # --- http --------------------------------------------------------------
    trust_proxy_headers: bool = True
    max_json_body_bytes: int = 1_048_576
    api_rate_limit_per_minute: int = 300
    run_migrations_on_startup: bool = True

    # --- scheduler / polling ----------------------------------------------
    timezone: str = "Asia/Shanghai"
    task_poll_interval_seconds: float = 1.0
    scheduler_interval_seconds: float = 1.0
    max_task_attempts: int = 3

    # --- transfer / cleanup -------------------------------------------------
    transfer_chunk_size: int = 262_144
    traffic_flush_bytes: int = 1_048_576
    cleanup_interval_seconds: float = 600.0
    session_retention_days: int = 7

    # ------------------------------------------------------------------ #
    # validation
    # ------------------------------------------------------------------ #
    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        level = value.strip().upper()
        if level not in LOG_LEVELS:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(LOG_LEVELS)}")
        return level

    @field_validator("bootstrap_username")
    @classmethod
    def _validate_username(cls, value: str) -> str:
        username = value.strip().lower()
        if not 3 <= len(username) <= 32:
            raise ValueError("BOOTSTRAP_ADMIN_USERNAME must be 3-32 characters")
        if not username.replace("-", "").replace("_", "").isalnum():
            raise ValueError("BOOTSTRAP_ADMIN_USERNAME may only contain letters, digits, '-' and '_'")
        return username

    @field_validator("bootstrap_password")
    @classmethod
    def _validate_bootstrap_password(cls, value: str) -> str:
        if not value:
            raise ValueError("BOOTSTRAP_ADMIN_PASSWORD must not be empty")
        if len(value) > 256:
            raise ValueError("BOOTSTRAP_ADMIN_PASSWORD must be at most 256 characters")
        return value

    @field_validator("public_base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            return ""
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("PUBLIC_BASE_URL must be an absolute http(s) URL")
        return value

    @model_validator(mode="after")
    def _finalize(self) -> AppConfig:
        data_dir = self.data_dir.expanduser()
        if not data_dir.is_absolute():
            raise ValueError("DATA_DIR must be an absolute path")
        self.data_dir = data_dir

        download_root = (self.download_root or data_dir / "downloads").expanduser()
        if not download_root.is_absolute():
            raise ValueError("DOWNLOAD_ROOT must be an absolute path")
        self.download_root = download_root

        if not self.database_url:
            self.database_url = f"sqlite+aiosqlite:///{(data_dir / 'db' / 'pullspool.db').as_posix()}"
        if not self.database_url.startswith(SQLITE_PREFIXES):
            raise ValueError("only SQLite databases are supported")

        if self.tls_mode == "acme" and not self.domain:
            raise ValueError("TLS_MODE=acme requires DOMAIN to be set")

        if self.is_production and self.allow_private_hosts:
            raise ValueError("ALLOW_PRIVATE_HOSTS must never be enabled in production")
        if self.is_production and not self.preflight_verify_tls:
            raise ValueError("PREFLIGHT_VERIFY_TLS must never be disabled in production")
        if self.preflight_timeout_seconds <= 0 or self.preflight_connect_timeout <= 0:
            raise ValueError("preflight timeouts must be positive")
        if not 0 <= self.preflight_max_redirects <= 10:
            raise ValueError("PREFLIGHT_MAX_REDIRECTS must be between 0 and 10")
        if self.task_poll_interval_seconds <= 0 or self.scheduler_interval_seconds <= 0:
            raise ValueError("scheduler and poll intervals must be positive")
        if not 1 <= self.max_task_attempts <= 10:
            raise ValueError("MAX_TASK_ATTEMPTS must be between 1 and 10")
        if self.transfer_chunk_size < 16_384 or self.transfer_chunk_size > 8 * 1024 * 1024:
            raise ValueError("TRANSFER_CHUNK_SIZE must be between 16 KiB and 8 MiB")
        if self.traffic_flush_bytes < 16_384:
            raise ValueError("TRAFFIC_FLUSH_BYTES must be at least 16 KiB")
        if self.cleanup_interval_seconds <= 0:
            raise ValueError("CLEANUP_INTERVAL_SECONDS must be positive")
        if not 1 <= self.session_retention_days <= 365:
            raise ValueError("SESSION_RETENTION_DAYS must be between 1 and 365")
        if not 10 <= self.api_rate_limit_per_minute <= 10_000:
            raise ValueError("API_RATE_LIMIT_PER_MINUTE must be between 10 and 10000")
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"TIMEZONE is not a valid IANA zone: {self.timezone}") from exc

        if not self.download_token_secret:
            self.download_token_secret = self._load_or_create_secret()
        return self

    # ------------------------------------------------------------------ #
    # helpers
    # ------------------------------------------------------------------ #
    def _load_or_create_secret(self) -> str:
        path = self.data_dir / ".token_secret"
        if path.exists():
            value = path.read_text(encoding="utf-8").strip()
            if len(value) >= 32:
                return value
        path.parent.mkdir(parents=True, exist_ok=True)
        value = secrets.token_urlsafe(48)
        path.write_text(value + "\n", encoding="utf-8")
        _chmod_600(path)
        return value

    @property
    def db_path(self) -> Path:
        for prefix in SQLITE_PREFIXES:
            if self.database_url and self.database_url.startswith(prefix):
                return Path(self.database_url[len(prefix) :])
        raise ValueError("cannot derive database path")  # pragma: no cover

    @property
    def sync_database_url(self) -> str:
        """Synchronous URL used by Alembic."""
        return f"sqlite:///{self.db_path.as_posix()}"

    @property
    def bootstrap_file(self) -> Path:
        return self.data_dir / "bootstrap-admin.txt"

    @property
    def aria2_secret_file(self) -> Path:
        return self.data_dir / "aria2" / "secret"

    @property
    def aria2_guard_status_file(self) -> Path:
        return self.data_dir / "aria2" / "egress-guard.status"

    @property
    def aria2_secret_value(self) -> str:
        """Env override first, then the file shared with the aria2 container."""
        if self.aria2_rpc_secret.strip():
            return self.aria2_rpc_secret.strip()
        try:
            return self.aria2_secret_file.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def cookie_secure_default(self) -> bool:
        return self.tls_mode != "off"

    def ensure_directories(self) -> None:
        for path in (self.data_dir, self.data_dir / "db", self.download_root, self.db_path.parent):
            path.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(self.data_dir / "db", 0o750)
