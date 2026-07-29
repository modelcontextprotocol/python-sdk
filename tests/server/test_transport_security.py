"""Tests for the transport-security request validation middleware."""

import pytest
from starlette.requests import Request

from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings


def _request(host: str | None, origin: str | None, content_type: str | None = "application/json") -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if content_type is not None:
        headers.append((b"content-type", content_type.encode()))
    if host is not None:
        headers.append((b"host", host.encode()))
    if origin is not None:
        headers.append((b"origin", origin.encode()))
    return Request({"type": "http", "method": "GET", "headers": headers})


SETTINGS = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=["good.example", "wild.example:*"],
    allowed_origins=["http://good.example", "http://wild.example:*"],
)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("host", "origin", "expected"),
    [
        pytest.param(None, None, 421, id="missing-host"),
        pytest.param("evil.example", None, 421, id="host-no-match"),
        pytest.param("evil.example:9000", None, 421, id="host-wildcard-base-mismatch"),
        pytest.param("good.example", None, None, id="host-exact-no-origin"),
        pytest.param("wild.example:9000", None, None, id="host-wildcard-match"),
        pytest.param("good.example", "http://evil.example", 403, id="origin-no-match"),
        pytest.param("good.example", "http://evil.example:9000", 403, id="origin-wildcard-base-mismatch"),
        pytest.param("good.example", "http://good.example", None, id="origin-exact"),
        pytest.param("good.example", "http://wild.example:9000", None, id="origin-wildcard-match"),
    ],
)
async def test_validate_request_checks_host_then_origin(
    host: str | None, origin: str | None, expected: int | None
) -> None:
    """Host is checked first, then Origin; exact and wildcard-port allowlist entries are honoured."""
    middleware = TransportSecurityMiddleware(SETTINGS)
    response = await middleware.validate_request(_request(host, origin))
    assert (None if response is None else response.status_code) == expected


@pytest.mark.anyio
async def test_validate_request_explains_host_rejection() -> None:
    middleware = TransportSecurityMiddleware(SETTINGS)
    response = await middleware.validate_request(_request("evil.example", None))

    assert response is not None
    assert response.status_code == 421
    assert response.media_type == "application/json"
    assert response.body == (
        b'{"error":"host_not_allowed","received_host":"evil.example",'
        b'"configure":"TransportSecuritySettings.allowed_hosts"}'
    )


@pytest.mark.anyio
async def test_validate_request_skips_host_and_origin_when_protection_is_disabled() -> None:
    """With DNS-rebinding protection off, any Host/Origin is accepted."""
    middleware = TransportSecurityMiddleware(TransportSecuritySettings(enable_dns_rebinding_protection=False))
    assert await middleware.validate_request(_request("evil.example", "http://evil.example")) is None


@pytest.mark.anyio
async def test_validate_request_defaults_to_protection_disabled() -> None:
    """Constructing the middleware without settings leaves DNS-rebinding protection off."""
    middleware = TransportSecurityMiddleware()
    assert await middleware.validate_request(_request("evil.example", "http://evil.example")) is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("content_type", "expected"),
    [
        pytest.param("application/json", None, id="json"),
        pytest.param("application/json; charset=utf-8", None, id="json-with-charset"),
        pytest.param("APPLICATION/JSON", None, id="case-insensitive"),
        pytest.param("text/plain", 400, id="wrong-type"),
        pytest.param(None, 400, id="missing"),
    ],
)
async def test_validate_request_checks_content_type_on_post(content_type: str | None, expected: int | None) -> None:
    """POST requests must carry an application/json Content-Type, regardless of DNS-rebinding settings."""
    middleware = TransportSecurityMiddleware()
    response = await middleware.validate_request(_request("any", None, content_type=content_type), is_post=True)
    assert (None if response is None else response.status_code) == expected


@pytest.mark.anyio
async def test_validate_request_ignores_content_type_on_get() -> None:
    """Content-Type is only enforced for POST requests."""
    middleware = TransportSecurityMiddleware(SETTINGS)
    response = await middleware.validate_request(_request("good.example", None, content_type="text/plain"))
    assert response is None
