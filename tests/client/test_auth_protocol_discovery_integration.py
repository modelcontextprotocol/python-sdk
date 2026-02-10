"""Integration tests: unified auth protocol discovery and 401 WWW-Authenticate extensions.

- Client requests /.well-known/authorization_servers and gets protocol list.
- Server 401 header contains auth_protocols/default_protocol/protocol_preferences and client parses them.
"""

import httpx
import pytest
from starlette.applications import Starlette

from mcp.client.auth.utils import (
    discover_authorization_servers,
    extract_auth_protocols_from_www_auth,
    extract_default_protocol_from_www_auth,
    extract_protocol_preferences_from_www_auth,
)
from mcp.server.auth.routes import create_authorization_servers_discovery_routes
from mcp.shared.auth import AuthProtocolMetadata


@pytest.mark.anyio
async def test_client_discovers_protocols_via_unified_endpoint_integration() -> None:
    """Integration: client discovers protocols via unified endpoint."""
    routes = create_authorization_servers_discovery_routes(
        protocols=[
            AuthProtocolMetadata(protocol_id="oauth2", protocol_version="2.0"),
            AuthProtocolMetadata(protocol_id="api_key", protocol_version="1"),
        ],
        default_protocol="oauth2",
        protocol_preferences={"oauth2": 1, "api_key": 2},
    )
    app = Starlette(routes=routes)
    base_url = "https://example.com"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=base_url,
    ) as client:
        result = await discover_authorization_servers(base_url, client)
    assert len(result) == 2
    assert result[0].protocol_id == "oauth2"
    assert result[1].protocol_id == "api_key"


@pytest.mark.anyio
async def test_client_parses_401_www_authenticate_auth_protocols_extension() -> None:
    """401 header extension fields are parsed correctly."""
    www_auth = (
        'Bearer auth_protocols="oauth2 api_key", default_protocol="oauth2", protocol_preferences="oauth2:1,api_key:2"'
    )
    response = httpx.Response(
        401,
        headers={"WWW-Authenticate": www_auth},
        request=httpx.Request("GET", "https://api.example.com/test"),
    )
    protocols = extract_auth_protocols_from_www_auth(response)
    assert protocols is not None
    assert protocols == ["oauth2", "api_key"]
    default = extract_default_protocol_from_www_auth(response)
    assert default == "oauth2"
    prefs = extract_protocol_preferences_from_www_auth(response)
    assert prefs is not None
    assert prefs == {"oauth2": 1, "api_key": 2}


@pytest.mark.anyio
async def test_client_parses_401_without_auth_protocols_extension_returns_none() -> None:
    """401 WWW-Authenticate without auth_protocols extension; extractors return None."""
    response = httpx.Response(
        401,
        headers={
            "WWW-Authenticate": 'Bearer resource_metadata="https://api.example.com/.well-known/oauth-protected-resource"'
        },
        request=httpx.Request("GET", "https://api.example.com/test"),
    )
    assert extract_auth_protocols_from_www_auth(response) is None
    assert extract_default_protocol_from_www_auth(response) is None
    assert extract_protocol_preferences_from_www_auth(response) is None
