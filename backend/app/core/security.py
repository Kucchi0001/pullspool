"""Password hashing, token generation and download-token signing."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import string
import time
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.errors import AppError, ErrorCode

# Tuned for 1 vCPU / 1 GB: about 60-120 ms per verification.
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128

COMMON_PASSWORDS = {
    "password",
    "password1",
    "password123",
    "1234567890",
    "12345678",
    "qwerty123",
    "admin123",
    "administrator",
    "letmein123",
    "welcome123",
    "iloveyou",
    "changeme",
    "changeme123",
    "pullspool",
    "vpsfetch",
    "download123",
    "abcd123456",
    "a1234567890",
    "1qaz2wsx3edc",
    "qwertyuiop",
}

_TOKEN_ALPHABET = string.ascii_letters + string.digits


# --------------------------------------------------------------------------- #
# passwords
# --------------------------------------------------------------------------- #
def hash_password(raw: str) -> str:
    return _hasher.hash(raw)


def verify_password(stored_hash: str, raw: str) -> bool:
    try:
        return _hasher.verify(stored_hash, raw)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:  # pragma: no cover - defensive
        return True


def _character_classes(password: str) -> int:
    patterns = (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]")
    return sum(1 for pattern in patterns if re.search(pattern, password))


def validate_password(password: str, *, username: str = "") -> None:
    """Raise ``WEAK_PASSWORD`` when the password does not meet the policy."""
    if len(password) < PASSWORD_MIN_LENGTH:
        raise AppError(ErrorCode.WEAK_PASSWORD, f"密码至少需要 {PASSWORD_MIN_LENGTH} 位")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise AppError(ErrorCode.WEAK_PASSWORD, f"密码不能超过 {PASSWORD_MAX_LENGTH} 位")
    if _character_classes(password) < 2:
        raise AppError(ErrorCode.WEAK_PASSWORD, "密码需同时包含字母与数字（或符号）")
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS:
        raise AppError(ErrorCode.WEAK_PASSWORD, "该密码过于常见，请更换")
    if username and lowered == username.lower():
        raise AppError(ErrorCode.WEAK_PASSWORD, "密码不能与用户名相同")


def generate_password(length: int = 32) -> str:
    """Random password without visually ambiguous characters."""
    alphabet = "".join(c for c in _TOKEN_ALPHABET if c not in "Il1O0o")
    while True:
        candidate = "".join(secrets.choice(alphabet) for _ in range(length))
        # Guarantee at least one letter and one digit.
        if any(c.isdigit() for c in candidate) and any(c.isalpha() for c in candidate):
            return candidate


# --------------------------------------------------------------------------- #
# session tokens
# --------------------------------------------------------------------------- #
def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def constant_time_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


# --------------------------------------------------------------------------- #
# download tokens (stateless, HMAC signed)
# --------------------------------------------------------------------------- #
def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def issue_download_token(task_id: str, secret: str, ttl_seconds: int) -> tuple[str, int]:
    """Return ``(token, expires_at_epoch)`` bound to a single task."""
    expires_at = int(time.time()) + int(ttl_seconds)
    payload = json.dumps(
        {"tid": task_id, "exp": expires_at, "nonce": secrets.token_urlsafe(8)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return f"{_b64encode(payload)}.{_b64encode(signature)}", expires_at


def verify_download_token(token: str, secret: str) -> dict[str, Any]:
    """Validate a download token, raising ``TOKEN_INVALID`` / ``TOKEN_EXPIRED``."""
    if not token or token.count(".") != 1:
        raise AppError(ErrorCode.TOKEN_INVALID)
    encoded_payload, encoded_signature = token.split(".", 1)
    try:
        payload = _b64decode(encoded_payload)
        signature = _b64decode(encoded_signature)
    except (ValueError, TypeError):
        raise AppError(ErrorCode.TOKEN_INVALID) from None

    expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise AppError(ErrorCode.TOKEN_INVALID)

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:  # pragma: no cover - cannot happen for signed data
        raise AppError(ErrorCode.TOKEN_INVALID) from None

    if not isinstance(data, dict) or "tid" not in data or "exp" not in data:
        raise AppError(ErrorCode.TOKEN_INVALID)
    if int(data["exp"]) < int(time.time()):
        raise AppError(ErrorCode.TOKEN_EXPIRED)
    return data
