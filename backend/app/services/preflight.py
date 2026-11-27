"""Preflight probe (SSRF layer L3).

Connects to the *validated* IP (pinned resolver) while keeping the original
hostname for the ``Host`` header and TLS SNI, disables automatic redirects and
re-validates every hop. Returns the metadata the download pipeline needs.
"""

from __future__ import annotations

import base64
import binascii
import re
import socket
from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import unquote, urljoin

import aiohttp
from aiohttp.abc import AbstractResolver

from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger, redact_url
from app.services.net_policy import check_target, validate_url
from app.services.storage_service import filename_from_url

logger = get_logger("pullspool.preflight")

USER_AGENT = "PullSpool/1.0"
DEFAULT_TIMEOUT_SECONDS = 12.0
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_MAX_REDIRECTS = 5
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
HEAD_FALLBACK_STATUSES = {400, 403, 405, 501}
MAX_FILENAME_LENGTH = 180

_FILENAME_STAR_RE = re.compile(r"filename\*\s*=\s*([^;]+)", re.IGNORECASE)
_FILENAME_RE = re.compile(r'filename\s*=\s*(?:"([^"]*)"|([^;]+))', re.IGNORECASE)
_CONTENT_RANGE_RE = re.compile(r"bytes\s+\d+-\d+/(\d+|\*)", re.IGNORECASE)


@dataclass(slots=True)
class PreflightResult:
    url: str
    url_display: str
    host: str
    status: int
    filename: str | None = None
    content_type: str | None = None
    content_length: int | None = None
    supports_range: bool = False
    etag: str | None = None
    last_modified: str | None = None
    expected_sha256: str | None = None
    redirect_chain: list[str] = field(default_factory=list)


@dataclass(slots=True)
class _HopResponse:
    status: int
    headers: Mapping[str, str]
    location: str | None = None


class PinnedResolver(AbstractResolver):
    """Resolves exactly one hostname to pre-validated addresses."""

    def __init__(self, host: str, port: int, addresses: list[str]) -> None:
        self._host = host.lower()
        self._port = port
        self._addresses = addresses

    async def resolve(
        self, host: str, port: int = 0, family: int = socket.AF_UNSPEC
    ) -> list[dict]:
        if host.lower() not in {self._host, self._host.rstrip(".")}:
            raise OSError(f"resolver pinned to {self._host!r}, refusing {host!r}")

        results: list[dict] = []
        for address in self._addresses:
            try:
                socket.inet_pton(socket.AF_INET, address)
                version = 4
            except OSError:
                try:
                    socket.inet_pton(socket.AF_INET6, address)
                    version = 6
                except OSError:
                    continue
            if family == socket.AF_INET and version != 4:
                continue
            if family == socket.AF_INET6 and version != 6:
                continue
            results.append(
                {
                    "hostname": host,
                    "host": address,
                    "port": port or self._port,
                    "family": socket.AF_INET if version == 4 else socket.AF_INET6,
                    "proto": 0,
                    "flags": 0,
                }
            )
        if not results:
            raise OSError(f"no matching address family for {host!r}")
        return results

    async def close(self) -> None:  # pragma: no cover - nothing to release
        return None


def filename_from_disposition(value: str | None) -> str | None:
    if not value:
        return None
    match = _FILENAME_STAR_RE.search(value)
    if match:
        raw = match.group(1).strip().strip('"')
        if "''" in raw:
            _, _, encoded = raw.partition("''")
        else:
            encoded = raw.split("'", 2)[-1]
        decoded = unquote(encoded, encoding="utf-8", errors="replace")
        if decoded.strip():
            return decoded.strip()

    match = _FILENAME_RE.search(value)
    if match:
        candidate = (match.group(1) or match.group(2) or "").strip()
        if candidate:
            return candidate
    return None


def _parse_content_range_total(value: str | None) -> int | None:
    if not value:
        return None
    match = _CONTENT_RANGE_RE.search(value)
    if not match or match.group(1) == "*":
        return None
    try:
        return int(match.group(1))
    except ValueError:  # pragma: no cover - defensive
        return None


def _parse_expected_sha256(headers: object) -> str | None:
    digest = None
    checksum = None
    try:
        digest = headers.get("Digest")  # type: ignore[attr-defined]
        checksum = headers.get("X-Checksum-Sha256")  # type: ignore[attr-defined]
    except AttributeError:  # pragma: no cover - plain dict fallback
        mapping = dict(headers)  # type: ignore[arg-type]
        digest = mapping.get("Digest")
        checksum = mapping.get("X-Checksum-Sha256")

    if checksum:
        candidate = checksum.strip().lower()
        if re.fullmatch(r"[0-9a-f]{64}", candidate):
            return candidate
    if digest:
        for part in digest.split(","):
            algorithm, _, encoded = part.partition("=")
            if algorithm.strip().lower() != "sha-256":
                continue
            try:
                raw = base64.b64decode(encoded.strip(), validate=True)
            except (binascii.Error, ValueError):
                continue
            if len(raw) == 32:
                return raw.hex()
    return None


