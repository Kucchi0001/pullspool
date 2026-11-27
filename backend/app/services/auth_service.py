"""Authentication: bootstrap, password checks, sessions, lockout."""

from __future__ import annotations

import contextlib
import os
import re
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import AppConfig
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.security import (
    hash_password,
    needs_rehash,
    new_session_token,
    sha256_hex,
    validate_password,
    verify_password,
)
from app.core.timeutil import now_iso, parse_iso, to_iso, utc_now
from app.models.session import AuthSession
from app.models.user import User
from app.schemas.settings import RuntimeSettings

logger = get_logger("pullspool.auth")

_SLIDING_REFRESH_SECONDS = 60
USERNAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,31}$")


def _bootstrap_text(username: str, password: str) -> str:
    if password == "admin":
        warning = (
            "警告：当前使用默认初始密码 admin。若服务已暴露公网，"
            "任何人可能抢先登录并修改密码，请立即登录修改。\n"
        )
    else:
        warning = "初始密码由 BOOTSTRAP_ADMIN_PASSWORD 指定，请妥善保管。\n"
    return (
        "PullSpool 初始管理员账号\n"
        "========================\n\n"
        f"用户名: {username}\n"
        f"密码:   {password}\n\n"
        "首次登录后必须修改密码，修改成功后本文件会被自动删除。\n"
        f"{warning}"
        "请勿把本文件提交到版本库或分享给他人。\n"
    )


async def ensure_bootstrap_admin(session: AsyncSession, config: AppConfig) -> bool:
    """Create the single admin account on first boot. Returns True if created."""
    existing = await session.scalar(select(User.id).limit(1))
    if existing is not None:
        return False

    password = config.bootstrap_password
    user = User(
        username=config.bootstrap_username,
        password_hash=hash_password(password),
        must_change_password=True,
        created_at=now_iso(),
    )
    session.add(user)
    await session.commit()

    path: Path = config.bootstrap_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_bootstrap_text(config.bootstrap_username, password), encoding="utf-8")
    with contextlib.suppress(OSError):
        os.chmod(path, 0o600)

    if password == "admin":
        logger.warning(
            "已创建初始管理员账号 %s，使用默认密码 admin；首次登录必须修改。"
            "若服务已暴露公网，请立即登录改密（或预先设置 BOOTSTRAP_ADMIN_PASSWORD）",
            config.bootstrap_username,
        )
    else:
        logger.warning(
            "已创建初始管理员账号 %s，初始密码见 %s（首次登录必须修改）",
            config.bootstrap_username,
            path,
        )
    return True


def remove_bootstrap_file(config: AppConfig) -> None:
    try:
        config.bootstrap_file.unlink(missing_ok=True)
    except OSError:  # pragma: no cover - defensive
        logger.warning("无法删除初始密码文件，请手动删除 %s", config.bootstrap_file)


async def authenticate(
    session: AsyncSession,
    username: str,
    password: str,
    settings: RuntimeSettings,
) -> User:
    user = await session.scalar(select(User).where(User.username == username.strip().lower()))
    now = utc_now()

    if user is not None and user.locked_until:
        if parse_iso(user.locked_until) > now:
            retry_after = max(1, int((parse_iso(user.locked_until) - now).total_seconds()) + 1)
            raise AppError(
                ErrorCode.AUTH_LOCKED,
                details={"retry_after": retry_after},
                headers={"Retry-After": str(retry_after)},
            )
        user.locked_until = None

    if user is None:
        # Constant-ish time: verify against a throwaway hash to avoid revealing
        # whether the username exists.
        verify_password(
            "$argon2id$v=19$m=65536,t=3,p=4$MDEyMzQ1Njc4OWFiY2RlZg$"
            "5Yf8oY6d7RbXk1F9m2Qw3pZ0vS4uT8xJ6nL1cH5gA2w",
            password,
        )
        raise AppError(ErrorCode.AUTH_INVALID)

    if not verify_password(user.password_hash, password):
        user.failed_login_count += 1
        if user.failed_login_count >= settings.login_max_attempts:
            user.locked_until = to_iso(now + timedelta(minutes=settings.login_lock_minutes))
            user.failed_login_count = 0
            await session.commit()
            raise AppError(
                ErrorCode.AUTH_LOCKED,
                details={"retry_after": settings.login_lock_minutes * 60},
                headers={"Retry-After": str(settings.login_lock_minutes * 60)},
            )
        await session.commit()
        raise AppError(ErrorCode.AUTH_INVALID)

    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now_iso()
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    await session.commit()
    return user


