"""Aggregate API router."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import auth, events, files, health, system, tasks
from app.api import settings as settings_api

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(tasks.router)
api_router.include_router(files.router)
api_router.include_router(system.router)
api_router.include_router(settings_api.router)
api_router.include_router(events.router)
api_router.include_router(health.router)
