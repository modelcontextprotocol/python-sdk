# pyright: reportMissingImports=false, reportGeneralTypeIssues=false
"""Tests for the build_proxy_server convenience helper."""

from __future__ import annotations

from typing import cast

import httpx  # type: ignore
import pytest  # type: ignore
from pydantic import AnyHttpUrl

from mcp.server.auth.providers.transparent_proxy import _Settings as ProxySettings
from mcp.server.auth.proxy import routes as proxy_routes
from mcp.server.auth.proxy.server import build_proxy_server


@pytest.mark.anyio
async def test_build_proxy_server_metadata(monkeypatch):
    """Ensure the server starts and serves metadata without touching network."""

    # Patch metadata fetcher so no real HTTP traffic occurs
    async def _fake_metadata():  # noqa: D401
        return {
            "issuer": "https://proxy.test",
            "authorization_endpoint": "https://proxy.test/authorize",
            "token_endpoint": "https://proxy.test/token",
            "registration_endpoint": "/register",
        }

    monkeypatch.setattr(proxy_routes, "fetch_upstream_metadata", _fake_metadata, raising=True)

    # Provide required upstream endpoints via settings object
    settings = ProxySettings(  # type: ignore[call-arg]
        UPSTREAM_AUTHORIZATION_ENDPOINT=cast(AnyHttpUrl, "https://upstream.example.com/authorize"),
        UPSTREAM_TOKEN_ENDPOINT=cast(AnyHttpUrl, "https://upstream.example.com/token"),
        UPSTREAM_CLIENT_ID="demo-client-id",
        UPSTREAM_CLIENT_SECRET=None,
        UPSTREAM_JWKS_URI=None,
    )

    mcp = build_proxy_server(port=0, settings=settings)

    app = mcp.streamable_http_app()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as c:
        r = await c.get("/.well-known/oauth-authorization-server")
        assert r.status_code == 200
        data = r.json()
        assert data["authorization_endpoint"].endswith("/authorize")
