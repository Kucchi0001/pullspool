"""aria2 JSON-RPC client behaviour against a fake RPC server."""

from __future__ import annotations

import socket
from collections.abc import AsyncIterator

import pytest
from aiohttp import web

from app.core.errors import AppError, ErrorCode
from app.services.aria2_service import (
    STATUS_MAP,
    Aria2Client,
    Aria2Status,
)

GID = "0123456789abcdef"


@pytest.fixture()
async def rpc_server() -> AsyncIterator[tuple[str, str, list[dict], dict[str, object]]]:
    calls: list[dict] = []
    routes: dict[str, object] = {"aria2.addUri": GID}

    async def handler(request: web.Request) -> web.Response:
        payload = await request.json()
        calls.append(payload)
        result = routes.get(payload["method"], {"version": "1.37.0"})
        if isinstance(result, dict) and "__error__" in result:
            return web.json_response(
                {"jsonrpc": "2.0", "id": payload["id"], "error": result["__error__"]}
            )
        return web.json_response({"jsonrpc": "2.0", "id": payload["id"], "result": result})

    async def broken(request: web.Request) -> web.Response:
        return web.Response(status=500, text="boom")

    application = web.Application()
    application.router.add_post("/jsonrpc", handler)
    application.router.add_post("/broken", broken)
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    try:
        yield (
            f"http://127.0.0.1:{port}/jsonrpc",
            f"http://127.0.0.1:{port}/broken",
            calls,
            routes,
        )
    finally:
        await runner.cleanup()


async def test_add_uri_sends_token_and_options(rpc_server) -> None:
    url, _, calls, _ = rpc_server
    client = Aria2Client(url, "s3cret", timeout_seconds=5)
    try:
        gid = await client.add_uri(
            ["https://example.com/file.bin"], {"dir": "/downloads/abc", "out": "file.bin"}
        )
    finally:
        await client.close()

    assert gid == GID
    assert calls[0]["method"] == "aria2.addUri"
    assert calls[0]["params"][0] == "token:s3cret"
    assert calls[0]["params"][1] == ["https://example.com/file.bin"]
    assert calls[0]["params"][2] == {"dir": "/downloads/abc", "out": "file.bin"}


async def test_add_uri_without_secret_omits_token(rpc_server) -> None:
    url, _, calls, _ = rpc_server
    client = Aria2Client(url, "", timeout_seconds=5)
    try:
        await client.add_uri(["https://example.com/file.bin"])
    finally:
        await client.close()

    assert calls[0]["params"][0] == ["https://example.com/file.bin"]


async def test_add_uri_rejects_invalid_gid(rpc_server) -> None:
    url, _, _, routes = rpc_server
    routes["aria2.addUri"] = "not-a-gid"
    client = Aria2Client(url, "", timeout_seconds=5)
    try:
        with pytest.raises(AppError) as excinfo:
            await client.add_uri(["https://example.com/file.bin"])
    finally:
        await client.close()
    assert excinfo.value.code is ErrorCode.ARIA2_ERROR


async def test_tell_status_parses_payload(rpc_server) -> None:
    url, _, _, routes = rpc_server
    routes["aria2.tellStatus"] = {
        "gid": GID,
        "status": "active",
        "totalLength": "1048576",
        "completedLength": "524288",
        "downloadSpeed": "131072",
        "connections": "4",
        "errorCode": "0",
        "dir": "/downloads/abc",
        "files": [
            {
                "path": "/downloads/abc/file.bin",
                "length": "1048576",
                "completedLength": "524288",
                "selected": "true",
            }
        ],
    }
    client = Aria2Client(url, "", timeout_seconds=5)
    try:
        status = await client.tell_status(GID)
    finally:
        await client.close()

    assert status.total_length == 1_048_576
    assert status.completed_length == 524_288
    assert status.download_speed == 131_072
    assert status.connections == 4
    assert status.error_code is None
    assert status.mapped_status == "active"
    assert status.files[0].path.endswith("file.bin")
    assert status.files[0].selected is True


