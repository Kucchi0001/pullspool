"""Per-task audit trail (also used for the "view error" panel)."""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutil import now_iso
from app.database.base import Base


class TaskEvent(Base):
    __tablename__ = "task_events"
    __table_args__ = (
        Index("ix_events_task", "task_id", "created_at"),
        Index("ix_events_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(20), nullable=False, default=now_iso)
