"""Large file download plus streaming Range retrieval (acceptance item)."""

from __future__ import annotations

import hashlib

from fake_server import LARGE_TOTAL
from helpers import create_task, wait_task

MIB = 1024 * 1024


def _expected_sha() -> str:
    digest = hashlib.sha256()
    block = b"L" * (256 * 1024)
    remaining = LARGE_TOTAL
    while remaining > 0:
        digest.update(block[: min(len(block), remaining)])
        remaining -= min(len(block), remaining)
    return digest.hexdigest()


def test_large_file_download_and_streaming_range(api) -> None:
    client, _, _, server = api
    created = create_task(client, f"{server.base_url}/large.bin")
    task_id = created["task"]["id"]

    finished = wait_task(
        client, task_id, lambda item: item["status"] == "completed", timeout=120.0
    )
    assert finished["file_size"] == LARGE_TOTAL == 64 * MIB
    assert finished["sha256"] == _expected_sha()
    assert finished["download_bytes"] == LARGE_TOTAL

    first = client.get(f"/api/tasks/{task_id}/file", headers={"Range": "bytes=0-1048575"})
    assert first.status_code == 206
    assert len(first.content) == MIB
    assert first.headers["content-range"] == f"bytes 0-1048575/{LARGE_TOTAL}"

    last_start = LARGE_TOTAL - 1024
    tail = client.get(
        f"/api/tasks/{task_id}/file",
        headers={"Range": f"bytes={last_start}-{LARGE_TOTAL - 1}"},
    )
    assert tail.status_code == 206
    assert len(tail.content) == 1024
    assert tail.content == b"L" * 1024
    assert tail.headers["content-range"] == f"bytes {last_start}-{LARGE_TOTAL - 1}/{LARGE_TOTAL}"

    detail = client.get(f"/api/tasks/{task_id}").json()["task"]
    assert detail["retrieved_bytes"] == MIB + 1024
