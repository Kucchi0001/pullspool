"""HTTP middleware: request correlation, access log, security headers, CSRF."""

from __future__ import annotations

import time
import uuid
from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.errors import ErrorCode, error_body
from app.core.logging import get_logger, redact_url, request_id_var
from app.core.rate_limit import limiter

logger = get_logger("pullspool.http")

UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if 8 <= len(incoming) <= 64 and incoming.isalnum() else uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        response: Response
        try:
            response = await call_next(request)
        except Exception:
            elapsed = (time.perf_counter() - started) * 1000
            logger.exception(
                "%s %s failed after %.1fms", request.method, redact_url(str(request.url)), elapsed
            )
            raise
        else:
            elapsed = (time.perf_counter() - started) * 1000
            response.headers["X-Request-ID"] = request_id
            for name, value in SECURITY_HEADERS.items():
                response.headers.setdefault(name, value)
            logger.info(
                "%s %s -> %s %.1fms",
                request.method,
                redact_url(str(request.url)),
                response.status_code,
                elapsed,
            )
            return response
        finally:
            request_id_var.reset(token)


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        raw_length = request.headers.get("content-length")
        if raw_length:
            try:
                length = int(raw_length)
            except ValueError:
                return JSONResponse(status_code=400, content=error_body(ErrorCode.VALIDATION_ERROR))
            if length > self.max_bytes:
                return JSONResponse(
                    status_code=413,
                    content=error_body(
                        ErrorCode.VALIDATION_ERROR, "请求体过大", {"max_bytes": self.max_bytes}
                    ),
                )
        return await call_next(request)


class ApiRateLimitMiddleware(BaseHTTPMiddleware):
    """Coarse per-IP limit for all API routes.

    Sensitive endpoints (login, task creation, token issuance) keep their own
    stricter limits; this one only exists so a single client cannot hammer the
    API indefinitely. SSE is excluded because it is one long-lived request.
    """

    def __init__(self, app, limit_per_minute: int, trust_proxy: bool = True) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.limit = limit_per_minute
        self.trust_proxy = trust_proxy

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if not path.startswith("/api/") or path == "/api/events":
            return await call_next(request)

        if self.trust_proxy:
            forwarded = request.headers.get("x-forwarded-for", "")
            client_ip = forwarded.split(",")[0].strip() if forwarded else ""
        else:
            client_ip = ""
        if not client_ip:
            client_ip = request.client.host if request.client else "unknown"

        allowed, retry_after = limiter.hit(f"api:{client_ip}", self.limit, 60)
        if not allowed:
            return JSONResponse(
                status_code=429,
                content=error_body(ErrorCode.RATE_LIMITED),
                headers={"Retry-After": str(retry_after)},
            )
        return await call_next(request)


class OriginCheckMiddleware(BaseHTTPMiddleware):
    """Defence-in-depth CSRF check.

    Browsers always send ``Origin`` on cross-origin unsafe requests, and modern
    browsers send it for same-origin requests too. When both ``Origin`` and
    ``Referer`` are absent we assume a non-browser client (curl, download
    manager) and allow the request; those clients cannot ride a victim's cookie.
    """

    def __init__(self, app, allowed_origins: list[str] | None = None) -> None:  # type: ignore[no-untyped-def]
        super().__init__(app)
        self.allowed_hosts = {
            urlparse(origin).netloc.lower() for origin in (allowed_origins or []) if origin
        }

    def _reject(self) -> JSONResponse:
        return JSONResponse(status_code=403, content=error_body(ErrorCode.ORIGIN_MISMATCH))

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.method not in UNSAFE_METHODS:
            return await call_next(request)

        fetch_site = request.headers.get("sec-fetch-site", "").lower()
        if fetch_site == "cross-site":
            return self._reject()

        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        source = origin or referer
        if not source:
            return await call_next(request)

        source_host = urlparse(source).netloc.lower()
        request_host = request.headers.get("host", "").lower()
        forwarded_host = request.headers.get("x-forwarded-host", "").split(",", 1)[0].strip().lower()
        if source_host and (
            source_host == request_host
            or (forwarded_host and source_host == forwarded_host)
            or source_host in self.allowed_hosts
        ):
            return await call_next(request)
        return self._reject()