async def test_rpc_error_maps_to_disk_full(rpc_server) -> None:
    url, _, _, routes = rpc_server
    routes["aria2.tellStatus"] = {"__error__": {"code": 9, "message": "not enough disk space"}}
    client = Aria2Client(url, "", timeout_seconds=5)
    try:
        with pytest.raises(AppError) as excinfo:
            await client.tell_status(GID)
    finally:
        await client.close()

    assert excinfo.value.code is ErrorCode.DISK_FULL
    assert excinfo.value.details["aria2_code"] == 9


async def test_rpc_error_with_unknown_code(rpc_server) -> None:
    url, _, _, routes = rpc_server
    routes["aria2.tellStatus"] = {"__error__": {"code": 999, "message": "mystery"}}
    client = Aria2Client(url, "", timeout_seconds=5)
    try:
        with pytest.raises(AppError) as excinfo:
            await client.tell_status(GID)
    finally:
        await client.close()

    assert excinfo.value.code is ErrorCode.ARIA2_ERROR
    assert excinfo.value.details["aria2_code"] == 999


async def test_http_error_reports_unavailable(rpc_server) -> None:
    _, broken_url, _, _ = rpc_server
    client = Aria2Client(broken_url, "", timeout_seconds=5)
    try:
        with pytest.raises(AppError) as excinfo:
            await client.get_version()
    finally:
        await client.close()
    assert excinfo.value.code is ErrorCode.ARIA2_UNAVAILABLE


async def test_connection_refused_reports_unavailable() -> None:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    client = Aria2Client(f"http://127.0.0.1:{port}/jsonrpc", "", timeout_seconds=2)
    try:
        with pytest.raises(AppError) as excinfo:
            await client.get_version()
    finally:
        await client.close()
    assert excinfo.value.code is ErrorCode.ARIA2_UNAVAILABLE


async def test_control_methods_use_expected_rpc_names(rpc_server) -> None:
    url, _, calls, _ = rpc_server
    client = Aria2Client(url, "s", timeout_seconds=5)
    try:
        await client.pause(GID)
        await client.pause(GID, force=True)
        await client.unpause(GID)
        await client.remove(GID)
        await client.remove(GID, force=True)
        await client.purge_result(GID)
        await client.change_global_option({"max-concurrent-downloads": "3"})
        await client.save_session()
    finally:
        await client.close()

    methods = [call["method"] for call in calls]
    assert methods == [
        "aria2.pause",
        "aria2.forcePause",
        "aria2.unpause",
        "aria2.remove",
        "aria2.forceRemove",
        "aria2.removeDownloadResult",
        "aria2.changeGlobalOption",
        "aria2.saveSession",
    ]


async def test_tell_active_and_waiting_parameter_shapes(rpc_server) -> None:
    url, _, calls, routes = rpc_server
    routes["aria2.tellActive"] = []
    routes["aria2.tellWaiting"] = []
    client = Aria2Client(url, "s", timeout_seconds=5)
    try:
        await client.tell_active()
        await client.tell_waiting(0, 25)
    finally:
        await client.close()

    active_params = calls[0]["params"]
    waiting_params = calls[1]["params"]
    assert active_params[0] == "token:s"
    assert isinstance(active_params[1], list)
    assert "gid" in active_params[1]
    assert waiting_params[1] == 0 and waiting_params[2] == 25
    assert isinstance(waiting_params[3], list)


async def test_is_alive_false_on_error(rpc_server) -> None:
    url, _, _, routes = rpc_server
    routes["aria2.getVersion"] = {"__error__": {"code": 1, "message": "nope"}}
    client = Aria2Client(url, "", timeout_seconds=5)
    try:
        assert await client.is_alive() is False
    finally:
        await client.close()


def test_status_mapping() -> None:
    assert STATUS_MAP["active"] == "active"
    assert STATUS_MAP["waiting"] == "queued"
    assert STATUS_MAP["paused"] == "paused"
    assert STATUS_MAP["error"] == "failed"
    assert STATUS_MAP["complete"] == "completed"
    assert STATUS_MAP["removed"] == "canceled"

    status = Aria2Status.from_payload({"gid": GID, "status": "complete", "totalLength": "10"})
    assert status.total_length == 10
    assert status.mapped_status == "completed"
