"""End-to-end tests against a real aria2c process.

The binary is downloaded into ``backend/.cache/aria2`` by the bootstrap script
(see README). When it is missing these tests are skipped rather than failing,
so the rest of the suite still runs on a clean checkout.

TLS note: the Windows aria2 build uses Schannel and ignores
``--ca-certificate``, so the "trusted CA" test is skipped there and runs on
Linux (including the container image in P7). The untrusted-certificate test
still proves that verification is active.
"""

from __future__ import annotations

import asyncio
import hashlib
import socket
import ssl
import sys
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from aiohttp import client_exceptions, web
from certs import make_test_certs

from app.core.errors import AppError, ErrorCode
from app.services.aria2_service import Aria2Client, Aria2Status

ARIA2_EXE = Path(__file__).resolve().parents[1] / ".cache" / "aria2" / "aria2c.exe"
requires_aria2 = pytest.mark.skipif(
    not ARIA2_EXE.exists(), reason="aria2c test binary not available in backend/.cache/aria2"
)

pytestmark = requires_aria2

PAYLOAD = bytes(range(256)) * 4096  # 1 MiB
SLOW_CHUNK = b"z" * 65536
SLOW_CHUNKS = 40  # 2.5 MiB, ~2s with the per-chunk delay
SLOW_TOTAL = len(SLOW_CHUNK) * SLOW_CHUNKS
SECRET = "test-secret"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _file(request: web.Request) -> web.Response:
    return web.Response(
        body=PAYLOAD,
        headers={
            "Content-Type": "application/octet-stream",
            "Accept-Ranges": "bytes",
            "ETag": '"payload"',
        },
    )


async def _slow(request: web.Request) -> web.StreamResponse:
    """Range-capable throttled endpoint so pause/resume mirrors a real server."""
    range_header = request.headers.get("Range", "")
    start, end, status = 0, SLOW_TOTAL - 1, 200
    if range_header.lower().startswith("bytes="):
        spec = range_header[6:].split("-", 1)
        try:
            start = int(spec[0]) if spec[0] else 0
            end = int(spec[1]) if len(spec) > 1 and spec[1] else SLOW_TOTAL - 1
        except ValueError:
            start, end = 0, SLOW_TOTAL - 1
        start = max(0, min(start, SLOW_TOTAL - 1))
        end = max(start, min(end, SLOW_TOTAL - 1))
        status = 206

    headers = {
        "Content-Type": "application/octet-stream",
        "Accept-Ranges": "bytes",
        "Content-Range": f"bytes {start}-{end}/{SLOW_TOTAL}" if status == 206 else "",
    }
    headers = {key: value for key, value in headers.items() if value}
    response = web.StreamResponse(status=status, headers=headers)
    response.content_length = end - start + 1
    await response.prepare(request)

    position = start
    try:
        while position <= end:
            chunk = SLOW_CHUNK[: min(len(SLOW_CHUNK), end - position + 1)]
            await response.write(chunk)
            position += len(chunk)
            await asyncio.sleep(0.05)
        await response.write_eof()
    except (ConnectionResetError, client_exceptions.ClientConnectionResetError):
        return response
    return response


async def _missing(request: web.Request) -> web.Response:
    return web.Response(status=404, text="not here")


@pytest.fixture()
async def http_server() -> AsyncIterator[str]:
    application = web.Application()
    application.router.add_get("/file.bin", _file)
    application.router.add_get("/slow.bin", _slow)
    application.router.add_get("/missing.bin", _missing)
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        await runner.cleanup()


@pytest.fixture(scope="session")
def tls_material(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    return make_test_certs(tmp_path_factory.mktemp("certs"))


@pytest.fixture()
async def https_server(tls_material: dict[str, Path]) -> AsyncIterator[str]:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=tls_material["cert"], keyfile=tls_material["key"])

    application = web.Application()
    application.router.add_get("/file.bin", _file)
    runner = web.AppRunner(application)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=context)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    try:
        yield f"https://127.0.0.1:{port}"
    finally:
        await runner.cleanup()


