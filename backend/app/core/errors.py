"""Error codes, the exception type used across the app, and HTTP handlers.

Every error response uses the envelope described in ``docs/API.md``:

    {"error": {"code": "...", "message": "...", "details": {...}, "request_id": "..."}}
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import get_logger, request_id_var


class ErrorCode(StrEnum):
    # request / validation
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    INTERNAL_ERROR = "INTERNAL_ERROR"

    # url / target
    URL_INVALID = "URL_INVALID"
    URL_SCHEME_NOT_ALLOWED = "URL_SCHEME_NOT_ALLOWED"
    SSRF_BLOCKED = "SSRF_BLOCKED"
    DNS_RESOLUTION_FAILED = "DNS_RESOLUTION_FAILED"
    REDIRECT_LIMIT_EXCEEDED = "REDIRECT_LIMIT_EXCEEDED"
    TARGET_UNREACHABLE = "TARGET_UNREACHABLE"
    TARGET_REJECTED = "TARGET_REJECTED"

    # auth
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_INVALID = "AUTH_INVALID"
    AUTH_LOCKED = "AUTH_LOCKED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    PASSWORD_CHANGE_REQUIRED = "PASSWORD_CHANGE_REQUIRED"
    WEAK_PASSWORD = "WEAK_PASSWORD"
    USERNAME_INVALID = "USERNAME_INVALID"
    USERNAME_TAKEN = "USERNAME_TAKEN"
    ORIGIN_MISMATCH = "ORIGIN_MISMATCH"
    FORBIDDEN = "FORBIDDEN"

    # tasks
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    TASK_STATE_CONFLICT = "TASK_STATE_CONFLICT"
    TASK_DUPLICATE = "TASK_DUPLICATE"
    TRANSFER_IN_PROGRESS = "TRANSFER_IN_PROGRESS"
    QUEUE_FULL = "QUEUE_FULL"

    # files
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_INTEGRITY_FAILED = "FILE_INTEGRITY_FAILED"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    RANGE_NOT_SATISFIABLE = "RANGE_NOT_SATISFIABLE"

    # quota / engine
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"
    DISK_FULL = "DISK_FULL"
    ARIA2_UNAVAILABLE = "ARIA2_UNAVAILABLE"
    ARIA2_ERROR = "ARIA2_ERROR"
    DOWNLOAD_TIMEOUT = "DOWNLOAD_TIMEOUT"

    # tokens / limits
    TOKEN_INVALID = "TOKEN_INVALID"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    RATE_LIMITED = "RATE_LIMITED"
    SETTINGS_INVALID = "SETTINGS_INVALID"


STATUS_BY_CODE: dict[ErrorCode, int] = {
    ErrorCode.VALIDATION_ERROR: 400,
    ErrorCode.NOT_FOUND: 404,
    ErrorCode.METHOD_NOT_ALLOWED: 405,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.URL_INVALID: 400,
    ErrorCode.URL_SCHEME_NOT_ALLOWED: 400,
    ErrorCode.SSRF_BLOCKED: 403,
    ErrorCode.DNS_RESOLUTION_FAILED: 502,
    ErrorCode.REDIRECT_LIMIT_EXCEEDED: 502,
    ErrorCode.TARGET_UNREACHABLE: 502,
    ErrorCode.TARGET_REJECTED: 502,
    ErrorCode.AUTH_REQUIRED: 401,
    ErrorCode.AUTH_INVALID: 401,
    ErrorCode.AUTH_LOCKED: 429,
    ErrorCode.SESSION_EXPIRED: 401,
    ErrorCode.PASSWORD_CHANGE_REQUIRED: 403,
    ErrorCode.WEAK_PASSWORD: 400,
    ErrorCode.USERNAME_INVALID: 400,
    ErrorCode.USERNAME_TAKEN: 409,
    ErrorCode.ORIGIN_MISMATCH: 403,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.TASK_NOT_FOUND: 404,
    ErrorCode.TASK_STATE_CONFLICT: 409,
    ErrorCode.TASK_DUPLICATE: 200,
    ErrorCode.TRANSFER_IN_PROGRESS: 409,
    ErrorCode.QUEUE_FULL: 409,
    ErrorCode.FILE_NOT_FOUND: 404,
    ErrorCode.FILE_INTEGRITY_FAILED: 409,
    ErrorCode.FILE_TOO_LARGE: 413,
    ErrorCode.RANGE_NOT_SATISFIABLE: 416,
    ErrorCode.QUOTA_EXCEEDED: 409,
    ErrorCode.DISK_FULL: 507,
    ErrorCode.ARIA2_UNAVAILABLE: 503,
    ErrorCode.ARIA2_ERROR: 502,
    ErrorCode.DOWNLOAD_TIMEOUT: 504,
    ErrorCode.TOKEN_INVALID: 401,
    ErrorCode.TOKEN_EXPIRED: 401,
    ErrorCode.RATE_LIMITED: 429,
    ErrorCode.SETTINGS_INVALID: 400,
}

# Friendly Chinese messages used when a caller does not supply one.
DEFAULT_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.VALIDATION_ERROR: "请求参数不合法",
    ErrorCode.NOT_FOUND: "请求的资源不存在",
    ErrorCode.METHOD_NOT_ALLOWED: "请求方法不被允许",
    ErrorCode.INTERNAL_ERROR: "服务器内部错误，请稍后重试",
    ErrorCode.AUTH_REQUIRED: "请先登录",
    ErrorCode.AUTH_INVALID: "用户名或密码错误",
    ErrorCode.AUTH_LOCKED: "登录尝试过于频繁，请稍后再试",
    ErrorCode.SESSION_EXPIRED: "登录已过期，请重新登录",
    ErrorCode.PASSWORD_CHANGE_REQUIRED: "首次登录需要先修改密码",
    ErrorCode.WEAK_PASSWORD: "密码强度不足",
    ErrorCode.ORIGIN_MISMATCH: "请求来源校验失败，请刷新页面后重试",
    ErrorCode.FORBIDDEN: "没有权限执行该操作",
    ErrorCode.RATE_LIMITED: "操作过于频繁，请稍后再试",
    ErrorCode.SSRF_BLOCKED: "该地址不允许访问",
    ErrorCode.URL_INVALID: "下载链接格式不正确",
    ErrorCode.TASK_STATE_CONFLICT: "任务当前状态不允许该操作",
    ErrorCode.TRANSFER_IN_PROGRESS: "文件正在回传，请等待传输结束后再删除",
    ErrorCode.SETTINGS_INVALID: "设置项不合法",
}

logger = get_logger("pullspool")


class AppError(Exception):
    """A handled, user-facing error."""

    def __init__(
        self,
        code: ErrorCode,
        message: str | None = None,
        *,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.code = code
        self.message = message or DEFAULT_MESSAGES.get(code, code.value)
        self.status_code = status_code or STATUS_BY_CODE.get(code, 400)
        self.details = details or {}
        self.headers = headers or {}
        super().__init__(self.message)


def error_body(
    code: ErrorCode,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "error": {
            "code": code.value,
            "message": message or DEFAULT_MESSAGES.get(code, code.value),
            "details": details or {},
            "request_id": request_id_var.get(),
        }
    }


def error_response(
    code: ErrorCode,
    message: str | None = None,
    *,
    status_code: int | None = None,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code or STATUS_BY_CODE.get(code, 400),
        content=error_body(code, message, details),
        headers=headers,
    )


def _validation_details(exc: RequestValidationError) -> dict[str, Any]:
    fields = []
    for item in exc.errors():
        loc = [str(part) for part in item.get("loc", ()) if part not in ("body", "query", "path")]
        fields.append({"field": ".".join(loc), "message": item.get("msg", "invalid")})
    return {"fields": fields}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.details),
            headers=exc.headers or None,
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(ErrorCode.VALIDATION_ERROR, details=_validation_details(exc))

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        mapping = {
            401: ErrorCode.AUTH_REQUIRED,
            403: ErrorCode.FORBIDDEN,
            404: ErrorCode.NOT_FOUND,
            405: ErrorCode.METHOD_NOT_ALLOWED,
            429: ErrorCode.RATE_LIMITED,
        }
        code = mapping.get(exc.status_code)
        if code is None:
            return error_response(
                ErrorCode.INTERNAL_ERROR if exc.status_code >= 500 else ErrorCode.VALIDATION_ERROR,
                status_code=exc.status_code,
            )
        return error_response(code, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error: %s", exc.__class__.__name__)
        return error_response(ErrorCode.INTERNAL_ERROR)
