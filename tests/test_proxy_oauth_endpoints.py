# pyright: reportMissingImports=false
# pytest test suite for examples/servers/proxy_oauth/server.py
# These tests spin up the FastMCP Starlette application in-process and
# exercise the custom HTTP routes as well as the `user_info` tool.

from __future__ import annotations

import base64
import json
import urllib.parse
from typing import Any, AsyncGenerator

import httpx  # type: ignore
import pytest  # type: ignore


@pytest.fixture
def proxy_server(monkeypatch):
    """Import the proxy OAuth demo server with safe environment + stubs."""
    import os
    # Avoid real outbound calls by pretending the upstream endpoints were
    # supplied explicitly via env vars – this makes `fetch_upstream_metadata`
    # construct metadata locally instead of performing an HTTP GET.
    os.environ.setdefault("UPSTREAM_AUTHORIZATION_ENDPOINT", "https://upstream.example.com/authorize")
    os.environ.setdefault("UPSTREAM_TOKEN_ENDPOINT", "https://upstream.example.com/token")

    # Deferred import so the env vars above are in effect.
    from examples.servers.proxy_oauth import server as proxy_server_module  # noqa: WPS433 (runtime import for tests)

    # Stub library-level fetch_upstream_metadata to avoid network I/O.
    from mcp.server.auth.proxy import routes as proxy_routes  # noqa: WPS433

    async def _fake_metadata() -> dict[str, Any]:  # noqa: D401
        return {
            "issuer": proxy_server_module.UPSTREAM_BASE,
            "authorization_endpoint": proxy_server_module.UPSTREAM_AUTHORIZE,
            "token_endpoint": proxy_server_module.UPSTREAM_TOKEN,
            "registration_endpoint": "/register",
            "jwks_uri": "",
        }

    monkeypatch.setattr(proxy_routes, "fetch_upstream_metadata", _fake_metadata, raising=True)
    return proxy_server_module


@pytest.fixture
def app(proxy_server):
    """Return the Starlette ASGI app for tests."""
    return proxy_server.mcp.streamable_http_app()


@pytest.fixture
async def client(app) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Async HTTP client bound to the in-memory ASGI application."""
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        yield c


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_metadata_endpoint(client):
    r = await client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    data = r.json()
    assert "issuer" in data
    assert data["authorization_endpoint"].endswith("/authorize")
    assert data["token_endpoint"].endswith("/token")
    assert data["registration_endpoint"].endswith("/register")


@pytest.mark.anyio
async def test_registration_endpoint(client, proxy_server):
    payload = {"redirect_uris": ["https://client.example.com/callback"]}
    r = await client.post("/register", json=payload)
    assert r.status_code == 201
    body = r.json()
    assert body["client_id"] == proxy_server.CLIENT_ID
    assert body["redirect_uris"] == payload["redirect_uris"]
    # client_secret may be None, but the field should exist (masked or real)
    assert "client_secret" in body


@pytest.mark.anyio
async def test_authorize_redirect(client, proxy_server):
    params = {
        "response_type": "code",
        "state": "xyz",
        "redirect_uri": "https://client.example.com/callback",
        "client_id": proxy_server.CLIENT_ID,
        "code_challenge": "testchallenge",
        "code_challenge_method": "S256",
    }
    r = await client.get("/authorize", params=params, follow_redirects=False)
    assert r.status_code in {302, 307}

    location = r.headers["location"]
    parsed = urllib.parse.urlparse(location)
    assert parsed.scheme.startswith("http")
    assert parsed.netloc == urllib.parse.urlparse(proxy_server.UPSTREAM_AUTHORIZE).netloc

    qs = urllib.parse.parse_qs(parsed.query)
    # Proxy should inject client_id & default scope
    assert qs["client_id"][0] == proxy_server.CLIENT_ID
    assert "scope" in qs
    # Original params preserved
    assert qs["state"][0] == "xyz"


@pytest.mark.anyio
async def test_revoke_proxy(client, monkeypatch, proxy_server):
    original_post = httpx.AsyncClient.post

    async def _mock_post(self, url, data=None, timeout=10, **kwargs):  # noqa: D401,WPS110
        if url.endswith("/revoke"):
            return httpx.Response(200, json={"revoked": True})
        # For the test client's own request to /revoke, delegate to original implementation
        return await original_post(self, url, data=data, timeout=timeout, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", _mock_post, raising=True)

    r = await client.post("/revoke", data={"token": "dummy"})
    assert r.status_code == 200
    assert r.json() == {"revoked": True}


@pytest.mark.anyio
async def test_logging_endpoint(client):
    r = await client.get("/test-logging")
    assert r.status_code == 200
    assert r.json()["message"] == "Enhanced logging test successful!"


@pytest.mark.anyio
async def test_token_passthrough(client, monkeypatch, proxy_server):
    """Ensure /token is proxied unchanged and response is returned verbatim."""

    # Capture outgoing POSTs made by ProxyTokenHandler
    captured: dict[str, Any] = {}

    original_post = httpx.AsyncClient.post

    async def _mock_post(self, url, *args, **kwargs):  # noqa: D401,WPS110
        if str(url).startswith(proxy_server.UPSTREAM_TOKEN):
            # Record exactly what was sent upstream
            captured["url"] = str(url)
            captured["data"] = kwargs.get("data")
            # Return a dummy upstream response
            return httpx.Response(
                200,
                json={
                    "access_token": "xyz",
                    "token_type": "bearer",
                    "expires_in": 3600,
                },
            )
        # Delegate any other POSTs to the real implementation
        return await original_post(self, url, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", _mock_post, raising=True)

    # ---------------- Act ----------------
    form = {
        "grant_type": "authorization_code",
        "code": "dummy-code",
        "client_id": proxy_server.CLIENT_ID,
    }
    r = await client.post("/token", data=form)

    # ---------------- Assert -------------
    assert r.status_code == 200
    assert r.json()["access_token"] == "xyz"

    # Verify the request payload was forwarded without modification
    assert captured["data"] == form


# ---------------------------------------------------------------------------
# Tool invocation – user_info
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_user_info_tool(monkeypatch, proxy_server):
    """Call the `user_info` tool directly with a mocked access token."""
    # Craft a dummy JWT with useful claims (header/payload/signature parts)
    payload = base64.urlsafe_b64encode(json.dumps({
        "sub": "test-user",
        "preferred_username": "tester",
    }).encode()).decode().rstrip("=")
    dummy_token = f"header.{payload}.signature"

    from mcp.server.auth.provider import AccessToken  # local import to avoid cycles
    from mcp.server.auth.middleware import auth_context

    def _fake_get_access_token():  # noqa: D401
        return AccessToken(token=dummy_token, client_id="client123", scopes=["openid"], expires_at=None)

    monkeypatch.setattr(auth_context, "get_access_token", _fake_get_access_token, raising=True)

    result = await proxy_server.mcp.call_tool("user_info", {})

    # call_tool returns (content_blocks, raw_result)
    if isinstance(result, tuple):
        _, raw = result
    else:
        raw = result  # fallback

    assert raw["authenticated"] is True
    assert (
        ("userid" in raw and raw["userid"] == "test-user")
        or ("user_id" in raw and raw["user_id"] == "test-user")
    )
    assert raw["username"] == "tester" 