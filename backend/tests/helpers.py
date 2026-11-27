"""Small helpers shared by the test modules."""

from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

BOOTSTRAP_PASSWORD_LABEL = "密码:"
NEW_PASSWORD = "Ready-Password-2026"


def read_bootstrap_password(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith(BOOTSTRAP_PASSWORD_LABEL):
            return line.split(":", 1)[1].strip()
    raise AssertionError(f"bootstrap password file has unexpected content: {text!r}")


def login(client: TestClient, password: str, username: str = "admin"):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def error_code(response) -> str:
    return response.json()["error"]["code"]


def create_task(client: TestClient, url: str, **extra) -> dict:
    response = client.post("/api/tasks", json={"url": url, **extra})
    assert response.status_code in {200, 201}, response.text
    return response.json()


def wait_task(
    client: TestClient,
    task_id: str,
    predicate: Callable[[dict], bool],
    *,
    timeout: float = 30.0,
) -> dict:
    deadline = time.monotonic() + timeout
    last: dict | None = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/tasks/{task_id}")
        assert response.status_code == 200, response.text
        last = response.json()["task"]
        if predicate(last):
            return last
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for task state; last = {last}")


def completed_task(client: TestClient, url: str) -> dict:
    created = create_task(client, url)
    task = wait_task(
        client, created["task"]["id"], lambda item: item["status"] in {"completed", "failed"}
    )
    assert task["status"] == "completed", task
    return task
