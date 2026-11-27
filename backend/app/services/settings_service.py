"""Runtime settings stored in the ``settings`` table with a validation layer."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.core.timeutil import now_iso
from app.models.setting import Setting
from app.schemas.settings import RuntimeSettings, SettingsPatch


class SettingsService:
    """Loads settings once and caches them; invalidated on every write."""

    def __init__(self) -> None:
        self._cache: RuntimeSettings | None = None

    async def ensure_defaults(self, session: AsyncSession) -> None:
        rows = (await session.scalars(select(Setting))).all()
        existing = {row.key for row in rows}
        defaults = RuntimeSettings().model_dump()
        changed = False
        for key, value in defaults.items():
            if key not in existing:
                session.add(Setting(key=key, value=json.dumps(value), updated_at=now_iso()))
                changed = True
        if changed:
            await session.commit()
        self._cache = None

    async def load(self, session: AsyncSession) -> RuntimeSettings:
        if self._cache is not None:
            return self._cache

        rows = (await session.scalars(select(Setting))).all()
        data: dict[str, Any] = RuntimeSettings().model_dump()
        for row in rows:
            if row.key not in data:
                continue
            try:
                data[row.key] = json.loads(row.value)
            except json.JSONDecodeError:
                continue  # keep the default for corrupted values
        try:
            settings = RuntimeSettings(**data)
        except ValidationError as exc:  # corrupted DB: fall back to defaults
            settings = RuntimeSettings()
            raise AppError(
                ErrorCode.SETTINGS_INVALID,
                "设置数据损坏，已回退到默认值",
                details={"error": exc.errors()[0].get("msg", "invalid")},
            ) from None
        self._cache = settings
        return settings

    async def update(
        self, session: AsyncSession, patch: SettingsPatch
    ) -> tuple[RuntimeSettings, list[str]]:
        current = await self.load(session)
        changes = patch.as_changes()
        merged = current.model_dump()
        merged.update(changes)

        try:
            updated = RuntimeSettings(**merged)
        except ValidationError as exc:
            first = exc.errors()[0]
            key = str(first.get("loc", ("unknown",))[0])
            raise AppError(
                ErrorCode.SETTINGS_INVALID,
                f"设置项 {key} 不合法",
                details={"key": key, "reason": first.get("msg", "invalid")},
            ) from None

        applied = [key for key in changes if getattr(updated, key) != getattr(current, key)]
        for key in applied:
            value = json.dumps(getattr(updated, key), ensure_ascii=False)
            row = await session.get(Setting, key)
            if row is None:
                session.add(Setting(key=key, value=value, updated_at=now_iso()))
            else:
                row.value = value
                row.updated_at = now_iso()
        if applied:
            await session.commit()
        self._cache = updated
        return updated, applied

    def invalidate(self) -> None:
        self._cache = None
