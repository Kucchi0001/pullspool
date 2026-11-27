"""Unit tests for hashing, password policy, download tokens and redaction."""

from __future__ import annotations

import pytest

from app.core.errors import AppError, ErrorCode
from app.core.logging import redact, redact_url
from app.core.security import (
    generate_password,
    hash_password,
    issue_download_token,
    validate_password,
    verify_download_token,
    verify_password,
)


def test_hash_roundtrip() -> None:
    hashed = hash_password("Str0ng-Passw0rd")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "Str0ng-Passw0rd") is True
    assert verify_password(hashed, "str0ng-passw0rd") is False


def test_validate_password_accepts_strong() -> None:
    validate_password("Str0ng-Passw0rd", username="admin")


@pytest.mark.parametrize(
    "candidate",
    ["short1", "onlylettershere", "123456789012", "password123", "changeme123"],
)
def test_validate_password_rejects_weak(candidate: str) -> None:
    with pytest.raises(AppError) as excinfo:
        validate_password(candidate, username="admin")
    assert excinfo.value.code is ErrorCode.WEAK_PASSWORD


def test_validate_password_rejects_username_echo() -> None:
    with pytest.raises(AppError):
        validate_password("Adminuser1", username="adminuser1")


def test_generate_password_shape() -> None:
    password = generate_password()
    assert len(password) == 32
    assert any(c.isdigit() for c in password)
    assert any(c.isalpha() for c in password)


def test_download_token_roundtrip() -> None:
    token, expires_at = issue_download_token("task-123", "super-secret", 120)
    payload = verify_download_token(token, "super-secret")
    assert payload["tid"] == "task-123"
    assert payload["exp"] == expires_at


def test_download_token_rejects_tampering() -> None:
    token, _ = issue_download_token("task-123", "super-secret", 120)
    with pytest.raises(AppError) as excinfo:
        verify_download_token(token + "tamper", "super-secret")
    assert excinfo.value.code is ErrorCode.TOKEN_INVALID


def test_download_token_rejects_wrong_secret() -> None:
    token, _ = issue_download_token("task-123", "super-secret", 120)
    with pytest.raises(AppError) as excinfo:
        verify_download_token(token, "another-secret")
    assert excinfo.value.code is ErrorCode.TOKEN_INVALID


def test_download_token_expires() -> None:
    token, _ = issue_download_token("task-123", "super-secret", -5)
    with pytest.raises(AppError) as excinfo:
        verify_download_token(token, "super-secret")
    assert excinfo.value.code is ErrorCode.TOKEN_EXPIRED


def test_redact_url_drops_query_and_credentials() -> None:
    assert redact_url("https://user:pass@example.com/file.zip?token=abc") == (
        "https://example.com/file.zip?***"
    )
    assert redact_url("http://example.com/file.zip") == "http://example.com/file.zip"


def test_redact_removes_key_values() -> None:
    message = "login failed password=hunter2 token=abc123 https://example.com/a?key=secret"
    cleaned = redact(message)
    assert "hunter2" not in cleaned
    assert "abc123" not in cleaned
    assert "key=secret" not in cleaned

def test_query_redactor_scrubs_access_log_records() -> None:
    import logging as logging_module

    from app.core.logging import QueryRedactor

    record = logging_module.LogRecord(
        "uvicorn.access",
        logging_module.INFO,
        __file__,
        1,
        'GET /api/tasks/x/file?token=super-secret-token HTTP/1.1',
        (),
        None,
    )
    QueryRedactor().filter(record)
    message = record.getMessage()
    assert "super-secret-token" not in message
    assert "token=***" in message
