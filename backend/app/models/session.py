"""Server-side sessions; only the SHA-256 of the cookie token is stored."""

from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base


class AuthSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[str] = mapped_column(String(20), nullable=False)
    last_seen_at: Mapped[str] = mapped_column(String(20), nullable=False)
    expires_at: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    revoked_at: Mapped[str | None] = mapped_column(String(20))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))