@asynccontextmanager
async def _start_aria2(
    tmp_path: Path,
    *,
    verify_certificate: bool = True,
    ca_file: Path | None = None,
) -> AsyncIterator[tuple[Aria2Client, Path, Path]]:
    port = _free_port()
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    session_file = tmp_path / "session.txt"
    log_path = tmp_path / "aria2.log"
    log_handle = log_path.open("wb")

    arguments = [
        str(ARIA2_EXE),
        "--enable-rpc=true",
        f"--rpc-listen-port={port}",
        "--rpc-listen-all=false",
        f"--rpc-secret={SECRET}",
        f"--dir={download_dir}",
        "--continue=true",
        "--file-allocation=none",
        "--auto-file-renaming=false",
        "--allow-overwrite=true",
        "--summary-interval=0",
        "--console-log-level=error",
        "--max-tries=1",
        "--retry-wait=1",
        f"--save-session={session_file}",
        "--save-session-interval=1",
        "--max-concurrent-downloads=3",
        "--split=1",
        "--max-connection-per-server=2",
    ]
    if ca_file is not None:
        arguments.append(f"--ca-certificate={ca_file}")
    if not verify_certificate:
        arguments.append("--check-certificate=false")

    process = await asyncio.create_subprocess_exec(
        *arguments, stdout=log_handle, stderr=log_handle
    )

    client = Aria2Client(f"http://127.0.0.1:{port}/jsonrpc", SECRET, timeout_seconds=5)
    alive = False
    for _ in range(100):
        if await client.is_alive():
            alive = True
            break
        await asyncio.sleep(0.1)

    if not alive:
        log_handle.close()
        process.kill()
        await process.wait()
        pytest.fail(f"aria2 did not start:\n{log_path.read_text(errors='replace')}")

    try:
        yield client, download_dir, session_file
    finally:
        await client.close()
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=10)
        except TimeoutError:
            process.kill()
            await process.wait()
        log_handle.close()


@pytest.fixture()
async def aria2(tmp_path: Path) -> AsyncIterator[tuple[Aria2Client, Path, Path]]:
    async with _start_aria2(tmp_path) as bundle:
        yield bundle


@pytest.fixture()
async def aria2_trusted(
    tmp_path: Path, tls_material: dict[str, Path]
) -> AsyncIterator[tuple[Aria2Client, Path, Path]]:
    async with _start_aria2(tmp_path, ca_file=tls_material["ca"]) as bundle:
        yield bundle


@pytest.fixture()
async def aria2_insecure(tmp_path: Path) -> AsyncIterator[tuple[Aria2Client, Path, Path]]:
    async with _start_aria2(tmp_path, verify_certificate=False) as bundle:
        yield bundle


async def _wait_for(
    client: Aria2Client,
    gid: str,
    predicate: Callable[[Aria2Status], bool],
    *,
    timeout: float = 25.0,
    description: str = "condition",
) -> Aria2Status:
    deadline = time.monotonic() + timeout
    last: Aria2Status | None = None
    while time.monotonic() < deadline:
        last = await client.tell_status(gid)
        if predicate(last):
            return last
        await asyncio.sleep(0.1)
    raise AssertionError(f"timed out waiting for {description}; last status = {last}")


async def test_download_completes_over_http(
    aria2: tuple[Aria2Client, Path, Path], http_server: str
) -> None:
    client, download_dir, _ = aria2
    gid = await client.add_uri(
        [f"{http_server}/file.bin"], {"dir": str(download_dir), "out": "payload.bin"}
    )

    status = await _wait_for(client, gid, lambda s: s.status == "complete", description="complete")
    assert status.total_length == len(PAYLOAD)
    assert status.completed_length == len(PAYLOAD)

    target = download_dir / "payload.bin"
    assert target.exists()
    data = target.read_bytes()
    assert len(data) == len(PAYLOAD)
    assert hashlib.sha256(data).digest() == hashlib.sha256(PAYLOAD).digest()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows aria2 uses Schannel and ignores --ca-certificate",
)
async def test_download_completes_over_https_with_ca(
    aria2_trusted: tuple[Aria2Client, Path, Path], https_server: str
) -> None:
    client, download_dir, _ = aria2_trusted
    gid = await client.add_uri(
        [f"{https_server}/file.bin"], {"dir": str(download_dir), "out": "secure.bin"}
    )

    status = await _wait_for(client, gid, lambda s: s.status == "complete", description="complete")
    assert status.total_length == len(PAYLOAD)
    assert (download_dir / "secure.bin").read_bytes() == PAYLOAD


