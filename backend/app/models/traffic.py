"""Daily application-level traffic counters."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class TrafficDaily(Base):
    __tablename__ = "traffic_daily"
    __table_args__ = (
        CheckConstraint("direction IN ('down','up')", name="direction_valid"),
        CheckConstraint("bytes >= 0", name="bytes_non_negative"),
    )

    day: Mapped[str] = mapped_column(String(10), primary_key=True)
    direction: Mapped[str] = mapped_column(String(4), primary_key=True)
    bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
