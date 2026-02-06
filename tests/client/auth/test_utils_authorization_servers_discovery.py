"""Coverage tests for auth discovery utilities."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from mcp.client.auth.utils import (
    build_authorization_servers_discovery_urls,
    discover_authorization_servers,
    extract_field_from_www_auth,
    extract_protocol_preferences_from_www_auth,
)
from mcp.shared.auth import AuthProtocolMetadata, ProtectedResourceMetadata


def test_extract_field_from_www_auth_with_auth_scheme_filters_match_group() -> None:
    response = httpx.Response(
        401,
        headers={
            "WWW-Authenticate": (
                'Bearer error="invalid_token", scope="a b", resource_metadata="https://rs/.well-known/prm"'
            )
        },
    )
    assert extract_field_from_www_auth(response, "scope", auth_scheme="Bearer") == "a b"
    assert extract_field_from_www_auth(response, "scope", auth_scheme="ApiKey") is None


def test_extract_protocol_preferences_skips_invalid_entries() -> None:
    response = httpx.Response(
        401,
        headers={"WWW-Authenticate": 'Bearer protocol_preferences="oauth2:1,api_key:bad,mutual_tls"'},
    )
    assert extract_protocol_preferences_from_www_auth(response) == {"oauth2": 1}


def test_build_authorization_servers_discovery_urls_deduplicates() -> None:
    # Double slash path normalizes to root, producing a duplicate root URL.
    urls = build_authorization_servers_discovery_urls("https://example.com//")
    assert urls == ["https://example.com/.well-known/authorization_servers"]


@pytest.mark.anyio
async def test_discover_authorization_servers_handles_parse_error_and_recovers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/mcp/.well-known/authorization_servers"):
            return httpx.Response(200, content=b"{not-json", request=request)
        if request.url.path == "/.well-known/authorization_servers":
            return httpx.Response(
                200,
                json={
                    "protocols": [
                        {"protocol_id": "api_key", "protocol_version": "1.0"},
                    ]
                },
                request=request,
            )
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        protocols = await discover_authorization_servers("https://rs.example/mcp", client)

    assert [p.protocol_id for p in protocols] == ["api_key"]
    assert handler(httpx.Request("GET", "https://rs.example/unexpected")).status_code == 404


@pytest.mark.anyio
async def test_discover_authorization_servers_returns_empty_when_no_protocols_and_no_prm() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/mcp/.well-known/authorization_servers"):
            return httpx.Response(200, json={"protocols": []}, request=request)
        if request.url.path == "/.well-known/authorization_servers":
            return httpx.Response(200, json={"protocols": []}, request=request)
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        protocols = await discover_authorization_servers("https://rs.example/mcp", client)

    assert protocols == []
    assert handler(httpx.Request("GET", "https://rs.example/unexpected")).status_code == 404


class _RaisingClient(httpx.AsyncClient):
    def __init__(self) -> None:
        self._calls: int = 0

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, request=request)

        super().__init__(transport=httpx.MockTransport(handler))

    async def get(self, url: httpx.URL | str, **kwargs: Any) -> httpx.Response:
        self._calls += 1
        if self._calls == 1:
            raise RuntimeError("network down")
        return await super().get(url, **kwargs)


@pytest.mark.anyio
async def test_discover_authorization_servers_falls_back_to_prm_after_request_error() -> None:
    prm = ProtectedResourceMetadata.model_validate(
        {
            "resource": "https://rs.example/mcp",
            "authorization_servers": ["https://as.example"],
            "mcp_auth_protocols": [
                AuthProtocolMetadata(protocol_id="oauth2", protocol_version="2.0"),
            ],
        }
    )
    async with _RaisingClient() as client:
        protocols = await discover_authorization_servers(
            "https://rs.example/mcp",
            http_client=client,
            prm=prm,
        )
    assert [p.protocol_id for p in protocols] == ["oauth2"]
