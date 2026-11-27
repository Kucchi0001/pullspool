"""Preflight probe against a local HTTP server (SSRF layer L3)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest
from aiohttp import web

import app.services.preflight as preflight_module
from app.core.errors import AppError, ErrorCode
from app.services.preflight import (
    PinnedResolver,
    filename_from_disposition,
    preflight,
)

BODY = b"0123456789abcdef" * 6250  # 100_000 bytes


async def _file(request: web.Request) -> web.Response:
    return web.Response(
        body=BODY,
        headers={
            "Content-Type": "application/octet-stream",
            "Content-Disposition": 'attachment; filename="sample.bin"',
            "Accept-Ranges": "bytes",
            "ETag": '"abc123"',
            "Last-Modified": "Wed, 26 Nov 2026 10:00:00 GMT",
        },
    )


async def _utf8_file(request: web.Request) -> web.Response:
    return web.Response(
        body=b"zip",
        headers={
            "Content-Type": "application/zip",
            "Content-Disposition": "attachment; filename*=UTF-8''%E6%B5%8B%E8%AF%95.zip",
        },
    )


async def _head_rejected(request: web.Request) -> web.Response:
    if request.method == "HEAD":
        return web.Response(status=405)
    return await _file(request)


async def _partial(request: web.Request) -> web.Response:
    return web.Response(
        status=206,
        body=b"x",
        headers={
            "Content-Range": "bytes 0-0/12345",
            "Accept-Ranges": "bytes",
            "Content-Type": "application/octet-stream",
        },
    )


async def _no_length(request: web.Request) -> web.StreamResponse:
    response = web.StreamResponse(
        status=200, headers={"Content-Type": "application/octet-stream"}
    )
    await response.prepare(request)
    if request.method != "HEAD":
        await response.write(b"x" * 512)
    await response.write_eof()
    return response


async def _slow(request: web.Request) -> web.Response:
    await asyncio.sleep(1.0)
    return web.Response(body=b"late")


async def _redirect(request: web.Request) -> web.Response:
    raise web.HTTPFound("/file.bin")


async def _loop(request: web.Request) -> web.Response:
    raise web.HTTPFound("/loop")


async def _not_found(request: web.Request) -> web.Response:
    return web.Response(status=404, text="gone")


@pytest.fixture()
async def file_server() -> AsyncIterator[str]:
    application = web.Application()
    application.router.add_get("/file.bin", _file)
    application.router.add_get("/utf8.bin", _utf8_file)
    application.router.add_get("/head-405", _head_rejected)
    application.router.add_get("/partial", _partial)
    application.router.add_get("/no-length", _no_length)
    application.router.add_get("/slow", _slow)
    application.router.add_get("/redirect", _redirect)
    application.router.add_get("/loop", _loop)
    application.router.add_get("/missing", _not_found)

    runner = web.AppRunner(application)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        await runner.cleanup()


async def test_preflight_extracts_metadata(file_server: str) -> None:
    result = await preflight(f"{file_server}/file.bin", allow_private=True)

    assert result.status == 200
    assert result.filename == "sample.bin"
    assert result.content_length == len(BODY)
    assert result.supports_range is True
    assert result.etag == '"abc123"'
    assert result.last_modified == "Wed, 26 Nov 2026 10:00:00 GMT"
    assert result.content_type == "application/octet-stream"
    assert result.url == f"{file_server}/file.bin"


async def test_preflight_follows_redirect(file_server: str) -> None:
    result = await preflight(f"{file_server}/redirect", allow_private=True)
    assert result.url == f"{file_server}/file.bin"
    assert result.redirect_chain == [f"{file_server}/redirect"]
    assert result.filename == "sample.bin"


async def test_preflight_limits_redirects(file_server: str) -> None:
    with pytest.raises(AppError) as excinfo:
        await preflight(f"{file_server}/loop", allow_private=True, max_redirects=2)
    assert excinfo.value.code is ErrorCode.REDIRECT_LIMIT_EXCEEDED


async def test_preflight_revalidates_each_hop(
    file_server: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    original = preflight_module.check_target

    async def fake_check_target(url: str, *, allow_private: bool = False):
        calls.append(url)
        if len(calls) > 1:
            raise AppError(ErrorCode.SSRF_BLOCKED, details={"reason": "redirect_to_private"})
        return await original(url, allow_private=True)

    monkeypatch.setattr(preflight_module, "check_target", fake_check_target)

    with pytest.raises(AppError) as excinfo:
        await preflight(f"{file_server}/redirect", allow_private=True)

    assert excinfo.value.code is ErrorCode.SSRF_BLOCKED
    assert len(calls) == 2


async def test_preflight_decodes_utf8_filename(file_server: str) -> None:
    result = await preflight(f"{file_server}/utf8.bin", allow_private=True)
    assert result.filename == "测试.zip"


async def test_preflight_falls_back_when_head_is_rejected(file_server: str) -> None:
    result = await preflight(f"{file_server}/head-405", allow_private=True)
    assert result.status == 200
    assert result.content_length == len(BODY)


async def test_preflight_reads_total_from_content_range(file_server: str) -> None:
    result = await preflight(f"{file_server}/partial", allow_private=True)
    assert result.status == 206
    assert result.content_length == 12345
    assert result.supports_range is True


async def test_preflight_handles_missing_content_length(file_server: str) -> None:
    result = await preflight(f"{file_server}/no-length", allow_private=True)
    assert result.status == 200
    assert result.content_length in (None, 0)
    assert result.supports_range is False


async def test_preflight_reports_http_errors(file_server: str) -> None:
    with pytest.raises(AppError) as excinfo:
        await preflight(f"{file_server}/missing", allow_private=True)
    assert excinfo.value.code is ErrorCode.TARGET_REJECTED
    assert excinfo.value.details["status"] == 404


async def test_preflight_times_out(file_server: str) -> None:
    with pytest.raises(AppError) as excinfo:
        await preflight(
            f"{file_server}/slow",
            allow_private=True,
            timeout_seconds=0.3,
            connect_timeout=0.2,
        )
    assert excinfo.value.code is ErrorCode.TARGET_UNREACHABLE


async def test_preflight_blocks_private_target(file_server: str) -> None:
    with pytest.raises(AppError) as excinfo:
        await preflight(f"{file_server}/file.bin", allow_private=False)
    assert excinfo.value.code is ErrorCode.SSRF_BLOCKED


async def test_preflight_unreachable_host(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr("app.services.net_policy.resolve_host", fake_resolve)
    with pytest.raises(AppError) as excinfo:
        await preflight(
            "http://unreachable.example/file.bin", allow_private=True, connect_timeout=0.2
        )
    assert excinfo.value.code is ErrorCode.TARGET_UNREACHABLE


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ('attachment; filename="report.pdf"', "report.pdf"),
        ("attachment; filename=report.pdf", "report.pdf"),
        ("attachment; filename*=UTF-8''%E4%B8%AD%E6%96%87.zip", "中文.zip"),
        ('attachment; filename="fallback.zip"; filename*=UTF-8\'\'%E4%B8%AD%E6%96%87.zip', "中文.zip"),
        ("inline", None),
        (None, None),
    ],
)
def test_filename_from_disposition(header: str | None, expected: str | None) -> None:
    assert filename_from_disposition(header) == expected


async def test_pinned_resolver_rejects_other_hosts() -> None:
    resolver = PinnedResolver("example.com", 443, ["93.184.216.34"])
    with pytest.raises(OSError):
        await resolver.resolve("evil.example")
    records = await resolver.resolve("example.com", 443)
    assert records[0]["host"] == "93.184.216.34"
    assert records[0]["family"] == 2  # AF_INET