async def _request_hop(
    url: str,
    addresses: list[str],
    host: str,
    port: int,
    *,
    verify_tls: bool,
    timeout_seconds: float,
    connect_timeout: float,
) -> _HopResponse:
    resolver = PinnedResolver(host, port, addresses)
    connector = aiohttp.TCPConnector(
        resolver=resolver,
        ssl=verify_tls,
        force_close=True,
        enable_cleanup_closed=True,
    )
    timeout = aiohttp.ClientTimeout(
        total=timeout_seconds, connect=connect_timeout, sock_read=connect_timeout
    )
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
    }

    last_error: Exception | None = None
    async with aiohttp.ClientSession(
        connector=connector, timeout=timeout, headers=headers, auto_decompress=False
    ) as session:
        for method in ("HEAD", "GET"):
            request_headers = {"Range": "bytes=0-0"} if method == "GET" else None
            try:
                async with session.request(
                    method, url, allow_redirects=False, headers=request_headers
                ) as response:
                    status = response.status
                    if method == "HEAD" and status in HEAD_FALLBACK_STATUSES:
                        continue
                    location = response.headers.get("Location")
                    if status in REDIRECT_STATUSES:
                        if not location:
                            raise AppError(
                                ErrorCode.TARGET_REJECTED,
                                "目标站点返回了没有地址的重定向",
                                details={"status": status},
                            )
                        return _HopResponse(status=status, headers=response.headers, location=location)
                    if status >= 400:
                        raise AppError(
                            ErrorCode.TARGET_REJECTED,
                            f"目标地址返回 HTTP {status}",
                            details={"status": status},
                        )
                    return _HopResponse(status=status, headers=response.headers)
            except AppError:
                raise
            except (aiohttp.ClientError, TimeoutError, OSError, ValueError) as exc:
                last_error = exc
                logger.info("preflight %s %s failed: %s", method, redact_url(url), exc.__class__.__name__)
                continue

    if isinstance(last_error, TimeoutError):
        raise AppError(
            ErrorCode.TARGET_UNREACHABLE,
            "访问目标地址超时",
            details={"reason": "timeout"},
        )
    raise AppError(
        ErrorCode.TARGET_UNREACHABLE,
        "无法连接目标地址",
        details={"reason": type(last_error).__name__ if last_error else "unknown"},
    )


async def preflight(
    url: str,
    *,
    allow_private: bool = False,
    verify_tls: bool = True,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
    max_redirects: int = DEFAULT_MAX_REDIRECTS,
) -> PreflightResult:
    """Probe ``url`` through validated IPs and manual redirect handling."""
    current = url
    chain: list[str] = []

    for hop in range(max_redirects + 1):
        target = await check_target(current, allow_private=allow_private)
        response = await _request_hop(
            target.url,
            target.ips,
            target.host,
            target.port,
            verify_tls=verify_tls,
            timeout_seconds=timeout_seconds,
            connect_timeout=connect_timeout,
        )

        if response.location is not None:
            if hop >= max_redirects:
                raise AppError(
                    ErrorCode.REDIRECT_LIMIT_EXCEEDED,
                    f"重定向次数超过 {max_redirects} 次",
                    details={"max_redirects": max_redirects},
                )
            chain.append(target.display)
            next_url = urljoin(target.url, response.location)
            # Re-validate the redirect target in the next loop iteration.
            validate_url(next_url, allow_private=allow_private)
            current = next_url
            continue

        headers = response.headers
        filename = filename_from_disposition(headers.get("Content-Disposition"))
        if filename is None:
            filename = filename_from_url(target.url)

        total = _parse_content_range_total(headers.get("Content-Range"))
        if total is None and response.status == 200:
            length_header = headers.get("Content-Length")
            if length_header and length_header.isdigit():
                total = int(length_header)

        content_type = headers.get("Content-Type")
        if content_type:
            content_type = content_type.split(";", 1)[0].strip()[:255]

        accept_ranges = (headers.get("Accept-Ranges") or "").lower()
        supports_range = "bytes" in accept_ranges or response.status == 206

        return PreflightResult(
            url=target.url,
            url_display=target.display,
            host=target.host,
            status=response.status,
            filename=filename[:MAX_FILENAME_LENGTH] if filename else None,
            content_type=content_type,
            content_length=total,
            supports_range=supports_range,
            etag=(headers.get("ETag") or None),
            last_modified=(headers.get("Last-Modified") or None),
            expected_sha256=_parse_expected_sha256(headers),
            redirect_chain=chain,
        )

    raise AppError(ErrorCode.REDIRECT_LIMIT_EXCEEDED)  # pragma: no cover - loop always returns
