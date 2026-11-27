"""User account (single-user mode in v1)."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.timeutil import now_iso
from app.database.base import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("length(username) BETWEEN 3 AND 32", name="username_length"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(
        nullable=False, default=False, server_default="0"
    )
    created_at: Mapped[str] = mapped_column(String(20), nullable=False, default=now_iso)
    password_changed_at: Mapped[str | None] = mapped_column(String(20))
    last_login_at: Mapped[str | None] = mapped_column(String(20))
    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    locked_until: Mapped[str | None] = mapped_column(String(20))
