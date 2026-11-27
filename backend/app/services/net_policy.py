"""URL normalisation, IP classification and DNS policy (SSRF layers L1 + L2).

Everything here is pure and synchronous except :func:`check_target`, which
performs DNS resolution. The preflight transport lives in ``preflight.py``.
"""

from __future__ import annotations

import asyncio
import ipaddress
import re
import socket
import unicodedata
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit

from app.core.errors import AppError, ErrorCode
from app.core.logging import redact_url

MAX_URL_LENGTH = 4096
MAX_HOST_LENGTH = 253

ALLOWED_SCHEMES = {"http", "https"}

# Hostnames / suffixes that must never be fetched, independent of DNS.
BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
    "metadata",
    "metadata.google.internal",
    "instance-data",
    "kubernetes.default.svc",
}

BLOCKED_HOST_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".lan",
    ".home.arpa",
    ".localdomain",
    ".intranet",
    ".corp",
)

# Address ranges that must be rejected even if ``ipaddress`` considers them global.
EXTRA_BLOCKED_NETWORKS = (
    ipaddress.ip_network("100.64.0.0/10"),  # carrier-grade NAT
    ipaddress.ip_network("169.254.169.254/32"),  # AWS/GCP/Azure metadata
    ipaddress.ip_network("169.254.170.2/32"),  # ECS task metadata
    ipaddress.ip_network("100.100.100.200/32"),  # Alibaba Cloud metadata
    ipaddress.ip_network("192.0.0.0/24"),  # IETF protocol assignments
    ipaddress.ip_network("198.18.0.0/15"),  # benchmarking
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("240.0.0.0/4"),  # reserved (incl. 255.255.255.255)
    ipaddress.ip_network("fd00:ec2::254/128"),  # AWS IPv6 metadata
)

_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
_NUMERIC_HOST_RE = re.compile(r"^[0-9]+$")
_HEX_HOST_RE = re.compile(r"^0x[0-9a-f]+$", re.IGNORECASE)
_DOTTED_NUMERIC_RE = re.compile(r"^[0-9.]+$")
_UNICODE_DOTS = str.maketrans({"\u3002": ".", "\uff0e": ".", "\uff61": "."})


@dataclass(slots=True)
class TargetURL:
    """A syntactically valid, policy-checked URL (no DNS yet)."""

    url: str
    display: str
    scheme: str
    host: str
    port: int
    is_ip_literal: bool
    ip: str | None = None


@dataclass(slots=True)
class ResolvedTarget:
    """A URL whose literal IP (or every resolved address) passed the policy."""

    url: str
    display: str
    scheme: str
    host: str
    port: int
    ips: list[str]
    is_ip_literal: bool


def _invalid(message: str, detail: str | None = None) -> AppError:
    return AppError(ErrorCode.URL_INVALID, message, details={"reason": detail} if detail else {})


def _blocked(reason: str, **details: object) -> AppError:
    return AppError(ErrorCode.SSRF_BLOCKED, details={"reason": reason, **details})


def is_blocked_ip(raw: str, *, allow_private: bool = False) -> tuple[bool, str]:
    """Return ``(blocked, reason)`` for an IP literal."""
    if allow_private:
        return False, "allowed_by_config"

    candidate = raw.split("%", 1)[0].strip()
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return True, "unparsable_ip"

    if address.version == 6:
        mapped = address.ipv4_mapped
        if mapped is not None:
            address = mapped

    if address.is_loopback:
        return True, "loopback"
    if address.is_private:
        return True, "private"
    if address.is_link_local:
        return True, "link_local"
    if address.is_multicast:
        return True, "multicast"
    if address.is_reserved:
        return True, "reserved"
    if address.is_unspecified:
        return True, "unspecified"
    if not address.is_global:
        return True, "not_global"
    for network in EXTRA_BLOCKED_NETWORKS:
        if address.version == network.version and address in network:
            return True, "blocked_network"
    return False, "ok"


def _normalise_host(raw_host: str) -> str:
    host = unicodedata.normalize("NFKC", raw_host).translate(_UNICODE_DOTS).strip()
    host = host.lower()
    while host.endswith("."):
        host = host[:-1]
    return host


def _validate_hostname(host: str, *, allow_private: bool) -> None:
    if not host:
        raise _invalid("下载链接缺少主机名", "empty_host")
    if len(host) > MAX_HOST_LENGTH:
        raise _invalid("主机名过长", "host_too_long")
    if "%" in host:
        raise _blocked("ipv6_zone_id", host=host)
    if host in BLOCKED_HOSTNAMES:
        raise _blocked("blocked_hostname", host=host)
    if host.endswith(BLOCKED_HOST_SUFFIXES):
        raise _blocked("blocked_host_suffix", host=host)
    if _HEX_HOST_RE.match(host) or _NUMERIC_HOST_RE.match(host):
        raise _blocked("numeric_host", host=host)
    if _DOTTED_NUMERIC_RE.match(host):
        # Looks like an IPv4 address but failed ``ipaddress`` parsing
        # (e.g. "127.1", "1.2.3", "999.1.1.1").
        raise _blocked("non_canonical_ip", host=host)

    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise _invalid("主机名包含非法字符", "idn_invalid") from exc

    labels = ascii_host.split(".")
    if len(labels) < 2:
        raise _blocked("single_label_host", host=host)
    for label in labels:
        if not _LABEL_RE.match(label):
            raise _invalid("主机名包含非法字符", "invalid_label")

    if not allow_private and labels[-1].isdigit():
        raise _blocked("numeric_tld", host=host)


