"""Authentication, session and CSRF behaviour."""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient
from helpers import NEW_PASSWORD, error_code, login, read_bootstrap_password

from app.core.config import AppConfig


def test_bootstrap_creates_admin_and_password_file(client: TestClient, config: AppConfig) -> None:
    assert config.bootstrap_file.exists()
    password = read_bootstrap_password(config.bootstrap_file)
    assert config.bootstrap_username == "admin"
    assert password == "admin"
    text = config.bootstrap_file.read_text(encoding="utf-8")
    assert "用户名: admin" in text
    assert "默认初始密码 admin" in text


def test_me_requires_auth(client: TestClient) -> None:
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert error_code(response) == "AUTH_REQUIRED"


def test_login_wrong_password(client: TestClient) -> None:
    response = login(client, "definitely-not-the-password")
    assert response.status_code == 401
    assert error_code(response) == "AUTH_INVALID"


def test_unknown_user_is_rejected(client: TestClient) -> None:
    response = login(client, "whatever", username="nobody")
    assert response.status_code == 401
    assert error_code(response) == "AUTH_INVALID"


def test_login_success_sets_cookie(client: TestClient, config: AppConfig) -> None:
    password = read_bootstrap_password(config.bootstrap_file)
    response = login(client, password)
    assert response.status_code == 200
    payload = response.json()
    assert payload["user"]["username"] == config.bootstrap_username
    assert payload["user"]["must_change_password"] is True
    assert config.cookie_name in client.cookies
    assert "httponly" in response.headers["set-cookie"].lower()


def test_me_after_login(client: TestClient, config: AppConfig) -> None:
    login(client, read_bootstrap_password(config.bootstrap_file))
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    body = response.json()
    assert body["user"]["username"] == config.bootstrap_username
    assert body["server"]["version"] == config.version
    assert body["server"]["uptime_seconds"] >= 0


def test_password_change_required_blocks_api(client: TestClient, config: AppConfig) -> None:
    login(client, read_bootstrap_password(config.bootstrap_file))
    response = client.get("/api/settings")
    assert response.status_code == 403
    assert error_code(response) == "PASSWORD_CHANGE_REQUIRED"


def test_weak_password_rejected(client: TestClient, config: AppConfig) -> None:
    password = read_bootstrap_password(config.bootstrap_file)
    login(client, password)
    response = client.post(
        "/api/auth/password",
        json={"current_password": password, "new_password": "short"},
    )
    assert response.status_code == 400
    assert error_code(response) == "WEAK_PASSWORD"