async def test_https_rejects_untrusted_certificate(
    aria2: tuple[Aria2Client, Path, Path], https_server: str
) -> None:
    client, download_dir, _ = aria2
    gid = await client.add_uri(
        [f"{https_server}/file.bin"], {"dir": str(download_dir), "out": "untrusted.bin"}
    )

    status = await _wait_for(client, gid, lambda s: s.status == "error", description="tls error")
    message = (status.error_message or "") + (status.error_code or "")
    assert "SSL" in message or "TLS" in message or "certificate" in message.lower()
    assert not (download_dir / "untrusted.bin").exists()


async def test_https_transport_completes_without_verification(
    aria2_insecure: tuple[Aria2Client, Path, Path], https_server: str
) -> None:
    client, download_dir, _ = aria2_insecure
    gid = await client.add_uri(
        [f"{https_server}/file.bin"], {"dir": str(download_dir), "out": "insecure.bin"}
    )

    await _wait_for(client, gid, lambda s: s.status == "complete", description="complete")
    assert (download_dir / "insecure.bin").read_bytes() == PAYLOAD


async def test_pause_and_resume(
    aria2: tuple[Aria2Client, Path, Path], http_server: str
) -> None:
    client, download_dir, _ = aria2
    gid = await client.add_uri(
        [f"{http_server}/slow.bin"], {"dir": str(download_dir), "out": "slow.bin"}
    )

    await _wait_for(client, gid, lambda s: s.completed_length > 0, description="first bytes")
    await client.pause(gid)
    paused = await _wait_for(client, gid, lambda s: s.status == "paused", description="paused")
    assert paused.completed_length > 0

    await client.unpause(gid)
    completed = await _wait_for(
        client, gid, lambda s: s.status == "complete", timeout=40, description="resumed"
    )
    assert completed.completed_length == SLOW_TOTAL
    assert (download_dir / "slow.bin").stat().st_size == SLOW_TOTAL


async def test_force_remove_then_purge(
    aria2: tuple[Aria2Client, Path, Path], http_server: str
) -> None:
    client, download_dir, _ = aria2
    gid = await client.add_uri(
        [f"{http_server}/slow.bin"], {"dir": str(download_dir), "out": "cancel.bin"}
    )
    await _wait_for(client, gid, lambda s: s.completed_length > 0, description="first bytes")

    await client.remove(gid, force=True)
    removed = await _wait_for(client, gid, lambda s: s.status == "removed", description="removed")
    assert removed.mapped_status == "canceled"

    await client.purge_result(gid)
    await asyncio.sleep(0.2)
    with pytest.raises(AppError) as excinfo:
        await client.tell_status(gid)
    assert excinfo.value.code is ErrorCode.ARIA2_ERROR


async def test_missing_file_reports_aria2_error_3(
    aria2: tuple[Aria2Client, Path, Path], http_server: str
) -> None:
    client, download_dir, _ = aria2
    gid = await client.add_uri(
        [f"{http_server}/missing.bin"], {"dir": str(download_dir), "out": "missing.bin"}
    )

    status = await _wait_for(client, gid, lambda s: s.status == "error", description="error")
    assert status.error_code == "3"
    assert status.mapped_status == "failed"


async def test_save_session_records_paused_task(
    aria2: tuple[Aria2Client, Path, Path], http_server: str
) -> None:
    client, download_dir, session_file = aria2
    gid = await client.add_uri(
        [f"{http_server}/slow.bin"], {"dir": str(download_dir), "out": "session.bin"}
    )
    await _wait_for(client, gid, lambda s: s.completed_length > 0, description="first bytes")
    await client.pause(gid)
    await _wait_for(client, gid, lambda s: s.status == "paused", description="paused")

    await client.save_session()
    for _ in range(50):
        if session_file.exists() and session_file.stat().st_size > 0:
            break
        await asyncio.sleep(0.1)

    text = session_file.read_text(encoding="utf-8", errors="replace")
    assert f"{http_server}/slow.bin" in text
    assert gid in text
    # A paused in-flight download keeps its control file for resumption.
    assert list(download_dir.glob("*.aria2"))
