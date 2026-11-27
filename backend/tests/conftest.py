"""Shared test fixtures.

Two families:
* generic app fixtures (`config`, `app`, `client`, `ready_client`) for HTTP /
  auth / settings tests that do not need aria2;
* task fixtures (`file_server`, `aria2_endpoint`, `api`) that start a real
  aria2c process plus a local file server for end-to-end download tests.
"""

from __future__ import annotations

import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from fake_server import ServerThread
from fastapi.testclient import TestClient
from helpers import NEW_PASSWORD, login, read_bootstrap_password

from app.core.config import AppConfig
from app.core.rate_limit import limiter
from app.main import create_app

ARIA2_EXE = Path(__file__).resolve().parents[1] / ".cache" / "aria2" / "aria2c.exe"
ARIA2_SECRET = "task-test-secret"


# --------------------------------------------------------------------------- #
# generic app
# --------------------------------------------------------------------------- #
@pytest.fixture()
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppConfig:
    data_dir = tmp_path / "data"
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATA_DIR", str(data_dir))
    monkeypatch.setenv("DOWNLOAD_ROOT", str(data_dir / "downloads"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("TLS_MODE", "off")
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://testserver")
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    monkeypatch.setenv("RUN_MIGRATIONS_ON_STARTUP", "false")
    return AppConfig()


@pytest.fixture()
def app(config: AppConfig):
    limiter.reset()
    return create_app(config)


@pytest.fixture()
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def ready_client(client: TestClient, config: AppConfig) -> TestClient:
    """A logged-in client whose admin password has already been changed."""
    initial_password = read_bootstrap_password(config.bootstrap_file)
    response = login(client, initial_password)
    assert response.status_code == 200, response.text

    response = client.post(
        "/api/auth/password",
        json={"current_password": initial_password, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 204, response.text
    return client


# --------------------------------------------------------------------------- #
# task fixtures (real aria2 + local files)
# --------------------------------------------------------------------------- #
def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture()
def file_server() -> Iterator:
    with ServerThread() as server:
        yield server


@pytest.fixture()
def aria2_endpoint(tmp_path: Path) -> Iterator[dict[str, str]]:
    if not ARIA2_EXE.exists():
        pytest.skip("aria2c test binary not available in backend/.cache/aria2")
    port = _free_port()
    download_dir = tmp_path / "aria2-downloads"
    download_dir.mkdir()
    process = subprocess.Popen(
        [
            str(ARIA2_EXE),
            "--enable-rpc=true",
            f"--rpc-listen-port={port}",
            "--rpc-listen-all=false",
            f"--rpc-secret={ARIA2_SECRET}",
            f"--dir={download_dir}",
            "--continue=true",
            "--file-allocation=none",
            "--auto-file-renaming=false",
            "--allow-overwrite=true",
            "--summary-interval=0",
            "--console-log-level=error",
            "--max-tries=1",
            "--split=1",
            "--max-connection-per-server=2",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                break
        except OSError:
            time.sleep(0.1)
    else:
        process.kill()
        pytest.fail("aria2 RPC did not start listening")

    try:
        yield {"url": f"http://127.0.0.1:{port}/jsonrpc", "secret": ARIA2_SECRET}
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def make_task_config(tmp_path: Path, aria2_endpoint: dict[str, str]) -> AppConfig:
    data_dir = tmp_path / "data"
    return AppConfig(
        app_env="test",
        data_dir=data_dir,
        download_root=data_dir / "downloads",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'tasks.db').as_posix()}",
        tls_mode="off",
        allow_private_hosts=True,
        public_base_url="http://testserver",
        log_level="ERROR",
        aria2_rpc_url=aria2_endpoint["url"],
        aria2_rpc_secret=aria2_endpoint["secret"],
        task_poll_interval_seconds=0.1,
        scheduler_interval_seconds=0.1,
    )


@pytest.fixture()
def api(tmp_path: Path, aria2_endpoint: dict[str, str], file_server) -> Iterator[tuple]:
    limiter.reset()
    config = make_task_config(tmp_path, aria2_endpoint)
    application = create_app(config)
    with TestClient(application) as client:
        password = read_bootstrap_password(config.bootstrap_file)
        assert login(client, password).status_code == 200
        changed = client.post(
            "/api/auth/password",
            json={"current_password": password, "new_password": NEW_PASSWORD},
        )
        assert changed.status_code == 204
        assert client.put("/api/settings", json={"default_connections": 1}).status_code == 200
        yield client, config, application, file_server
