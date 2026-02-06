"""Regression tests for AuthorizationServersDiscoveryHandler and create_authorization_servers_discovery_routes."""

from typing import cast

import httpx
import pytest
from starlette.applications import Starlette

from mcp.server.auth.routes import create_authorization_servers_discovery_routes
from mcp.shared.auth import AuthProtocolMetadata


@pytest.fixture
def discovery_app() -> Starlette:
    """App with /.well-known/authorization_servers returning protocols, default_protocol, protocol_preferences."""
    routes = create_authorization_servers_discovery_routes(
        protocols=[
            AuthProtocolMetadata(protocol_id="oauth2", protocol_version="2.0"),
            AuthProtocolMetadata(protocol_id="api_key", protocol_version="1"),
        ],
        default_protocol="oauth2",
        protocol_preferences={"oauth2": 1, "api_key": 2},
    )
    return Starlette(routes=routes)


@pytest.fixture
async def discovery_client(discovery_app: Starlette):
    """HTTP client for discovery app."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=discovery_app), base_url="https://mcptest.com"
    ) as client:
        yield client


@pytest.mark.anyio
async def test_discovery_endpoint_returns_protocols(discovery_client: httpx.AsyncClient) -> None:
    """GET /.well-known/authorization_servers returns 200 with protocols list."""
    response = await discovery_client.get("/.well-known/authorization_servers")
    assert response.status_code == 200
    data = response.json()
    assert "protocols" in data
    assert len(data["protocols"]) == 2
    assert data["protocols"][0]["protocol_id"] == "oauth2"
    assert data["protocols"][1]["protocol_id"] == "api_key"


@pytest.mark.anyio
async def test_discovery_endpoint_includes_default_and_preferences(discovery_client: httpx.AsyncClient) -> None:
    """Response includes default_protocol and protocol_preferences when provided."""
    response = await discovery_client.get("/.well-known/authorization_servers")
    assert response.status_code == 200
    data = response.json()
    assert data.get("default_protocol") == "oauth2"
    assert data.get("protocol_preferences") == {"oauth2": 1, "api_key": 2}


@pytest.mark.anyio
async def test_discovery_response_parseable_by_client() -> None:
    """Response format is parseable by discover_authorization_servers (AuthProtocolMetadata.model_validate)."""
    routes = create_authorization_servers_discovery_routes(
        protocols=[AuthProtocolMetadata(protocol_id="oauth2", protocol_version="2.0")],
    )
    app = Starlette(routes=routes)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://mcptest.com") as client:
        response = await client.get("/.well-known/authorization_servers")
    assert response.status_code == 200
    data = response.json()
    raw = cast(list[dict[str, object]] | None, data.get("protocols"))
    assert raw is not None and len(raw) == 1
    parsed = AuthProtocolMetadata.model_validate(raw[0])
    assert parsed.protocol_id == "oauth2"
    assert parsed.protocol_version == "2.0"


@pytest.mark.anyio
async def test_discovery_routes_minimal_protocols_only() -> None:
    """create_authorization_servers_discovery_routes with only protocols (no default/preferences)."""
    routes = create_authorization_servers_discovery_routes(
        protocols=[AuthProtocolMetadata(protocol_id="api_key", protocol_version="1")],
    )
    app = Starlette(routes=routes)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://mcptest.com") as client:
        response = await client.get("/.well-known/authorization_servers")
    assert response.status_code == 200
    data = response.json()
    assert data["protocols"][0]["protocol_id"] == "api_key"
    assert "default_protocol" not in data or data.get("default_protocol") is None
    assert "protocol_preferences" not in data or data.get("protocol_preferences") is None
