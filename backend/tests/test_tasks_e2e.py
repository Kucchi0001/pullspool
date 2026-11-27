"""End-to-end task lifecycle against a real aria2 process and local files."""

from __future__ import annotations

import asyncio
import hashlib
import sqlite3
import time
from pathlib import Path

import pytest
from conftest import make_task_config
from fake_server import PAYLOAD
from fastapi.testclient import TestClient
from helpers import (
    NEW_PASSWORD,
    login,
    read_bootstrap_password,
)
from helpers import (
    create_task as _create,
)
from helpers import (
    wait_task as _wait,
)

from app.core.config import AppConfig
from app.core.errors import AppError, ErrorCode
from app.core.rate_limit import limiter
from app.database.base import Base
from app.database.session import Database
from app.main import create_app
from app.schemas.settings import RuntimeSettings
from app.services import download_service as download_module
from app.services.download_service import DownloadService
from app.services.event_bus import EventBus
from app.services.settings_service import SettingsService


def test_task_completes_and_stores_sha256(api) -> None:
    client, config, _, server = api
    created = _create(client, f"{server.base_url}/file.bin")
    task_id = created["task"]["id"]
    assert created["duplicate"] is False
    assert created["task"]["status"] in {"queued", "active"}

    task = _wait(client, task_id, lambda item: item["status"] in {"completed", "failed"})
    assert task["status"] == "completed", task
    assert task["sha256"] == hashlib.sha256(PAYLOAD).hexdigest()
    assert task["file_size"] == len(PAYLOAD)
    assert task["ui_status"] == "ready"
    assert task["expires_at"]

    stored = config.download_root / task_id / "file.bin"
    assert stored.exists()
    assert stored.read_bytes() == PAYLOAD

    with sqlite3.connect(config.db_path) as connection:
        download_bytes = connection.execute(
            "SELECT COALESCE(SUM(bytes), 0) FROM traffic_daily WHERE direction = 'down'"
        ).fetchone()[0]
    assert download_bytes == len(PAYLOAD)

    ready = client.get("/api/tasks", params={"scope": "ready"}).json()
    assert ready["total"] == 1
    assert ready["counts"]["ready"] == 1
    assert ready["items"][0]["id"] == task_id


def test_duplicate_url_returns_existing_task(api) -> None:
    client, _, _, server = api
    first = _create(client, f"{server.base_url}/file.bin")
    second = client.post("/api/tasks", json={"url": f"{server.base_url}/file.bin"})
    assert second.status_code == 200
    body = second.json()
    assert body["duplicate"] is True
    assert body["task"]["id"] == first["task"]["id"]


def test_missing_target_is_rejected_at_creation(api) -> None:
    client, _, _, server = api
    response = client.post("/api/tasks", json={"url": f"{server.base_url}/missing.bin"})
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "TARGET_REJECTED"


