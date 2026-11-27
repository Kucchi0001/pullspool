"""Unauthenticated health probe used by Docker and uptime monitors."""

from __future__ import annotations

import shutil

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_config, get_db
from app.core.config import AppConfig
from app.core.logging import get_logger

router = APIRouter(tags=["system"])
logger = get_logger("pullspool.health")

MIN_FREE_BYTES = 100 * 1024 * 1024


@router.get("/health")
async def health(
    request: Request,
    db: AsyncSession = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> dict[str, object]:
    checks: dict[str, str] = {}

    try:
        await db.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception:  # pragma: no cover - only on a broken database
        logger.exception("health: database check failed")
        checks["db"] = "error"

    try:
        usage = shutil.disk_usage(config.download_root)
        checks["disk"] = "ok" if usage.free >= MIN_FREE_BYTES else "low"
    except OSError:
        checks["disk"] = "error"

    aria2_client = getattr(request.app.state, "aria2", None)
    if aria2_client is None:
        checks["aria2"] = "not_configured"
    else:
        checks["aria2"] = "ok" if await aria2_client.is_alive() else "error"

    guard_state = "unknown"
    try:
        candidate = config.aria2_guard_status_file.read_text(encoding="utf-8").strip()
        if candidate in {"ok", "failed", "disabled"}:
            guard_state = candidate
    except OSError:
        guard_state = "not_configured" if not config.aria2_guard_status_file.exists() else "unknown"
    checks["egress_guard"] = guard_state

    healthy = (
        checks["db"] == "ok"
        and checks["disk"] in {"ok", "low"}
        and checks["aria2"] in {"ok", "not_configured"}
    )
    return {
        "status": "ok" if healthy else "degraded",
        "checks": checks,
        "version": config.version,
    }
