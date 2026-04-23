"""Unit tests for TransportSecurityMiddleware."""

import pytest
from starlette.requests import Request

from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings


def make_request(headers: dict[str, str], method: str = "GET") -> Request:
    scope = {
        "type": "http",
        "method": method,
        "path": "/",
        "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    return Request(scope)


def make_middleware(
    *,
    allowed_hosts: list[str] | None = None,
    allowed_origins: list[str] | None = None,
) -> TransportSecurityMiddleware:
    return TransportSecurityMiddleware(
        TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts or [],
            allowed_origins=allowed_origins or [],
        )
    )


# ---------------------------------------------------------------------------
# _validate_host
# ---------------------------------------------------------------------------


def test_validate_host_missing_header():
    mw = make_middleware(allowed_hosts=["example.com"])
    assert mw._validate_host(None) is False


def test_validate_host_exact_match():
    mw = make_middleware(allowed_hosts=["example.com"])
    assert mw._validate_host("example.com") is True


def test_validate_host_no_match():
    mw = make_middleware(allowed_hosts=["example.com"])
    assert mw._validate_host("evil.com") is False


def test_validate_host_port_wildcard_matches():
    mw = make_middleware(allowed_hosts=["example.com:*"])
    assert mw._validate_host("example.com:8080") is True


def test_validate_host_port_wildcard_different_host():
    mw = make_middleware(allowed_hosts=["example.com:*"])
    assert mw._validate_host("evil.com:8080") is False


def test_validate_host_subdomain_wildcard_base_domain():
    # "*.example.com" should match the base domain itself
    mw = make_middleware(allowed_hosts=["*.example.com"])
    assert mw._validate_host("example.com") is True


def test_validate_host_subdomain_wildcard_with_subdomain():
    mw = make_middleware(allowed_hosts=["*.example.com"])
    assert mw._validate_host("app.example.com") is True


def test_validate_host_subdomain_wildcard_with_nested_subdomain():
    mw = make_middleware(allowed_hosts=["*.example.com"])
    assert mw._validate_host("api.staging.example.com") is True


def test_validate_host_subdomain_wildcard_with_port():
    # Port should be stripped before subdomain matching
    mw = make_middleware(allowed_hosts=["*.example.com"])
    assert mw._validate_host("app.example.com:443") is True


def test_validate_host_subdomain_wildcard_no_match():
    mw = make_middleware(allowed_hosts=["*.example.com"])
    assert mw._validate_host("notexample.com") is False


def test_validate_host_subdomain_wildcard_suffix_collision():
    # "fakeexample.com" must not match "*.example.com"
    mw = make_middleware(allowed_hosts=["*.example.com"])
    assert mw._validate_host("fakeexample.com") is False


# ---------------------------------------------------------------------------
# _validate_origin
# ---------------------------------------------------------------------------


def test_validate_origin_absent():
    mw = make_middleware(allowed_origins=["https://example.com"])
    assert mw._validate_origin(None) is True


def test_validate_origin_exact_match():
    mw = make_middleware(allowed_origins=["https://example.com"])
    assert mw._validate_origin("https://example.com") is True


def test_validate_origin_no_match():
    mw = make_middleware(allowed_origins=["https://example.com"])
    assert mw._validate_origin("https://evil.com") is False


def test_validate_origin_port_wildcard_matches():
    mw = make_middleware(allowed_origins=["https://example.com:*"])
    assert mw._validate_origin("https://example.com:8443") is True


def test_validate_origin_port_wildcard_different_host():
    mw = make_middleware(allowed_origins=["https://example.com:*"])
    assert mw._validate_origin("https://evil.com:8443") is False


def test_validate_origin_subdomain_wildcard_base_domain():
    # "https://*.example.com" should match the base domain itself
    mw = make_middleware(allowed_origins=["https://*.example.com"])
    assert mw._validate_origin("https://example.com") is True


def test_validate_origin_subdomain_wildcard_with_subdomain():
    mw = make_middleware(allowed_origins=["https://*.example.com"])
    assert mw._validate_origin("https://app.example.com") is True


def test_validate_origin_subdomain_wildcard_scheme_mismatch():
    mw = make_middleware(allowed_origins=["https://*.example.com"])
    assert mw._validate_origin("http://app.example.com") is False


def test_validate_origin_subdomain_wildcard_no_match():
    mw = make_middleware(allowed_origins=["https://*.example.com"])
    assert mw._validate_origin("https://evil.com") is False


# ---------------------------------------------------------------------------
# validate_request (integration over the public method)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_validate_request_post_invalid_content_type():
    mw = make_middleware(allowed_hosts=["example.com"])
    req = make_request({"host": "example.com", "content-type": "text/plain"}, method="POST")
    resp = await mw.validate_request(req, is_post=True)
    assert resp is not None
    assert resp.status_code == 400


@pytest.mark.anyio
async def test_validate_request_post_valid_content_type_protection_disabled():
    mw = TransportSecurityMiddleware(TransportSecuritySettings(enable_dns_rebinding_protection=False))
    req = make_request({"host": "example.com", "content-type": "application/json"}, method="POST")
    resp = await mw.validate_request(req, is_post=True)
    assert resp is None


@pytest.mark.anyio
async def test_validate_request_get_protection_disabled():
    mw = TransportSecurityMiddleware(TransportSecuritySettings(enable_dns_rebinding_protection=False))
    req = make_request({"host": "evil.com"}, method="GET")
    resp = await mw.validate_request(req, is_post=False)
    assert resp is None


@pytest.mark.anyio
async def test_validate_request_get_invalid_host():
    mw = make_middleware(allowed_hosts=["example.com"])
    req = make_request({"host": "evil.com"}, method="GET")
    resp = await mw.validate_request(req, is_post=False)
    assert resp is not None
    assert resp.status_code == 421


@pytest.mark.anyio
async def test_validate_request_post_invalid_host():
    mw = make_middleware(allowed_hosts=["example.com"])
    req = make_request({"host": "evil.com", "content-type": "application/json"}, method="POST")
    resp = await mw.validate_request(req, is_post=True)
    assert resp is not None
    assert resp.status_code == 421


@pytest.mark.anyio
async def test_validate_request_invalid_origin():
    mw = make_middleware(allowed_hosts=["example.com"], allowed_origins=["https://example.com"])
    req = make_request({"host": "example.com", "origin": "https://evil.com"}, method="GET")
    resp = await mw.validate_request(req, is_post=False)
    assert resp is not None
    assert resp.status_code == 403


@pytest.mark.anyio
async def test_validate_request_all_valid():
    mw = make_middleware(allowed_hosts=["example.com"], allowed_origins=["https://example.com"])
    req = make_request({"host": "example.com", "origin": "https://example.com"}, method="GET")
    resp = await mw.validate_request(req, is_post=False)
    assert resp is None


@pytest.mark.anyio
async def test_validate_request_wildcard_host_end_to_end():
    mw = make_middleware(allowed_hosts=["*.example.com"], allowed_origins=["https://*.example.com"])
    req = make_request({"host": "api.example.com", "origin": "https://app.example.com"}, method="GET")
    resp = await mw.validate_request(req, is_post=False)
    assert resp is None