def test_queue_limit_returns_409(api) -> None:
    client, _, _, server = api
    assert client.put("/api/settings", json={"queue_max_length": 1}).status_code == 200
    created = _create(client, f"{server.base_url}/slow.bin")
    _wait(client, created["task"]["id"], lambda item: item["ui_status"] == "downloading")

    response = client.post("/api/tasks", json={"url": f"{server.base_url}/file.bin"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "QUEUE_FULL"


def test_check_storage_rejects_disk_and_quota(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = AppConfig(
        app_env="test",
        data_dir=tmp_path / "data",
        download_root=tmp_path / "data" / "downloads",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'storage.db').as_posix()}",
        tls_mode="off",
        log_level="ERROR",
    )
    config.ensure_directories()

    async def scenario() -> None:
        database = Database(config.database_url)
        await database.initialize()
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        service = DownloadService(config, database, None, EventBus(), SettingsService())
        try:
            monkeypatch.setattr(
                download_module.storage_service, "disk_usage", lambda root: (1000, 999, 1)
            )
            with pytest.raises(AppError) as disk_error:
                await service._check_storage(
                    RuntimeSettings(min_free_disk_bytes=0, max_total_storage_bytes=10**12), 1000
                )
            assert disk_error.value.code is ErrorCode.DISK_FULL

            monkeypatch.setattr(
                download_module.storage_service, "disk_usage", lambda root: (10**12, 0, 10**12)
            )
            with pytest.raises(AppError) as quota_error:
                await service._check_storage(
                    RuntimeSettings(
                        min_free_disk_bytes=0, max_total_storage_bytes=1024**3
                    ),
                    2 * 1024**3,
                )
            assert quota_error.value.code is ErrorCode.QUOTA_EXCEEDED
        finally:
            await database.dispose()

    asyncio.run(scenario())


def test_pause_and_resume(api) -> None:
    client, _, _, server = api
    created = _create(client, f"{server.base_url}/slow.bin")
    task_id = created["task"]["id"]

    _wait(
        client,
        task_id,
        lambda item: item["ui_status"] == "downloading" and item["downloaded_size"] > 0,
    )
    paused = client.post(f"/api/tasks/{task_id}/pause")
    assert paused.status_code == 200
    assert paused.json()["task"]["status"] == "paused"

    time.sleep(0.6)
    assert client.get(f"/api/tasks/{task_id}").json()["task"]["status"] == "paused"

    resumed = client.post(f"/api/tasks/{task_id}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["task"]["status"] in {"active", "queued"}

    finished = _wait(
        client, task_id, lambda item: item["status"] in {"completed", "failed"}, timeout=40
    )
    assert finished["status"] == "completed", finished
    assert finished["file_size"] == 40 * 64 * 1024


def test_cancel_with_delete_files(api) -> None:
    client, config, _, server = api
    created = _create(client, f"{server.base_url}/slow.bin")
    task_id = created["task"]["id"]
    _wait(client, task_id, lambda item: item["downloaded_size"] > 0)

    response = client.post(f"/api/tasks/{task_id}/cancel", json={"delete_files": True})
    assert response.status_code == 200
    task = response.json()["task"]
    assert task["status"] == "canceled"
    assert task["deleted_at"] is not None
    assert not (config.download_root / task_id).exists()


def test_retry_failed_task(api) -> None:
    client, config, _, server = api
    created = _create(client, f"{server.base_url}/file.bin")
    task_id = created["task"]["id"]
    _wait(client, task_id, lambda item: item["status"] == "completed")

    with sqlite3.connect(config.db_path) as connection:
        connection.execute(
            "UPDATE tasks SET status = 'failed', error_code = 'ARIA2_ERROR', "
            "error_message = 'simulated failure' WHERE id = ?",
            (task_id,),
        )
        connection.commit()

    retried = client.post(f"/api/tasks/{task_id}/retry")
    assert retried.status_code == 200, retried.text
    assert retried.json()["task"]["status"] == "queued"

    finished = _wait(client, task_id, lambda item: item["status"] in {"completed", "failed"})
    assert finished["status"] == "completed", finished
    assert finished["attempts"] == 1
    assert finished["sha256"] == hashlib.sha256(PAYLOAD).hexdigest()


def test_retry_rejects_non_failed_task(api) -> None:
    client, _, _, server = api
    created = _create(client, f"{server.base_url}/file.bin")
    task_id = created["task"]["id"]
    _wait(client, task_id, lambda item: item["status"] == "completed")

    response = client.post(f"/api/tasks/{task_id}/retry")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TASK_STATE_CONFLICT"


def test_list_search_and_sort(api) -> None:
    client, _, _, server = api
    created = _create(client, f"{server.base_url}/file.bin")
    task_id = created["task"]["id"]
    _wait(client, task_id, lambda item: item["status"] == "completed")

    searched = client.get("/api/tasks", params={"scope": "ready", "q": "file"}).json()
    assert searched["total"] == 1
    missing = client.get("/api/tasks", params={"scope": "ready", "q": "nothing-here"}).json()
    assert missing["total"] == 0

    sorted_desc = client.get(
        "/api/tasks", params={"scope": "all", "sort": "filename", "order": "desc"}
    ).json()
    assert sorted_desc["items"][0]["id"] == task_id

    bad = client.get("/api/tasks", params={"sort": "evil"})
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "VALIDATION_ERROR"


def test_task_not_found_for_unknown_id(api) -> None:
    client, _, _, _ = api
    response = client.get("/api/tasks/not-a-real-id")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "TASK_NOT_FOUND"


def test_paused_queued_task_survives_restart(
    tmp_path: Path, aria2_endpoint: dict[str, str], file_server
) -> None:
    """A task paused before it started must not silently resume after restart."""
    limiter.reset()
    config = make_task_config(tmp_path, aria2_endpoint)

    first_app = create_app(config)
    with TestClient(first_app) as first_client:
        password = read_bootstrap_password(config.bootstrap_file)
        assert login(first_client, password).status_code == 200
        assert (
            first_client.post(
                "/api/auth/password",
                json={"current_password": password, "new_password": NEW_PASSWORD},
            ).status_code
            == 204
        )
        assert (
            first_client.put(
                "/api/settings",
                json={"default_connections": 1, "max_concurrent_downloads": 1},
            ).status_code
            == 200
        )
        active = _create(
            first_client, f"{file_server.base_url}/slow.bin", speed_limit_kib_per_s=96
        )
        _wait(first_client, active["task"]["id"], lambda item: item["ui_status"] == "downloading")

        queued = _create(
            first_client, f"{file_server.base_url}/file.bin", speed_limit_kib_per_s=96
        )
        _wait(first_client, queued["task"]["id"], lambda item: item["status"] == "queued")
        paused = first_client.post(f"/api/tasks/{queued['task']['id']}/pause")
        assert paused.status_code == 200
        assert paused.json()["task"]["status"] == "paused"

    second_app = create_app(config)
    with TestClient(second_app) as second_client:
        assert login(second_client, NEW_PASSWORD).status_code == 200
        detail = second_client.get(f"/api/tasks/{queued['task']['id']}")
        assert detail.status_code == 200
        assert detail.json()["task"]["status"] == "paused"


def test_task_survives_backend_restart(
    tmp_path: Path, aria2_endpoint: dict[str, str], file_server
) -> None:
    """A running download must keep going while the backend is restarted."""
    limiter.reset()
    config = make_task_config(tmp_path, aria2_endpoint)

    first_app = create_app(config)
    with TestClient(first_app) as first_client:
        password = read_bootstrap_password(config.bootstrap_file)
        assert login(first_client, password).status_code == 200
        assert (
            first_client.post(
                "/api/auth/password",
                json={"current_password": password, "new_password": NEW_PASSWORD},
            ).status_code
            == 204
        )
        assert (
            first_client.put("/api/settings", json={"default_connections": 1}).status_code
            == 200
        )
        created = _create(first_client, f"{file_server.base_url}/slow.bin")
        task_id = created["task"]["id"]
        _wait(first_client, task_id, lambda item: item["downloaded_size"] > 0)

    # The backend is down here; aria2 keeps downloading in the background.
    second_app = create_app(config)
    with TestClient(second_app) as second_client:
        assert login(second_client, NEW_PASSWORD).status_code == 200
        recovered = _wait(
            second_client,
            task_id,
            lambda item: item["status"] in {"completed", "failed"},
            timeout=40,
        )
    assert recovered["status"] == "completed", recovered
    assert recovered["file_size"] == 40 * 64 * 1024
    assert (config.download_root / task_id / "slow.bin").exists()
