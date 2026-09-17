"""`docs/run/authorization.md`: every claim the page makes, proved against the real SDK."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
import httpx2
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INVALID_PARAMS,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    InputResponses,
    TextContent,
)
from starlette.routing import Route

from docs_src.authorization import tutorial001, tutorial002, tutorial003
from mcp import Client, MCPError
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.transport import MessageMetadata, TransportContext, TransportStreams

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


async def test_verified_transport_identity_binds_the_published_request_state_example() -> None:
    """tutorial003: issued state accepts its verified peer and rejects an anonymous retry through the public runtime."""

    @tutorial003.mcp.tool()
    async def confirm(ctx: Context) -> str | InputRequiredResult:
        if ctx.input_responses is not None:
            assert isinstance(ctx.request_state, str)
            return ctx.request_state
        return InputRequiredResult(
            input_requests={
                "confirm": ElicitRequest(
                    params=ElicitRequestFormParams(
                        message="Confirm?",
                        requested_schema={"type": "object", "properties": {}},
                    )
                )
            },
            request_state="approved",
        )

    with anyio.fail_after(5):
        async with tutorial003.mcp.serve() as runtime:

            @asynccontextmanager
            async def connection(verified: bool) -> AsyncIterator[TransportStreams]:
                async with create_client_server_memory_streams() as (client_streams, server_streams):

                    def builder(metadata: MessageMetadata) -> TransportContext:
                        if verified:
                            return tutorial003.VerifiedPeer(kind="broker", can_send_request=False, principal="alice")
                        return TransportContext(kind="broker", can_send_request=False)

                    @asynccontextmanager
                    async def transport() -> AsyncIterator[TransportStreams]:
                        yield server_streams

                    await runtime.connect(transport(), transport_builder=builder)
                    yield client_streams

            async with Client(connection(True)) as alice, Client(connection(False)) as anonymous:
                pending = await alice.session.call_tool("confirm", allow_input_required=True)
                assert isinstance(pending, InputRequiredResult)
                assert pending.request_state is not None
                responses: InputResponses = {"confirm": ElicitResult(action="accept")}
                with pytest.raises(MCPError) as exc:
                    await anonymous.call_tool("confirm", input_responses=responses, request_state=pending.request_state)
                assert exc.value.code == INVALID_PARAMS
                result = await alice.call_tool(
                    "confirm", input_responses=responses, request_state=pending.request_state
                )
            assert result.structured_content == {"result": "approved"}


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
    transport = httpx2.ASGITransport(app=tutorial001.mcp.streamable_http_app())
    async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
        response = await http_client.get("/.well-known/oauth-protected-resource/mcp")
    assert response.status_code == 200
    assert response.json() == snapshot(
        {
            "resource": "http://127.0.0.1:8000/mcp",
            "authorization_servers": ["https://auth.example.com/"],
            "scopes_supported": ["notes:read"],
            "bearer_methods_supported": ["header"],
        }
    )


async def test_a_request_without_a_token_never_reaches_the_protocol() -> None:
    """The `!!! check`: no `Authorization` header means a 401 that points at the metadata document."""
    transport = httpx2.ASGITransport(app=tutorial001.mcp.streamable_http_app())
    async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
        response = await http_client.post("/mcp", json={})
    assert response.status_code == 401
    assert response.json() == {"error": "invalid_token", "error_description": "Authentication required"}
    assert response.headers["www-authenticate"] == (
        'Bearer error="invalid_token", error_description="Authentication required", '
        'resource_metadata="http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp"'
    )


async def test_a_token_the_verifier_rejects_gets_the_same_401() -> None:
    """tutorial001: `verify_token` returning `None` and a missing header are indistinguishable to the caller."""
    transport = httpx2.ASGITransport(app=tutorial001.mcp.streamable_http_app())
    async with httpx2.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
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
    transport = httpx2.ASGITransport(app=tutorial002.mcp.streamable_http_app())
    headers = {"Authorization": "Bearer alice-token"}
    async with tutorial002.mcp.session_manager.run():
        async with (
            httpx2.AsyncClient(transport=transport, base_url=url, headers=headers) as http_client,
            Client(streamable_http_client(url, http_client=http_client)) as client,
        ):
            result = await client.call_tool("whoami", {})
            assert result.content == [TextContent(type="text", text="alice (scopes: notes:read)")]
            assert result.structured_content == {"result": "alice (scopes: notes:read)"}
