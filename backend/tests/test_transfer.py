"""File retrieval (Range), download tokens, ack, cleanup and system endpoints."""

from __future__ import annotations

import sqlite3

from fake_server import PAYLOAD
from helpers import completed_task, create_task, wait_task

from app.core.security import issue_download_token

SIZE = len(PAYLOAD)


def _file_url(task_id: str) -> str:
    return f"/api/tasks/{task_id}/file"


def test_full_download_and_accounting(api) -> None:
    client, config, _, server = api
    task = completed_task(client, f"{server.base_url}/file.bin")

    response = client.get(_file_url(task["id"]))
    assert response.status_code == 200
    assert response.content == PAYLOAD
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == str(SIZE)
    assert response.headers["content-disposition"].startswith("attachment;")
    assert "filename*=UTF-8''" in response.headers["content-disposition"]
    assert response.headers["etag"].endswith(f'{SIZE}"')

    with sqlite3.connect(config.db_path) as connection:
        uploaded = connection.execute(
            "SELECT COALESCE(SUM(bytes), 0) FROM traffic_daily WHERE direction = 'up'"
        ).fetchone()[0]
    assert uploaded == SIZE

    detail = client.get(f"/api/tasks/{task['id']}").json()["task"]
    assert detail["retrieved_bytes"] == SIZE
    assert detail["transfer_count"] == 1
    assert detail["ui_status"] == "ready"


def test_range_requests(api) -> None:
    client, _, _, server = api
    task = completed_task(client, f"{server.base_url}/file.bin")
    url = _file_url(task["id"])

    partial = client.get(url, headers={"Range": "bytes=0-99"})
    assert partial.status_code == 206
    assert partial.content == PAYLOAD[:100]
    assert partial.headers["content-range"] == f"bytes 0-99/{SIZE}"
    assert partial.headers["content-length"] == "100"

    suffix = client.get(url, headers={"Range": "bytes=-50"})
    assert suffix.status_code == 206
    assert suffix.content == PAYLOAD[-50:]
    assert suffix.headers["content-range"] == f"bytes {SIZE - 50}-{SIZE - 1}/{SIZE}"

    middle = client.get(url, headers={"Range": "bytes=100-199"})
    assert middle.status_code == 206
    assert middle.content == PAYLOAD[100:200]


def test_unsatisfiable_range(api) -> None:
    client, _, _, server = api
    task = completed_task(client, f"{server.base_url}/file.bin")

    response = client.get(_file_url(task["id"]), headers={"Range": f"bytes={SIZE}-"})
    assert response.status_code == 416
    assert response.json()["error"]["code"] == "RANGE_NOT_SATISFIABLE"
    assert response.headers["content-range"] == f"bytes */{SIZE}"


def test_if_range_validation(api) -> None:
    client, _, _, server = api
    task = completed_task(client, f"{server.base_url}/file.bin")
    etag = client.get(_file_url(task["id"])).headers["etag"]

    stale = client.get(
        _file_url(task["id"]), headers={"Range": "bytes=0-9", "If-Range": '"stale"'}
    )
    assert stale.status_code == 200
    assert stale.content == PAYLOAD

    fresh = client.get(
        _file_url(task["id"]), headers={"Range": "bytes=0-9", "If-Range": etag}
    )
    assert fresh.status_code == 206
    assert fresh.content == PAYLOAD[:10]


def test_download_requires_auth(api) -> None:
    client, _, _, server = api
    task = completed_task(client, f"{server.base_url}/file.bin")
    client.cookies.clear()

    response = client.get(_file_url(task["id"]))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_download_token_flow(api) -> None:
    client, _, _, server = api
    task = completed_task(client, f"{server.base_url}/file.bin")

    issued = client.post(f"/api/tasks/{task['id']}/download-token")
    assert issued.status_code == 200
    body = issued.json()
    assert body["url"].endswith(f"/api/tasks/{task['id']}/file?token={body['url'].split('token=')[1]}")
    assert body["ttl_seconds"] >= 60

    client.cookies.clear()
    response = client.get(body["url"])
    assert response.status_code == 200
    assert response.content == PAYLOAD


def test_download_token_is_bound_to_task(api) -> None:
    client, config, _, server = api
    first = completed_task(client, f"{server.base_url}/file.bin")
    second = completed_task(client, f"{server.base_url}/toggle.bin")

    token, _ = issue_download_token(first["id"], config.download_token_secret, 300)
    response = client.get(_file_url(second["id"]), params={"token": token})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"


def test_expired_download_token(api) -> None:
    client, config, _, server = api
    task = completed_task(client, f"{server.base_url}/file.bin")
    token, _ = issue_download_token(task["id"], config.download_token_secret, -5)

    response = client.get(_file_url(task["id"]), params={"token": token})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "TOKEN_EXPIRED"


