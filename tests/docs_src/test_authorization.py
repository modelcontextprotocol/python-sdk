"""`docs/advanced/authorization.md`: every claim the page makes, proved against the real SDK."""

import httpx
import pytest
from inline_snapshot import snapshot
from mcp_types import TextContent
from starlette.routing import Route

from docs_src.authorization import tutorial001, tutorial002
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_the_in_memory_client_never_authenticates() -> None:
    """tutorial001: `Client(mcp)` connects to the server object directly, so no token is ever checked."""
    async with Client(tutorial001.mcp) as client:
        result = await client.call_tool("list_notes", {})
        assert not result.is_error
        assert result.structured_content == {"result": ["Buy milk", "Ship the release"]}


async def test_token_verifier_and_auth_settings_must_travel_together() -> None:
    """tutorial001: passing `token_verifier=` without `auth=` is refused at construction time."""
    with pytest.raises(ValueError, match="Cannot specify auth_server_provider or token_verifier without auth settings"):
        MCPServer("Notes", token_verifier=tutorial001.StaticTokenVerifier())


async def test_the_app_grows_a_protected_resource_metadata_route() -> None:
    """tutorial001: the HTTP app has the `/mcp` endpoint plus the RFC 9728 well-known route."""
    mcp_route, metadata_route = tutorial001.mcp.streamable_http_app().routes
    assert isinstance(mcp_route, Route)
    assert isinstance(metadata_route, Route)
    assert mcp_route.path == "/mcp"
    assert metadata_route.path == "/.well-known/oauth-protected-resource/mcp"


async def test_the_metadata_document_is_built_from_auth_settings() -> None:
    """tutorial001: `GET` on the well-known route returns the Protected Resource Metadata the page shows."""
    transport = httpx.ASGITransport(app=tutorial001.mcp.streamable_http_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
        response = await http_client.get("/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200
    assert response.json() == snapshot(
        {
            "resource": "http://127.0.0.1:8000/mcp",
            "authorization_servers": ["https://auth.example.com"],
            "scopes_supported": ["notes:read"],
            "bearer_methods_supported": ["header"],
        }
    )


async def test_a_request_without_a_token_never_reaches_the_protocol() -> None:
    """The `!!! check`: no `Authorization` header means a 401 that points at the metadata document."""
    transport = httpx.ASGITransport(app=tutorial001.mcp.streamable_http_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
        response = await http_client.post("/mcp", json={})
    assert response.status_code == 401
    assert response.json() == {"error": "invalid_token", "error_description": "Authentication required"}
    assert response.headers["www-authenticate"] == (
        'Bearer error="invalid_token", error_description="Authentication required", '
        'resource_metadata="http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp"'
    )


async def test_a_token_the_verifier_rejects_gets_the_same_401() -> None:
    """tutorial001: `verify_token` returning `None` and a missing header are indistinguishable to the caller."""
    transport = httpx.ASGITransport(app=tutorial001.mcp.streamable_http_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
        response = await http_client.post("/mcp", json={}, headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401
    assert response.json() == {"error": "invalid_token", "error_description": "Authentication required"}


async def test_get_access_token_is_none_outside_an_authenticated_request() -> None:
    """tutorial002: in-memory there is no HTTP layer, so `get_access_token()` returns `None`."""
    async with Client(tutorial002.mcp) as client:
        result = await client.call_tool("whoami", {})
        assert result.structured_content == {"result": "anonymous"}


async def test_get_access_token_is_the_callers_access_token() -> None:
    """tutorial002: over Streamable HTTP a valid bearer token reaches the tool as an `AccessToken`."""
    url = "http://127.0.0.1:8000/mcp"
    transport = httpx.ASGITransport(app=tutorial002.mcp.streamable_http_app())
    headers = {"Authorization": "Bearer alice-token"}
    async with tutorial002.mcp.session_manager.run():
        async with (
            httpx.AsyncClient(transport=transport, base_url=url, headers=headers) as http_client,
            Client(streamable_http_client(url, http_client=http_client)) as client,
        ):
            result = await client.call_tool("whoami", {})
            assert result.content == [TextContent(type="text", text="alice (scopes: notes:read)")]
            assert result.structured_content == {"result": "alice (scopes: notes:read)"}
