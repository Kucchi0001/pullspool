"""HTTP-level security checks: SSRF gate, rate limiting, filename containment."""

from __future__ import annotations

from pathlib import Path

import pytest
from fake_server import PAYLOAD
from fastapi.testclient import TestClient
from helpers import create_task, wait_task

from app.core.config import AppConfig
from app.core.rate_limit import limiter
from app.main import create_app

SSRF_URLS = [
    "http://127.0.0.1:8000/api/health",
    "http://localhost:8000/",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.1/",
    "http://192.168.1.1/",
    "http://[::1]/",
    "http://metadata.google.internal/computeMetadata/v1/",
]


@pytest.mark.parametrize("url", SSRF_URLS)
def test_private_targets_are_rejected_by_the_api(ready_client: TestClient, url: str) -> None:
    response = ready_client.post("/api/tasks", json={"url": url})
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "SSRF_BLOCKED"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("file:///etc/passwd", "URL_SCHEME_NOT_ALLOWED"),
        ("ftp://example.com/a.zip", "URL_SCHEME_NOT_ALLOWED"),
        ("javascript:alert(1)", "URL_SCHEME_NOT_ALLOWED"),
        ("http://user:pass@example.com/a.zip", "URL_INVALID"),
        ("http://example.com:99999/", "URL_INVALID"),
    ],
)
def test_bad_schemes_and_urls_are_rejected(
    ready_client: TestClient, url: str, expected: str
) -> None:
    response = ready_client.post("/api/tasks", json={"url": url})
    assert response.status_code in {400, 403}, response.text
    assert response.json()["error"]["code"] == expected


def test_global_api_rate_limit(tmp_path: Path) -> None:
    limiter.reset()
    config = AppConfig(
        app_env="test",
        data_dir=tmp_path / "data",
        download_root=tmp_path / "data" / "downloads",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'rate.db').as_posix()}",
        tls_mode="off",
        log_level="ERROR",
        api_rate_limit_per_minute=10,
    )
    application = create_app(config)
    with TestClient(application) as client:
        for _ in range(10):
            assert client.get("/api/health").status_code == 200
        blocked = client.get("/api/health")
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "RATE_LIMITED"
    assert int(blocked.headers["Retry-After"]) >= 1


def test_events_stream_is_not_rate_limited_by_the_middleware(
    ready_client: TestClient,
) -> None:
    # EventSource reconnects must not be throttled by the coarse API limiter.
    with ready_client.stream("GET", "/api/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")


def test_filename_traversal_is_contained(api) -> None:
    client, config, _, server = api
    created = create_task(client, f"{server.base_url}/file.bin", filename="../../evil.sh")
    task = created["task"]
    assert "/" not in task["filename"]
    assert "\\" not in task["filename"]

    finished = wait_task(client, task["id"], lambda item: item["status"] == "completed")
    stored = config.download_root / finished["id"] / finished["filename"]
    assert stored.exists()
    assert stored.resolve().parent == (config.download_root / finished["id"]).resolve()
    assert stored.read_bytes() == PAYLOAD
    assert not (config.download_root.parent / "evil.sh").exists()


def test_task_creation_requires_authentication(client: TestClient) -> None:
    response = client.post("/api/tasks", json={"url": "https://example.com/a.zip"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