def test_ack_deletes_files_and_is_idempotent(api) -> None:
    client, config, _, server = api
    task = completed_task(client, f"{server.base_url}/file.bin")
    task_id = task["id"]
    assert (config.download_root / task_id).exists()

    first = client.post(f"/api/tasks/{task_id}/ack", json={"confirm": True})
    assert first.status_code == 200, first.text
    acknowledged = first.json()["task"]
    assert acknowledged["deleted_at"] is not None
    assert acknowledged["retrieved_at"] is not None
    assert acknowledged["sha256"] == task["sha256"]
    assert acknowledged["ui_status"] in {"retrieved", "deleted"}
    assert not (config.download_root / task_id).exists()

    second = client.post(f"/api/tasks/{task_id}/ack", json={"confirm": True})
    assert second.status_code == 200
    assert second.json()["task"]["deleted_at"] == acknowledged["deleted_at"]

    missing = client.get(_file_url(task_id))
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "FILE_NOT_FOUND"

    integrity = client.get(f"/api/tasks/{task_id}/integrity")
    assert integrity.status_code == 200
    assert integrity.json()["sha256"] == task["sha256"]


def test_ack_rejected_while_transferring(api) -> None:
    client, _, application, server = api
    task = completed_task(client, f"{server.base_url}/file.bin")

    transfers = application.state.transfers
    assert transfers._acquire(task["id"], 5)
    try:
        response = client.post(f"/api/tasks/{task['id']}/ack", json={"confirm": True})
    finally:
        transfers._release(task["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TRANSFER_IN_PROGRESS"


def test_ack_requires_completed(api) -> None:
    client, _, _, server = api
    created = create_task(client, f"{server.base_url}/slow.bin")
    task_id = created["task"]["id"]
    wait_task(client, task_id, lambda item: item["ui_status"] == "downloading")

    response = client.post(f"/api/tasks/{task_id}/ack", json={"confirm": True})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "TASK_STATE_CONFLICT"


def test_transfer_concurrency_limit(api) -> None:
    client, _, application, server = api
    task = completed_task(client, f"{server.base_url}/file.bin")
    assert client.put("/api/settings", json={"max_transfer_concurrency": 1}).status_code == 200

    transfers = application.state.transfers
    assert transfers._acquire("some-other-task", 1)
    try:
        response = client.get(_file_url(task["id"]))
    finally:
        transfers._release("some-other-task")

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "RATE_LIMITED"


def test_integrity_endpoint(api) -> None:
    client, _, _, server = api
    task = completed_task(client, f"{server.base_url}/file.bin")

    response = client.get(f"/api/tasks/{task['id']}/integrity")
    assert response.status_code == 200
    body = response.json()
    assert body["sha256"] == task["sha256"]
    assert body["file_size"] == SIZE
    assert body["expected_sha256"] is None
    assert body["matches_expected"] is None
    assert "note" in body

    created = create_task(client, f"{server.base_url}/slow.bin")
    pending = client.get(f"/api/tasks/{created['task']['id']}/integrity")
    assert pending.status_code == 409
    assert pending.json()["error"]["code"] == "TASK_STATE_CONFLICT"


def test_expired_task_is_cleaned_up(api) -> None:
    client, config, application, server = api
    task = completed_task(client, f"{server.base_url}/file.bin")
    task_id = task["id"]

    with sqlite3.connect(config.db_path) as connection:
        connection.execute(
            "UPDATE tasks SET expires_at = '2000-01-01T00:00:00Z' WHERE id = ?", (task_id,)
        )
        connection.commit()

    result = client.portal.call(application.state.cleanup.run_once)
    assert result["expired"] == 1

    detail = client.get(f"/api/tasks/{task_id}").json()["task"]
    assert detail["deleted_at"] is not None
    assert detail["ui_status"] == "expired"
    assert not (config.download_root / task_id).exists()


def test_orphan_directories_are_quarantined(api) -> None:
    client, config, application, _ = api
    stray = config.download_root / "stray-directory"
    stray.mkdir()
    (stray / "leftover.bin").write_bytes(b"orphan")

    result = client.portal.call(application.state.cleanup.run_once)
    assert result["orphans"] == 1
    assert not stray.exists()

    orphans = list((config.download_root / ".orphan").iterdir())
    assert len(orphans) == 1
    assert (orphans[0] / "leftover.bin").exists()


def test_system_endpoints(api) -> None:
    client, _, _, server = api
    task = completed_task(client, f"{server.base_url}/file.bin")
    assert client.get(_file_url(task["id"])).status_code == 200

    status = client.get("/api/system/status")
    assert status.status_code == 200
    body = status.json()
    assert body["server"]["version"]
    assert body["host"]["mem_total"] > 0
    assert body["storage"]["root"]
    assert body["counts"]["ready"] == 1
    assert body["aria2"]["reachable"] is True
    assert body["queue"]["max_concurrent"] >= 1

    storage = client.get("/api/system/storage").json()
    assert storage["downloads_bytes"] >= SIZE
    assert storage["tasks"]

    traffic = client.get("/api/system/traffic", params={"days": 7}).json()
    assert len(traffic["days"]) == 7
    assert traffic["totals"]["today_upload_bytes"] == SIZE
    assert traffic["note"]

    bad_tz = client.get("/api/system/traffic", params={"tz": "Not/AZone"})
    assert bad_tz.status_code == 400
    assert bad_tz.json()["error"]["code"] == "VALIDATION_ERROR"


def test_system_endpoints_require_auth(api) -> None:
    client, _, _, _ = api
    client.cookies.clear()
    assert client.get("/api/system/status").status_code == 401
    assert client.get("/api/system/storage").status_code == 401
    assert client.get("/api/system/traffic").status_code == 401
