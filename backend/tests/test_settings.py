"""Runtime settings endpoints and persistence."""

from __future__ import annotations

import json
import sqlite3

from fastapi.testclient import TestClient
from helpers import error_code

from app.core.config import AppConfig


def test_settings_require_auth(client: TestClient) -> None:
    response = client.get("/api/settings")
    assert response.status_code == 401
    assert error_code(response) == "AUTH_REQUIRED"


def test_settings_defaults(ready_client: TestClient) -> None:
    response = ready_client.get("/api/settings")
    assert response.status_code == 200
    body = response.json()
    assert body["settings"]["max_concurrent_downloads"] == 2
    assert body["settings"]["default_speed_limit_kib_per_s"] == 0
    assert body["settings"]["retention_hours"] == 24
    assert body["settings"]["theme"] == "system"
    assert body["meta"]["version"]
    assert body["meta"]["read_only_keys"] == ["storage_subdir"]


def test_update_settings_partial(ready_client: TestClient) -> None:
    response = ready_client.put(
        "/api/settings", json={"max_concurrent_downloads": 3, "retention_hours": 48}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["settings"]["max_concurrent_downloads"] == 3
    assert body["settings"]["retention_hours"] == 48
    assert set(body["applied"]) == {"max_concurrent_downloads", "retention_hours"}

    again = ready_client.get("/api/settings").json()["settings"]
    assert again["max_concurrent_downloads"] == 3
    assert again["retention_hours"] == 48


def test_update_settings_out_of_range(ready_client: TestClient) -> None:
    response = ready_client.put("/api/settings", json={"max_concurrent_downloads": 99})
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "SETTINGS_INVALID"
    assert body["error"]["details"]["key"] == "max_concurrent_downloads"


def test_update_settings_unknown_key(ready_client: TestClient) -> None:
    response = ready_client.put("/api/settings", json={"not_a_setting": 1})
    assert response.status_code == 400
    assert error_code(response) == "VALIDATION_ERROR"


def test_settings_persisted_in_database(ready_client: TestClient, config: AppConfig) -> None:
    ready_client.put("/api/settings", json={"default_connections": 7})
    with sqlite3.connect(config.db_path) as connection:
        row = connection.execute("SELECT value FROM settings WHERE key = 'default_connections'").fetchone()
    assert row is not None
    assert json.loads(row[0]) == 7
