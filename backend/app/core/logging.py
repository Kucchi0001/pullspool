"""Structured logging with request correlation and secret redaction."""

from __future__ import annotations

import json
import logging
import re
import sys
from contextvars import ContextVar
from typing import Any
from urllib.parse import urlparse

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

_URL_RE = re.compile(r"https?://[^\s\"'<>]+")
_KV_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|token|secret|session|authorization|cookie)\b\s*[=:]\s*([^\s,;&\"'}]+)"
)
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+")
_QUERY_SECRET_RE = re.compile(
    r"(?i)([?&](?:token|secret|password|key|signature|sig|code)=)[^&\s\"']+"
)


class QueryRedactor(logging.Filter):
    """Strip secret query-string values from any log message.

    uvicorn's own access logger formats the raw request line and would
    otherwise write download tokens to disk; this filter is attached to it as a
    second line of defence on top of ``--no-access-log``.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        if _QUERY_SECRET_RE.search(message):
            record.msg = _QUERY_SECRET_RE.sub(r"\1***", message)
            record.args = ()
        return True


def redact_url(url: str, max_path: int = 48) -> str:
    """Return ``scheme://host[:port]/path?***`` without credentials or query."""
    try:
        parsed = urlparse(url)
    except ValueError:  # pragma: no cover - defensive
        return "<invalid-url>"
    host = parsed.hostname or ""
    if parsed.port:
        host = f"{host}:{parsed.port}"
    path = parsed.path or ""
    if len(path) > max_path:
        path = path[:max_path] + "…"
    query = "?***" if parsed.query else ""
    return f"{parsed.scheme}://{host}{path}{query}"


def redact(text: str) -> str:
    """Remove secrets from log messages before they reach a handler."""
    text = _URL_RE.sub(lambda m: redact_url(m.group(0)), text)
    text = _BEARER_RE.sub("Bearer ***", text)
    text = _KV_RE.sub(lambda m: f"{m.group(1)}=***", text)
    return text


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.request_id = request_id_var.get()
        try:
            return redact(super().format(record))
        except Exception:  # pragma: no cover - never break logging
            return f"{record.levelname} {record.name} <log formatting failed>"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": request_id_var.get(),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return redact(json.dumps(payload, ensure_ascii=False))


def setup_logging(level: str = "INFO", fmt: str = "text") -> None:
    handler = logging.StreamHandler(stream=sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            RedactingFormatter(
                fmt="%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    handler.addFilter(QueryRedactor())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # We emit our own access log line; uvicorn's is duplicated, noisy and logs
    # the raw query string (download tokens). Disable it and keep a redaction
    # filter attached in case another uvicorn version re-enables it.
    access = logging.getLogger("uvicorn.access")
    access.disabled = True
    access.addFilter(QueryRedactor())
    logging.getLogger("uvicorn.error").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