def test_password_change_requires_current_password(client: TestClient, config: AppConfig) -> None:
    password = read_bootstrap_password(config.bootstrap_file)
    login(client, password)
    response = client.post(
        "/api/auth/password",
        json={"current_password": "wrong-current", "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 401
    assert error_code(response) == "AUTH_INVALID"


def test_password_change_success_unlocks_api(client: TestClient, config: AppConfig) -> None:
    password = read_bootstrap_password(config.bootstrap_file)
    login(client, password)
    response = client.post(
        "/api/auth/password",
        json={"current_password": password, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 204
    assert not config.bootstrap_file.exists()

    me = client.get("/api/auth/me").json()
    assert me["user"]["must_change_password"] is False
    assert client.get("/api/settings").status_code == 200


def test_logout_revokes_session(ready_client: TestClient) -> None:
    assert ready_client.get("/api/auth/me").status_code == 200
    response = ready_client.post("/api/auth/logout")
    assert response.status_code == 204
    after = ready_client.get("/api/auth/me")
    assert after.status_code == 401
    assert error_code(after) in {"AUTH_REQUIRED", "SESSION_EXPIRED"}


def test_lockout_after_repeated_failures(client: TestClient, config: AppConfig) -> None:
    for _ in range(4):
        response = login(client, "wrong-password")
        assert response.status_code == 401

    # The fifth failure trips the lock and is reported as locked immediately.
    fifth = login(client, "wrong-password")
    assert fifth.status_code == 429
    assert error_code(fifth) == "AUTH_LOCKED"

    blocked = login(client, read_bootstrap_password(config.bootstrap_file))
    assert blocked.status_code == 429
    assert error_code(blocked) == "AUTH_LOCKED"
    assert int(blocked.headers["Retry-After"]) > 0


def test_password_change_revokes_other_sessions(client: TestClient, config: AppConfig) -> None:
    password = read_bootstrap_password(config.bootstrap_file)
    login(client, password)
    first_cookie = client.cookies.get(config.cookie_name)
    assert first_cookie

    client.cookies.clear()
    login(client, password)
    response = client.post(
        "/api/auth/password",
        json={"current_password": password, "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 204

    client.cookies.clear()
    old_session = client.get(
        "/api/auth/me", headers={"Cookie": f"{config.cookie_name}={first_cookie}"}
    )
    assert old_session.status_code == 401
    assert error_code(old_session) == "SESSION_EXPIRED"


def test_expired_session_is_rejected(ready_client: TestClient, config: AppConfig) -> None:
    with sqlite3.connect(config.db_path) as connection:
        connection.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00Z'")
        connection.commit()

    response = ready_client.get("/api/auth/me")
    assert response.status_code == 401
    assert error_code(response) == "SESSION_EXPIRED"


def test_csrf_rejects_cross_origin(client: TestClient) -> None:
    response = client.post("/api/auth/logout", headers={"Origin": "http://evil.example"})
    assert response.status_code == 403
    assert error_code(response) == "ORIGIN_MISMATCH"


def test_csrf_rejects_cross_site_fetch_metadata(client: TestClient) -> None:
    response = client.post(
        "/api/auth/logout",
        headers={"Sec-Fetch-Site": "cross-site", "Origin": "http://testserver"},
    )
    assert response.status_code == 403
    assert error_code(response) == "ORIGIN_MISMATCH"


def test_csrf_allows_same_origin(client: TestClient) -> None:
    response = client.post("/api/auth/logout", headers={"Origin": "http://testserver"})
    assert response.status_code == 204


def test_csrf_allows_forwarded_proxy_host(client: TestClient) -> None:
    response = client.post(
        "/api/auth/logout",
        headers={
            "Origin": "http://pull.example:18080",
            "X-Forwarded-Host": "pull.example:18080",
        },
    )
    assert response.status_code == 204


def test_csrf_allows_non_browser_client(client: TestClient) -> None:
    response = client.post("/api/auth/logout")
    assert response.status_code == 204


def test_login_rate_limit_by_ip(client: TestClient) -> None:
    for _ in range(20):
        login(client, "wrong-password")
    blocked = login(client, "wrong-password")
    assert blocked.status_code == 429
    assert error_code(blocked) == "RATE_LIMITED"


def test_events_require_auth(client: TestClient) -> None:
    response = client.get("/api/events")
    assert response.status_code == 401
    assert error_code(response) == "AUTH_REQUIRED"

def test_failed_login_is_audited_without_password(api, caplog) -> None:
    import logging

    client, _, _, _ = api
    with caplog.at_level(logging.WARNING, logger="pullspool.auth"):
        response = client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "Wrong-Pass-123"},
        )
    assert response.status_code == 401
    messages = [record.getMessage() for record in caplog.records]
    assert any("登录失败" in message and "admin" in message for message in messages)
    assert all("Wrong-Pass-123" not in message for message in messages)

def test_change_username_and_login_with_new_name(ready_client: TestClient) -> None:
    response = ready_client.post(
        "/api/auth/username",
        json={"new_username": "Spool.Admin", "current_password": NEW_PASSWORD},
    )
    assert response.status_code == 200, response.text
    assert response.json()["username"] == "spool.admin"
    assert ready_client.get("/api/auth/me").json()["user"]["username"] == "spool.admin"

    assert ready_client.post("/api/auth/logout").status_code == 204
    assert login(ready_client, NEW_PASSWORD, username="admin").status_code == 401
    assert login(ready_client, NEW_PASSWORD, username="spool.admin").status_code == 200


def test_change_username_requires_current_password(ready_client: TestClient) -> None:
    response = ready_client.post(
        "/api/auth/username",
        json={"new_username": "another-name", "current_password": "wrong-password"},
    )
    assert response.status_code == 401
    assert error_code(response) == "AUTH_INVALID"
    assert ready_client.get("/api/auth/me").json()["user"]["username"] == "admin"


def test_change_username_rejects_invalid_names(ready_client: TestClient) -> None:
    for candidate in ["ab", "-bad", "bad name", "用户user", "bad/name"]:
        response = ready_client.post(
            "/api/auth/username",
            json={"new_username": candidate, "current_password": NEW_PASSWORD},
        )
        assert response.status_code == 400, (candidate, response.text)
        assert error_code(response) in {"USERNAME_INVALID", "VALIDATION_ERROR"}


def test_change_username_rejects_taken_name(
    ready_client: TestClient, config: AppConfig
) -> None:
    with sqlite3.connect(config.db_path) as connection:
        connection.execute(
            "INSERT INTO users (username, password_hash, must_change_password, created_at,"
            " failed_login_count) VALUES (?, ?, 0, ?, 0)",
            ("taken", "not-a-real-hash", "2026-01-01T00:00:00Z"),
        )
        connection.commit()

    response = ready_client.post(
        "/api/auth/username",
        json={"new_username": "taken", "current_password": NEW_PASSWORD},
    )
    assert response.status_code == 409, response.text
    assert error_code(response) == "USERNAME_TAKEN"


def test_change_username_requires_authentication(client: TestClient) -> None:
    response = client.post(
        "/api/auth/username",
        json={"new_username": "nobody-new", "current_password": "whatever"},
    )
    assert response.status_code == 401
    assert error_code(response) == "AUTH_REQUIRED"

def test_change_username_blocked_before_password_change(
    client: TestClient, config: AppConfig
) -> None:
    login(client, read_bootstrap_password(config.bootstrap_file))
    response = client.post(
        "/api/auth/username",
        json={"new_username": "too-early", "current_password": "whatever"},
    )
    assert response.status_code == 403
    assert error_code(response) == "PASSWORD_CHANGE_REQUIRED"

def test_bootstrap_credentials_env_aliases(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("BOOTSTRAP_ADMIN_USERNAME", "ops")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "Alias-Override-123")
    config = AppConfig(_env_file=None, data_dir=tmp_path)
    assert config.bootstrap_username == "ops"
    assert config.bootstrap_password == "Alias-Override-123"
