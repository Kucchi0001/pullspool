"""aria2 JSON-RPC client.

Only the backend talks to aria2 (the RPC port is never published). Every call
is authenticated with the shared secret read from ``/aria2/secret`` or the
``ARIA2_RPC_SECRET`` environment variable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

import aiohttp

from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger

logger = get_logger("pullspool.aria2")

GID_RE = re.compile(r"^[0-9a-f]{16}$")
DEFAULT_TIMEOUT_SECONDS = 10.0

# aria2 exit/error codes → API error codes. Codes not listed map to ARIA2_ERROR.
ARIA2_ERROR_CODES: dict[int, ErrorCode] = {
    2: ErrorCode.DOWNLOAD_TIMEOUT,  # timeout
    3: ErrorCode.TARGET_REJECTED,  # resource not found
    4: ErrorCode.TARGET_REJECTED,  # max "file not found" reached
    5: ErrorCode.DOWNLOAD_TIMEOUT,  # download aborted because speed too slow
    6: ErrorCode.TARGET_UNREACHABLE,  # network problem
    8: ErrorCode.ARIA2_ERROR,  # server does not support resume
    9: ErrorCode.DISK_FULL,  # not enough disk space
    13: ErrorCode.ARIA2_ERROR,  # file already exists
    16: ErrorCode.ARIA2_ERROR,  # could not create file
    17: ErrorCode.ARIA2_ERROR,  # file I/O error
    18: ErrorCode.ARIA2_ERROR,  # could not create directory
    19: ErrorCode.DNS_RESOLUTION_FAILED,  # name resolution failed
    22: ErrorCode.TARGET_REJECTED,  # bad HTTP response header
    23: ErrorCode.REDIRECT_LIMIT_EXCEEDED,  # too many redirects
    24: ErrorCode.TARGET_REJECTED,  # HTTP authorization failed
    29: ErrorCode.TARGET_REJECTED,  # server cannot handle the request
    32: ErrorCode.FILE_INTEGRITY_FAILED,  # checksum validation failed
}

ARIA2_ERROR_MESSAGES: dict[int, str] = {
    1: "下载引擎内部错误",
    2: "下载超时",
    3: "目标地址不存在（HTTP 404）",
    4: "连续多次未找到文件",
    5: "下载速度过慢，已中止",
    6: "下载时发生网络错误",
    7: "下载未完成",
    8: "目标服务器不支持断点续传",
    9: "磁盘空间不足",
    13: "文件已存在",
    16: "无法创建文件",
    17: "文件读写错误",
    18: "无法创建目录",
    19: "域名解析失败",
    22: "目标服务器返回了无效的响应头",
    23: "重定向次数过多",
    24: "目标服务器要求认证",
    29: "目标服务器无法处理该请求",
    32: "文件校验失败",
}

# aria2 status → PullSpool persistent status
STATUS_MAP: dict[str, str] = {
    "active": "active",
    "waiting": "queued",
    "paused": "paused",
    "error": "failed",
    "complete": "completed",
    "removed": "canceled",
}

STATUS_KEYS = [
    "gid",
    "status",
    "totalLength",
    "completedLength",
    "downloadSpeed",
    "uploadSpeed",
    "connections",
    "errorCode",
    "errorMessage",
    "dir",
    "files",
]


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return default


@dataclass(slots=True)
class Aria2File:
    path: str
    length: int
    completed_length: int
    selected: bool


@dataclass(slots=True)
class Aria2Status:
    gid: str
    status: str
    total_length: int = 0
    completed_length: int = 0
    download_speed: int = 0
    upload_speed: int = 0
    connections: int = 0
    error_code: str | None = None
    error_message: str | None = None
    directory: str | None = None
    files: list[Aria2File] = field(default_factory=list)

    @property
    def mapped_status(self) -> str:
        return STATUS_MAP.get(self.status, "failed")

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Aria2Status:
        files: list[Aria2File] = []
        for item in payload.get("files") or []:
            if not isinstance(item, dict):
                continue
            files.append(
                Aria2File(
                    path=str(item.get("path", "")),
                    length=_as_int(item.get("length")),
                    completed_length=_as_int(item.get("completedLength")),
                    selected=str(item.get("selected", "true")).lower() == "true",
                )
            )
        error_code = payload.get("errorCode")
        return cls(
            gid=str(payload.get("gid", "")),
            status=str(payload.get("status", "")),
            total_length=_as_int(payload.get("totalLength")),
            completed_length=_as_int(payload.get("completedLength")),
            download_speed=_as_int(payload.get("downloadSpeed")),
            upload_speed=_as_int(payload.get("uploadSpeed")),
            connections=_as_int(payload.get("connections")),
            error_code=str(error_code) if error_code and str(error_code) != "0" else None,
            error_message=(payload.get("errorMessage") or None),
            directory=payload.get("dir") or None,
            files=files,
        )


class Aria2Client:
    def __init__(
        self,
        rpc_url: str,
        secret: str = "",
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.rpc_url = rpc_url
        self.secret = secret
        self.timeout_seconds = timeout_seconds
        self._session = session
        self._owns_session = session is None

    # ------------------------------------------------------------------ #
    # transport
    # ------------------------------------------------------------------ #
    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(limit=8, force_close=False),
            )
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    async def _call(self, method: str, params: list[Any] | None = None) -> Any:
        session = await self._get_session()
        call_params: list[Any] = []
        if self.secret:
            call_params.append(f"token:{self.secret}")
        call_params.extend(params or [])
        payload = {
            "jsonrpc": "2.0",
            "id": uuid4().hex,
            "method": method,
            "params": call_params,
        }
        try:
            async with session.post(
                self.rpc_url,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),
            ) as response:
                http_status = response.status
                try:
                    body = await response.json(content_type=None)
                except ValueError:
                    body = None
                if http_status != 200 and not isinstance(body, dict):
                    raise AppError(
                        ErrorCode.ARIA2_UNAVAILABLE,
                        "下载引擎返回了异常状态",
                        details={"http_status": http_status},
                    )
        except AppError:
            raise
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            logger.warning("aria2 RPC %s failed: %s", method, exc.__class__.__name__)
            raise AppError(
                ErrorCode.ARIA2_UNAVAILABLE,
                "下载引擎不可用",
                details={"reason": exc.__class__.__name__},
            ) from exc

        if not isinstance(body, dict):
            raise AppError(ErrorCode.ARIA2_ERROR, "下载引擎返回了无法解析的响应")
        error = body.get("error")
        if error:
            self._raise_rpc_error(error)
        return body.get("result")

    @staticmethod
    def _raise_rpc_error(error: object) -> None:
        if not isinstance(error, dict):
            raise AppError(ErrorCode.ARIA2_ERROR)
        code = _as_int(error.get("code"))
        message = str(error.get("message", ""))[:200]
        raise AppError(
            ARIA2_ERROR_CODES.get(code, ErrorCode.ARIA2_ERROR),
            ARIA2_ERROR_MESSAGES.get(code, f"下载引擎错误（code={code}）"),
            details={"aria2_code": code, "aria2_message": message},
        )

    # ------------------------------------------------------------------ #
    # commands
    # ------------------------------------------------------------------ #
    async def add_uri(self, urls: list[str], options: dict[str, str] | None = None) -> str:
        if not urls:
            raise AppError(ErrorCode.VALIDATION_ERROR, "缺少下载地址")
        result = await self._call("aria2.addUri", [urls, options or {}])
        gid = str(result or "")
        if not GID_RE.match(gid):
            raise AppError(ErrorCode.ARIA2_ERROR, "下载引擎返回了非法任务标识")
        return gid

    async def tell_status(self, gid: str, keys: list[str] | None = None) -> Aria2Status:
        if not GID_RE.match(gid):
            raise AppError(ErrorCode.ARIA2_ERROR, "任务标识不合法")
        params: list[Any] = [gid]
        if keys is not None:
            params.append(keys)
        payload = await self._call("aria2.tellStatus", params)
        if not isinstance(payload, dict):
            raise AppError(ErrorCode.ARIA2_ERROR, "下载引擎返回了无效的任务状态")
        return Aria2Status.from_payload(payload)

    async def tell_active(self) -> list[Aria2Status]:
        return await self._tell_many("aria2.tellActive", [], STATUS_KEYS)

    async def tell_waiting(self, offset: int = 0, num: int = 100) -> list[Aria2Status]:
        return await self._tell_many("aria2.tellWaiting", [offset, num], STATUS_KEYS)

    async def tell_stopped(self, offset: int = 0, num: int = 100) -> list[Aria2Status]:
        return await self._tell_many("aria2.tellStopped", [offset, num], STATUS_KEYS)

    async def _tell_many(
        self, method: str, extra_params: list[Any], keys: list[str]
    ) -> list[Aria2Status]:
        params: list[Any] = [keys] if method == "aria2.tellActive" else [*extra_params, keys]
        payload = await self._call(method, params)
        if not isinstance(payload, list):
            return []
        return [Aria2Status.from_payload(item) for item in payload if isinstance(item, dict)]

    async def pause(self, gid: str, *, force: bool = False) -> None:
        await self._call("aria2.forcePause" if force else "aria2.pause", [gid])

    async def unpause(self, gid: str) -> None:
        await self._call("aria2.unpause", [gid])

    async def remove(self, gid: str, *, force: bool = False) -> None:
        await self._call("aria2.forceRemove" if force else "aria2.remove", [gid])

    async def purge_result(self, gid: str) -> None:
        await self._call("aria2.removeDownloadResult", [gid])

    async def change_global_option(self, options: dict[str, str]) -> None:
        await self._call("aria2.changeGlobalOption", [options])

    async def save_session(self) -> None:
        await self._call("aria2.saveSession")

    async def get_version(self) -> str:
        payload = await self._call("aria2.getVersion")
        if not isinstance(payload, dict):
            raise AppError(ErrorCode.ARIA2_ERROR, "下载引擎返回了无效的版本信息")
        return str(payload.get("version", "unknown"))

    async def is_alive(self) -> bool:
        try:
            await self.get_version()
        except AppError:
            return False
        return True
