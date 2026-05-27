"""Unit tests for TransportSecuritySettings and TransportSecurityMiddleware."""

import logging

import pytest
from starlette.requests import Request

from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings


def make_request(headers: dict[str, str], method: str = "GET") -> Request:
    scope = {
        "type": "http",
        "method": method,
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "path": "/",
        "query_string": b"",
    }
    return Request(scope)


# ---------------------------------------------------------------------------
# TransportSecuritySettings — construction-time warning
# ---------------------------------------------------------------------------


def test_no_warning_when_protection_disabled(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="mcp.server.transport_security"):
        TransportSecuritySettings(enable_dns_rebinding_protection=False)
    assert not caplog.records


def test_no_warning_when_allowed_hosts_populated(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="mcp.server.transport_security"):
        TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["example.com"],
        )
    assert not caplog.records


def test_warning_when_protection_enabled_with_empty_allowed_hosts(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="mcp.server.transport_security"):
        TransportSecuritySettings(enable_dns_rebinding_protection=True)
    assert len(caplog.records) == 1
    assert "allowed_hosts is empty" in caplog.records[0].message
    assert "HTTP 421" in caplog.records[0].message
    assert "allowed_hosts=" in caplog.records[0].message


# ---------------------------------------------------------------------------
# TransportSecurityMiddleware._validate_host
# ---------------------------------------------------------------------------


def test_validate_host_missing_host() -> None:
    m = TransportSecurityMiddleware(TransportSecuritySettings(allowed_hosts=["example.com"]))
    assert m._validate_host(None) is False


def test_validate_host_exact_match() -> None:
    m = TransportSecurityMiddleware(TransportSecuritySettings(allowed_hosts=["example.com"]))
    assert m._validate_host("example.com") is True


def test_validate_host_exact_no_match() -> None:
    m = TransportSecurityMiddleware(TransportSecuritySettings(allowed_hosts=["example.com"]))
    assert m._validate_host("other.com") is False


def test_validate_host_port_wildcard_match() -> None:
    m = TransportSecurityMiddleware(TransportSecuritySettings(allowed_hosts=["localhost:*"]))
    assert m._validate_host("localhost:8080") is True


def test_validate_host_port_wildcard_different_base() -> None:
    m = TransportSecurityMiddleware(TransportSecuritySettings(allowed_hosts=["localhost:*"]))
    assert m._validate_host("other:8080") is False


def test_validate_host_port_wildcard_no_port() -> None:
    m = TransportSecurityMiddleware(TransportSecuritySettings(allowed_hosts=["localhost:*"]))
    assert m._validate_host("localhost") is False


def test_validate_host_logs_once_per_unique_host(caplog: pytest.LogCaptureFixture) -> None:
    m = TransportSecurityMiddleware(TransportSecuritySettings(allowed_hosts=["example.com"]))
    with caplog.at_level(logging.WARNING, logger="mcp.server.transport_security"):
        m._validate_host("evil.com")
        m._validate_host("evil.com")
        m._validate_host("evil.com")
        m._validate_host("other.com")
    host_records = [r for r in caplog.records if "Invalid Host header" in r.message]
    assert len(host_records) == 2  # one for evil.com, one for other.com


# ---------------------------------------------------------------------------
# TransportSecurityMiddleware._validate_origin
# ---------------------------------------------------------------------------


def test_validate_origin_absent_is_allowed() -> None:
    m = TransportSecurityMiddleware(TransportSecuritySettings(allowed_origins=["http://example.com"]))
    assert m._validate_origin(None) is True


def test_validate_origin_exact_match() -> None:
    m = TransportSecurityMiddleware(TransportSecuritySettings(allowed_origins=["http://example.com"]))
    assert m._validate_origin("http://example.com") is True


def test_validate_origin_exact_no_match() -> None:
    m = TransportSecurityMiddleware(TransportSecuritySettings(allowed_origins=["http://example.com"]))
    assert m._validate_origin("http://other.com") is False


def test_validate_origin_port_wildcard_match() -> None:
    m = TransportSecurityMiddleware(TransportSecuritySettings(allowed_origins=["http://localhost:*"]))
    assert m._validate_origin("http://localhost:3000") is True


def test_validate_origin_port_wildcard_different_base() -> None:
    m = TransportSecurityMiddleware(TransportSecuritySettings(allowed_origins=["http://localhost:*"]))
    assert m._validate_origin("http://other:3000") is False


def test_validate_origin_logs_once_per_unique_origin(caplog: pytest.LogCaptureFixture) -> None:
    m = TransportSecurityMiddleware(TransportSecuritySettings(allowed_origins=["http://example.com"]))
    with caplog.at_level(logging.WARNING, logger="mcp.server.transport_security"):
        m._validate_origin("http://evil.com")
        m._validate_origin("http://evil.com")
        m._validate_origin("http://other.com")
    origin_records = [r for r in caplog.records if "Invalid Origin header" in r.message]
    assert len(origin_records) == 2  # one for evil.com, one for other.com


# ---------------------------------------------------------------------------
# TransportSecurityMiddleware.validate_request
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_validate_request_post_valid_content_type() -> None:
    m = TransportSecurityMiddleware(TransportSecuritySettings(enable_dns_rebinding_protection=False))
    request = make_request({"content-type": "application/json"}, method="POST")
    assert await m.validate_request(request, is_post=True) is None


@pytest.mark.anyio
async def test_validate_request_post_invalid_content_type() -> None:
    m = TransportSecurityMiddleware(TransportSecuritySettings(enable_dns_rebinding_protection=False))
    request = make_request({"content-type": "text/plain"}, method="POST")
    response = await m.validate_request(request, is_post=True)
    assert response is not None
    assert response.status_code == 400


@pytest.mark.anyio
async def test_validate_request_get_skips_content_type() -> None:
    m = TransportSecurityMiddleware(TransportSecuritySettings(enable_dns_rebinding_protection=False))
    request = make_request({})
    assert await m.validate_request(request, is_post=False) is None


@pytest.mark.anyio
async def test_validate_request_protection_disabled_allows_any_host() -> None:
    m = TransportSecurityMiddleware(TransportSecuritySettings(enable_dns_rebinding_protection=False))
    request = make_request({"host": "attacker.example.com"})
    assert await m.validate_request(request) is None


@pytest.mark.anyio
async def test_validate_request_valid_host_and_no_origin() -> None:
    m = TransportSecurityMiddleware(TransportSecuritySettings(allowed_hosts=["example.com"]))
    request = make_request({"host": "example.com"})
    assert await m.validate_request(request) is None


@pytest.mark.anyio
async def test_validate_request_invalid_host_returns_421_with_detail() -> None:
    m = TransportSecurityMiddleware(TransportSecuritySettings(allowed_hosts=["example.com"]))
    request = make_request({"host": "attacker.com"})
    response = await m.validate_request(request)
    assert response is not None
    assert response.status_code == 421
    assert b"attacker.com" in response.body
    assert b"allowed_hosts" in response.body


@pytest.mark.anyio
async def test_validate_request_invalid_origin_returns_403_with_detail() -> None:
    m = TransportSecurityMiddleware(
        TransportSecuritySettings(
            allowed_hosts=["example.com"],
            allowed_origins=["http://example.com"],
        )
    )
    request = make_request({"host": "example.com", "origin": "http://attacker.com"})
    response = await m.validate_request(request)
    assert response is not None
    assert response.status_code == 403
    assert b"attacker.com" in response.body
    assert b"allowed_origins" in response.body