async def create_session(
    session: AsyncSession,
    user: User,
    *,
    ip: str | None,
    user_agent: str | None,
    settings: RuntimeSettings,
) -> tuple[str, AuthSession]:
    token = new_session_token()
    now = utc_now()
    idle_expiry = now + timedelta(days=settings.session_idle_days)
    absolute_expiry = now + timedelta(days=settings.session_absolute_days)
    expires_at = min(idle_expiry, absolute_expiry)

    row = AuthSession(
        id=str(uuid4()),
        user_id=user.id,
        token_hash=sha256_hex(token),
        created_at=to_iso(now),
        last_seen_at=to_iso(now),
        expires_at=to_iso(expires_at),
        ip=(ip or "")[:64] or None,
        user_agent=(user_agent or "")[:255] or None,
    )
    session.add(row)
    await session.commit()
    return token, row


async def resolve_session(
    session: AsyncSession, token: str | None, settings: RuntimeSettings
) -> tuple[User, AuthSession] | None:
    if not token:
        return None
    row = await session.scalar(select(AuthSession).where(AuthSession.token_hash == sha256_hex(token)))
    if row is None or row.revoked_at is not None:
        return None

    now = utc_now()
    if parse_iso(row.expires_at) <= now:
        return None

    user = await session.get(User, row.user_id)
    if user is None:
        return None

    if (now - parse_iso(row.last_seen_at)).total_seconds() > _SLIDING_REFRESH_SECONDS:
        row.last_seen_at = to_iso(now)
        idle_expiry = now + timedelta(days=settings.session_idle_days)
        absolute_expiry = parse_iso(row.created_at) + timedelta(days=settings.session_absolute_days)
        row.expires_at = to_iso(min(idle_expiry, absolute_expiry))
        await session.commit()

    return user, row


async def revoke_session(session: AsyncSession, token: str | None) -> None:
    if not token:
        return
    row = await session.scalar(select(AuthSession).where(AuthSession.token_hash == sha256_hex(token)))
    if row is not None and row.revoked_at is None:
        row.revoked_at = now_iso()
        await session.commit()


async def revoke_other_sessions(
    session: AsyncSession, user_id: int, keep_token: str | None
) -> int:
    rows = (
        await session.scalars(
            select(AuthSession).where(
                AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None)
            )
        )
    ).all()
    keep_hash = sha256_hex(keep_token) if keep_token else ""
    revoked = 0
    for row in rows:
        if row.token_hash == keep_hash:
            continue
        row.revoked_at = now_iso()
        revoked += 1
    if revoked:
        await session.commit()
    return revoked


async def change_password(
    session: AsyncSession,
    user: User,
    *,
    current_password: str,
    new_password: str,
    config: AppConfig,
) -> None:
    if not verify_password(user.password_hash, current_password):
        raise AppError(ErrorCode.AUTH_INVALID, "当前密码不正确")
    validate_password(new_password, username=user.username)
    if verify_password(user.password_hash, new_password):
        raise AppError(ErrorCode.WEAK_PASSWORD, "新密码不能与当前密码相同")

    user.password_hash = hash_password(new_password)
    user.password_changed_at = now_iso()
    user.must_change_password = False
    user.failed_login_count = 0
    user.locked_until = None
    await session.commit()
    remove_bootstrap_file(config)
    logger.info("用户 %s 已修改密码，其他会话将被撤销", user.username)


async def change_username(
    session: AsyncSession,
    user: User,
    *,
    new_username: str,
    current_password: str,
) -> User:
    """Rename the single admin account after re-checking the password."""
    if not verify_password(user.password_hash, current_password):
        raise AppError(ErrorCode.AUTH_INVALID, "当前密码不正确")

    candidate = new_username.strip().lower()
    if not USERNAME_PATTERN.fullmatch(candidate):
        raise AppError(
            ErrorCode.USERNAME_INVALID,
            "用户名需为 3–32 位小写字母、数字、点、下划线或连字符，并以字母或数字开头",
        )
    if candidate == user.username:
        return user

    exists = await session.scalar(select(User).where(User.username == candidate))
    if exists is not None:
        raise AppError(ErrorCode.USERNAME_TAKEN, "该用户名已被占用")

    previous = user.username
    user.username = candidate
    await session.commit()
    logger.info("用户 %s 已将用户名修改为 %s", previous, candidate)
    return user
