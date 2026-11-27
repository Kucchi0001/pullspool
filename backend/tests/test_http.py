"""HTTP semantics: health, envelopes, headers, limits."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from helpers import error_code

from app.core.config import AppConfig
from app.main import create_app
from app.services.aria2_service import Aria2Client


def test_health_is_public_and_ok(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["checks"]["db"] == "ok"
    assert body["checks"]["disk"] in {"ok", "low"}


def test_security_headers_present(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-Request-ID"]


def test_request_id_is_echoed(client: TestClient) -> None:
    response = client.get("/api/health", headers={"X-Request-ID": "abcd1234efgh"})
    assert response.headers["X-Request-ID"] == "abcd1234efgh"


def test_request_id_is_generated_when_missing(client: TestClient) -> None:
    response = client.get("/api/health")
    assert len(response.headers["X-Request-ID"]) == 16


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["request_id"]


def test_method_not_allowed(client: TestClient) -> None:
    response = client.get("/api/auth/login")
    assert response.status_code == 405
    assert error_code(response) == "METHOD_NOT_ALLOWED"


def test_validation_error_lists_fields(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={})
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"]["fields"]


def test_no_cors_headers(client: TestClient) -> None:
    response = client.options(
        "/api/auth/login",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in {k.lower() for k in response.headers}


def test_json_body_limit(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    config = AppConfig(
        app_env="test",
        data_dir=data_dir,
        download_root=data_dir / "downloads",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'limit.db').as_posix()}",
        tls_mode="off",
        max_json_body_bytes=1024,
        log_level="ERROR",
    )
    application = create_app(config)
    with TestClient(application) as test_client:
        response = test_client.post(
            "/api/auth/login",
            content=b"x" * 4096,
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 413
    assert response.json()["error"]["details"]["max_bytes"] == 1024


def test_health_degraded_when_aria2_unreachable(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    config = AppConfig(
        app_env="test",
        data_dir=data_dir,
        download_root=data_dir / "downloads",
        database_url=f"sqlite+aiosqlite:///{(tmp_path / 'health.db').as_posix()}",
        tls_mode="off",
        aria2_rpc_url="http://127.0.0.1:9/jsonrpc",
        log_level="ERROR",
    )
    application = create_app(config)
    with TestClient(application) as test_client:
        aria2_client = Aria2Client(
            "http://127.0.0.1:9/jsonrpc", "secret", timeout_seconds=1
        )
        application.state.aria2 = aria2_client
        try:
            body = test_client.get("/api/health").json()
        finally:
            application.state.aria2 = None
    assert body["status"] == "degraded"
    assert body["checks"]["aria2"] == "error"
    assert body["checks"]["db"] == "ok"