def validate_url(raw_url: str, *, allow_private: bool = False) -> TargetURL:
    """L1: scheme, host shape and literal-IP checks. Performs no network I/O."""
    if not isinstance(raw_url, str):
        raise _invalid("下载链接必须是字符串")
    url = raw_url.strip()
    if not url:
        raise _invalid("下载链接不能为空", "empty")
    if len(url) > MAX_URL_LENGTH:
        raise _invalid(f"下载链接过长（上限 {MAX_URL_LENGTH} 字符）", "too_long")
    if any(ord(char) < 0x20 or ord(char) == 0x7F for char in url):
        raise _invalid("下载链接包含控制字符", "control_char")

    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise _invalid("下载链接格式不正确", "parse_error") from exc

    scheme = parsed.scheme.lower()
    if scheme not in ALLOWED_SCHEMES:
        raise AppError(
            ErrorCode.URL_SCHEME_NOT_ALLOWED,
            f"只支持 http 与 https 链接（收到 {scheme or '空'}）",
            details={"scheme": scheme},
        )
    if not parsed.netloc:
        raise _invalid("下载链接缺少主机名", "missing_netloc")
    if parsed.username is not None or parsed.password is not None:
        raise _invalid("下载链接不允许包含用户名或密码", "userinfo")
    if "@" in parsed.netloc:
        raise _invalid("下载链接不允许包含用户名或密码", "userinfo")

    raw_host = parsed.hostname
    if not raw_host:
        raise _invalid("下载链接缺少主机名", "no_host")
    host = _normalise_host(raw_host)

    try:
        explicit_port = parsed.port
    except ValueError as exc:
        raise _invalid("端口号不合法", "invalid_port") from exc
    port = explicit_port if explicit_port is not None else (443 if scheme == "https" else 80)
    if not 1 <= port <= 65535:
        raise _invalid("端口号不合法", "port_out_of_range")

    is_ip_literal = False
    literal_ip: str | None = None
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None

    if address is not None:
        is_ip_literal = True
        literal_ip = str(address)
        blocked, reason = is_blocked_ip(literal_ip, allow_private=allow_private)
        if blocked:
            raise _blocked(reason, host=host, ip=literal_ip)
    else:
        _validate_hostname(host, allow_private=allow_private)
        host = host.encode("idna").decode("ascii")

    path = parsed.path or "/"
    query = f"?{parsed.query}" if parsed.query else ""
    host_for_url = f"[{host}]" if ":" in host else host
    default_port = 443 if scheme == "https" else 80
    port_part = "" if port == default_port else f":{port}"
    normalised = f"{scheme}://{host_for_url}{port_part}{path}{query}"

    return TargetURL(
        url=normalised,
        display=redact_url(normalised),
        scheme=scheme,
        host=host,
        port=port,
        is_ip_literal=is_ip_literal,
        ip=literal_ip,
    )


async def resolve_host(host: str, port: int) -> list[str]:
    """Resolve every A/AAAA record, de-duplicated and order-preserving."""

    def _resolve() -> list[str]:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        return [info[4][0] for info in infos]

    try:
        addresses = await asyncio.to_thread(_resolve)
    except socket.gaierror as exc:
        raise AppError(
            ErrorCode.DNS_RESOLUTION_FAILED,
            f"无法解析域名 {host}",
            details={"host": host},
        ) from exc

    seen: set[str] = set()
    unique: list[str] = []
    for address in addresses:
        if address in seen:
            continue
        seen.add(address)
        unique.append(address)
    if not unique:
        raise AppError(
            ErrorCode.DNS_RESOLUTION_FAILED,
            f"域名 {host} 没有可用地址",
            details={"host": host},
        )
    return unique


async def check_target(raw_url: str, *, allow_private: bool = False) -> ResolvedTarget:
    """L1 + L2: validate the URL and every address it resolves to."""
    target = validate_url(raw_url, allow_private=allow_private)

    if target.is_ip_literal:
        assert target.ip is not None
        return ResolvedTarget(
            url=target.url,
            display=target.display,
            scheme=target.scheme,
            host=target.host,
            port=target.port,
            ips=[target.ip],
            is_ip_literal=True,
        )

    addresses = await resolve_host(target.host, target.port)
    for address in addresses:
        blocked, reason = is_blocked_ip(address, allow_private=allow_private)
        if blocked:
            raise _blocked(reason, host=target.host, ip=address)
        if address.split("%", 1)[0] != address:
            raise _blocked("ipv6_zone_id", host=target.host, ip=address)

    return ResolvedTarget(
        url=target.url,
        display=target.display,
        scheme=target.scheme,
        host=target.host,
        port=target.port,
        ips=addresses,
        is_ip_literal=False,
    )


def url_for_display(url: str) -> str:
    """Redacted, percent-safe display form used in API responses and logs."""
    return redact_url(url)


def encoded_path_segment(segment: str) -> str:
    return quote(unquote(segment), safe="")
