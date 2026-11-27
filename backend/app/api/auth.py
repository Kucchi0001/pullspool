"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import client_ip, get_config, get_current_user, get_db, get_ready_user, get_runtime_settings
from app.core.config import AppConfig
from app.core.errors import AppError
from app.core.logging import get_logger
from app.core.rate_limit import limiter
from app.core.timeutil import parse_iso, utc_now
from app.models.user import User
from app.schemas.auth import (
    ChangePasswordRequest,
    ChangeUsernameRequest,
    LoginRequest,
    LoginResponse,
    MeResponse,
    ServerOut,
    UserOut,
)
from app.schemas.settings import RuntimeSettings
from app.services import auth_service

logger = get_logger("pullspool.auth")

router = APIRouter(prefix="/auth", tags=["auth"])

LOGIN_IP_LIMIT = 20
LOGIN_IP_WINDOW_SECONDS = 15 * 60


def _cookie_secure(request: Request, config: AppConfig) -> bool:
    if config.tls_mode != "off":
        return True
    forwarded_proto = request.headers.get("x-forwarded-proto", "").lower()
    return forwarded_proto == "https" or request.url.scheme == "https"


def _set_session_cookie(
    response: Response, request: Request, config: AppConfig, token: str, settings: RuntimeSettings
) -> None:
    response.set_cookie(
        key=config.cookie_name,
        value=token,
        max_age=settings.session_absolute_days * 86400,
        httponly=True,
        secure=_cookie_secure(request, config),
        samesite="lax",
        path="/",
    )


def _clear_session_cookie(response: Response, config: AppConfig) -> None:
    response.delete_cookie(key=config.cookie_name, path="/", httponly=True, samesite="lax")


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    config: AppConfig = Depends(get_config),
    settings: RuntimeSettings = Depends(get_runtime_settings),
) -> LoginResponse:
    ip = client_ip(request, config)
    limiter.enforce(f"login:ip:{ip}", LOGIN_IP_LIMIT, LOGIN_IP_WINDOW_SECONDS)

    try:
        user = await auth_service.authenticate(db, payload.username, payload.password, settings)
    except AppError as exc:
        # Audit trail: username and source IP only, never the password.
        logger.warning(
            "登录失败 username=%s ip=%s code=%s", payload.username, ip, exc.code.value
        )
        raise
    logger.info("登录成功 username=%s ip=%s", user.username, ip)
    token, _ = await auth_service.create_session(
        db,
        user,
        ip=ip,
        user_agent=request.headers.get("user-agent"),
        settings=settings,
    )
    _set_session_cookie(response, request, config, token, settings)
    return LoginResponse(user=UserOut.model_validate(user))


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    config: AppConfig = Depends(get_config),
) -> Response:
    token = request.cookies.get(config.cookie_name)
    await auth_service.revoke_session(db, token)
    _clear_session_cookie(response, config)
    return Response(status_code=204)


@router.get("/me", response_model=MeResponse)
async def me(
    request: Request,
    user: User = Depends(get_current_user),
    config: AppConfig = Depends(get_config),
) -> MeResponse:
    started_at = request.app.state.started_at
    uptime = max(0, int((utc_now() - parse_iso(started_at)).total_seconds()))
    return MeResponse(
        user=UserOut.model_validate(user),
        server=ServerOut(
            version=config.version,
            build=request.app.state.build,
            started_at=started_at,
            uptime_seconds=uptime,
        ),
    )


@router.post("/username", response_model=UserOut)
async def change_username(
    payload: ChangeUsernameRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_ready_user),
) -> UserOut:
    updated = await auth_service.change_username(
        db,
        user,
        new_username=payload.new_username,
        current_password=payload.current_password,
    )
    return UserOut.model_validate(updated)


@router.post("/password", status_code=204)
async def change_password(
    payload: ChangePasswordRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    config: AppConfig = Depends(get_config),
    user: User = Depends(get_current_user),
) -> Response:
    await auth_service.change_password(
        db,
        user,
        current_password=payload.current_password,
        new_password=payload.new_password,
        config=config,
    )
    current_token = getattr(request.state, "session_token", None)
    await auth_service.revoke_other_sessions(db, user.id, keep_token=current_token)
    return Response(status_code=204)
