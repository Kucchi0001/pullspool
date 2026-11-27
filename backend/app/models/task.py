"""Download task records."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutil import now_iso
from app.database.base import Base

TASK_STATUSES = ("queued", "active", "paused", "verifying", "completed", "failed", "canceled")
DELETED_REASONS = ("user_ack", "expired", "user_cancel", "admin")


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','active','paused','verifying','completed','failed','canceled')",
            name="status_valid",
        ),
        CheckConstraint(
            "deleted_reason IS NULL OR deleted_reason IN ('user_ack','expired','user_cancel','admin')",
            name="deleted_reason_valid",
        ),
        CheckConstraint("sha256 IS NULL OR length(sha256) = 64", name="sha256_length"),
        CheckConstraint("downloaded_size >= 0", name="downloaded_size_non_negative"),
        Index("ix_tasks_user_status", "user_id", "status"),
        Index("ix_tasks_created", "created_at"),
        Index("ix_tasks_completed", "completed_at"),
        Index("ix_tasks_filename", "filename"),
        Index(
            "ix_tasks_expires_pending",
            "expires_at",
            sqlite_where=text("deleted_at IS NULL AND status = 'completed'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    url: Mapped[str] = mapped_column(Text, nullable=False)
    url_display: Mapped[str] = mapped_column(Text, nullable=False)
    final_url: Mapped[str | None] = mapped_column(Text)
    final_url_display: Mapped[str | None] = mapped_column(Text)

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    stored_relpath: Mapped[str | None] = mapped_column(String(512))

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", server_default="queued"
    )
    error_code: Mapped[str | None] = mapped_column(String(48))
    error_message: Mapped[str | None] = mapped_column(String(500))
    aria2_gid: Mapped[str | None] = mapped_column(String(64))

    file_size: Mapped[int | None] = mapped_column(Integer)
    downloaded_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    download_speed: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    sha256: Mapped[str | None] = mapped_column(String(64))
    sha256_computed_at: Mapped[str | None] = mapped_column(String(20))
    expected_sha256: Mapped[str | None] = mapped_column(String(64))
    content_type: Mapped[str | None] = mapped_column(String(255))
    supports_range: Mapped[bool | None] = mapped_column()
    etag: Mapped[str | None] = mapped_column(String(255))

    max_connections: Mapped[int] = mapped_column(Integer, nullable=False, default=4, server_default="4")
    speed_limit_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_size_bytes: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    download_bytes_counted: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    upload_bytes_counted: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    transfer_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    created_at: Mapped[str] = mapped_column(String(20), nullable=False, default=now_iso)
    started_at: Mapped[str | None] = mapped_column(String(20))
    completed_at: Mapped[str | None] = mapped_column(String(20))
    retrieved_at: Mapped[str | None] = mapped_column(String(20))
    deleted_at: Mapped[str | None] = mapped_column(String(20))
    deleted_reason: Mapped[str | None] = mapped_column(String(16))
    expires_at: Mapped[str | None] = mapped_column(String(20))
    last_synced_at: Mapped[str | None] = mapped_column(String(20))
