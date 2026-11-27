"""SSRF layer L1/L2: URL normalisation, IP classification, DNS checks."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import AppConfig
from app.core.errors import AppError, ErrorCode
from app.services import net_policy
from app.services.net_policy import check_target, is_blocked_ip, validate_url

BLOCKED_URLS = [
    # loopback / localhost
    ("http://127.0.0.1/", ErrorCode.SSRF_BLOCKED),
    ("http://127.0.0.1:8080/admin", ErrorCode.SSRF_BLOCKED),
    ("http://localhost/", ErrorCode.SSRF_BLOCKED),
    ("http://LOCALHOST/", ErrorCode.SSRF_BLOCKED),
    ("http://localhost./", ErrorCode.SSRF_BLOCKED),
    ("http://foo.localhost/", ErrorCode.SSRF_BLOCKED),
    ("http://localhost.localdomain/", ErrorCode.SSRF_BLOCKED),
    ("http://127.1/", ErrorCode.SSRF_BLOCKED),
    # alternative IPv4 notations
    ("http://2130706433/", ErrorCode.SSRF_BLOCKED),
    ("http://0x7f000001/", ErrorCode.SSRF_BLOCKED),
    ("http://0177.0.0.1/", ErrorCode.SSRF_BLOCKED),
    ("http://1.2.3/", ErrorCode.SSRF_BLOCKED),
    ("http://127。0。0。1/", ErrorCode.SSRF_BLOCKED),
    # private ranges
    ("http://10.0.0.5/", ErrorCode.SSRF_BLOCKED),
    ("http://172.16.0.1/", ErrorCode.SSRF_BLOCKED),
    ("http://172.31.255.254/", ErrorCode.SSRF_BLOCKED),
    ("http://192.168.1.1/", ErrorCode.SSRF_BLOCKED),
    ("http://100.64.0.1/", ErrorCode.SSRF_BLOCKED),
    ("http://0.0.0.0/", ErrorCode.SSRF_BLOCKED),
    ("http://255.255.255.255/", ErrorCode.SSRF_BLOCKED),
    # metadata endpoints
    ("http://169.254.169.254/latest/meta-data/", ErrorCode.SSRF_BLOCKED),
    ("http://169.254.170.2/v2/credentials", ErrorCode.SSRF_BLOCKED),
    ("http://100.100.100.200/latest/meta-data/", ErrorCode.SSRF_BLOCKED),
    ("http://metadata.google.internal/computeMetadata/v1/", ErrorCode.SSRF_BLOCKED),
    ("http://instance-data/latest/", ErrorCode.SSRF_BLOCKED),
    # IPv6
    ("http://[::1]/", ErrorCode.SSRF_BLOCKED),
    ("http://[::ffff:127.0.0.1]/", ErrorCode.SSRF_BLOCKED),
    ("http://[fd00::1]/", ErrorCode.SSRF_BLOCKED),
    ("http://[fe80::1]/", ErrorCode.SSRF_BLOCKED),
    ("http://[fe80::1%25eth0]/", ErrorCode.SSRF_BLOCKED),
    ("http://[::]/", ErrorCode.SSRF_BLOCKED),
    # reserved suffixes / single-label hosts
    ("http://printer.local/", ErrorCode.SSRF_BLOCKED),
    ("http://db.internal/", ErrorCode.SSRF_BLOCKED),
    ("http://router.lan/", ErrorCode.SSRF_BLOCKED),
    ("http://intranet/", ErrorCode.SSRF_BLOCKED),
    # malformed / unsupported
    ("", ErrorCode.URL_INVALID),
    ("not a url", ErrorCode.URL_SCHEME_NOT_ALLOWED),
    ("http://", ErrorCode.URL_INVALID),
    ("http:///path", ErrorCode.URL_INVALID),
    ("http://user:pass@example.com/file.zip", ErrorCode.URL_INVALID),
    ("http://example.com:99999/", ErrorCode.URL_INVALID),
    ("http://example.com:0/", ErrorCode.URL_INVALID),
    ("http://exa mple.com/", ErrorCode.URL_INVALID),
    ("javascript:alert(1)", ErrorCode.URL_SCHEME_NOT_ALLOWED),
    ("data:text/plain,hello", ErrorCode.URL_SCHEME_NOT_ALLOWED),
    ("file:///etc/passwd", ErrorCode.URL_SCHEME_NOT_ALLOWED),
    ("ftp://example.com/file.zip", ErrorCode.URL_SCHEME_NOT_ALLOWED),
    ("magnet:?xt=urn:btih:abc", ErrorCode.URL_SCHEME_NOT_ALLOWED),
]


@pytest.mark.parametrize(("url", "expected"), BLOCKED_URLS)
def test_blocked_urls(url: str, expected: ErrorCode) -> None:
    with pytest.raises(AppError) as excinfo:
        validate_url(url)
    assert excinfo.value.code is expected


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/file.zip",
        "http://example.com:8080/path/file.bin?token=abc",
        "https://sub.domain.example.co/releases/v1.0/app.tar.gz",
        "https://example.com/",
        "https://[2606:4700:4700::1111]/dns-query",
        "https://1.1.1.1/",
        "https://xn--fsqu00a.example/",
        "https://例子.测试/file.zip",
    ],
)
def test_allowed_urls(url: str) -> None:
    target = validate_url(url)
    assert target.scheme in {"http", "https"}
    assert target.port in {80, 443, 8080}


def test_url_is_normalised_and_query_is_redacted() -> None:
    target = validate_url("HTTPS://Example.COM:443/Path/File.ZIP?token=secret#frag")
    assert target.url == "https://example.com/Path/File.ZIP?token=secret"
    assert target.display == "https://example.com/Path/File.ZIP?***"


def test_unicode_dots_are_normalised() -> None:
    with pytest.raises(AppError) as excinfo:
        validate_url("http://127\u30020\u30020\u30021/")
    assert excinfo.value.code is ErrorCode.SSRF_BLOCKED


def test_allow_private_escape_hatch() -> None:
    target = validate_url("http://127.0.0.1:8080/file", allow_private=True)
    assert target.host == "127.0.0.1"
    assert target.port == 8080


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.1.2.3",
        "172.20.0.1",
        "192.168.0.1",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",
        "::1",
        "::ffff:192.168.0.1",
        "fd00::1",
        "fe80::1",
        "240.0.0.1",
    ],
)
def test_private_addresses_are_blocked(address: str) -> None:
    blocked, _ = is_blocked_ip(address)
    assert blocked is True


@pytest.mark.parametrize("address", ["1.1.1.1", "93.184.216.34", "2606:4700:4700::1111"])
def test_public_addresses_are_allowed(address: str) -> None:
    blocked, reason = is_blocked_ip(address)
    assert blocked is False, reason


async def test_check_target_allows_public_resolution(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(net_policy, "resolve_host", fake_resolve)
    target = await check_target("https://example.com/file.zip")
    assert target.ips == ["93.184.216.34"]


async def test_check_target_blocks_hostname_resolving_to_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["93.184.216.34", "127.0.0.1"]

    monkeypatch.setattr(net_policy, "resolve_host", fake_resolve)
    with pytest.raises(AppError) as excinfo:
        await check_target("https://rebind.example.com/file.zip")
    assert excinfo.value.code is ErrorCode.SSRF_BLOCKED
    assert excinfo.value.details["ip"] == "127.0.0.1"


async def test_check_target_reports_dns_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    import socket

    def fake_getaddrinfo(*args, **kwargs):
        raise socket.gaierror("name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(AppError) as excinfo:
        await check_target("https://does-not-exist.example/")
    assert excinfo.value.code is ErrorCode.DNS_RESOLUTION_FAILED


def test_allow_private_hosts_refused_in_production(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TLS_MODE", "off")
    monkeypatch.setenv("ALLOW_PRIVATE_HOSTS", "true")
    with pytest.raises(ValidationError):
        AppConfig()


def test_tls_verification_cannot_be_disabled_in_production(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("TLS_MODE", "off")
    monkeypatch.setenv("PREFLIGHT_VERIFY_TLS", "false")
    with pytest.raises(ValidationError):
        AppConfig()
