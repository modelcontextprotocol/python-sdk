"""`docs/run/authorization.md`: every claim the page makes, proved against the real SDK."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx2
import pytest
from inline_snapshot import snapshot
from mcp_types import TextContent
from starlette.routing import Route

from docs_src.authorization import tutorial001, tutorial002, tutorial003
from mcp import Client, MCPError
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken

# See test_index.py for why this is a per-module mark and not a conftest hook.
pytestmark = [pytest.mark.anyio, pytest.mark.filterwarnings("error::mcp.MCPDeprecationWarning")]


@pytest.fixture
async def notes_app() -> AsyncIterator[tuple[MCPServer, httpx2.ASGITransport]]:
    server = tutorial003.create_server()
    transport = httpx2.ASGITransport(app=server.streamable_http_app())
    async with server.session_manager.run():
        yield server, transport


@asynccontextmanager
async def notes_client(transport: httpx2.ASGITransport, token: str) -> AsyncIterator[Client]:
    async with (
        httpx2.AsyncClient(
            transport=transport, base_url=tutorial003.RESOURCE, headers={"Authorization": f"Bearer {token}"}
        ) as http_client,
        Client(streamable_http_client(tutorial003.RESOURCE, http_client=http_client)) as client,
    ):
        yield client


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


async def test_tool_discovery_reflects_the_current_callers_scopes(
    notes_app: tuple[MCPServer, httpx2.ASGITransport],
) -> None:
    """tutorial003 policy: a shared server filters discovery separately as callers change."""
    _, transport = notes_app
    for token, visible in [
        ("reader-token", ["notes_read"]),
        ("writer-token", ["notes_read", "notes_update"]),
        ("reader-token", ["notes_read"]),
    ]:
        async with notes_client(transport, token) as client:
            tools = await client.list_tools()
            assert [tool.name for tool in tools.tools] == visible
            assert tools.meta is not None
            assert "io.modelcontextprotocol/serverInfo" in tools.meta
            result = await client.call_tool("notes_read", {"note_id": "note-1"})
            assert result.structured_content == {"result": "Ship the release"}


@pytest.mark.parametrize("name", ["notes_update", "unconfigured_tool"])
async def test_a_guessed_or_unconfigured_tool_is_denied_before_its_handler_runs(
    notes_app: tuple[MCPServer, httpx2.ASGITransport], name: str
) -> None:
    """tutorial003 policy: knowing a tool name cannot bypass the scope gate before dispatch."""
    server, transport = notes_app

    def forbidden_handler(note_id: str, text: str) -> str:
        raise NotImplementedError

    if name == "notes_update":
        server.remove_tool(name)
    server.add_tool(forbidden_handler, name=name)
    async with notes_client(transport, "reader-token") as client:
        with pytest.raises(MCPError) as exc:
            await client.call_tool(name, {"note_id": "note-1", "text": "changed"})
        assert exc.value.error.code == tutorial003.PERMISSION_DENIED
        assert exc.value.error.message == snapshot("Operation not permitted.")
        assert exc.value.error.data is None


async def test_a_writer_can_update_and_read_a_note_in_its_own_tenant(
    notes_app: tuple[MCPServer, httpx2.ASGITransport],
) -> None:
    """tutorial003 policy: write scope plus ownership permits the mutation and subsequent read."""
    _, transport = notes_app
    text = "Updated release checklist"
    async with notes_client(transport, "writer-token") as client:
        result = await client.call_tool("notes_update", {"note_id": "note-1", "text": text})
        assert result.structured_content == {"result": text}
        result = await client.call_tool("notes_read", {"note_id": "note-1"})
        assert result.structured_content == {"result": text}


@pytest.mark.parametrize("note_id", ["note-2", "missing-note"])
@pytest.mark.parametrize("name", ["notes_read", "notes_update"])
async def test_foreign_and_missing_notes_return_the_same_safe_denial(
    notes_app: tuple[MCPServer, httpx2.ASGITransport], name: str, note_id: str
) -> None:
    """tutorial003 policy: ownership is required even with scope, and denial hides note existence."""
    _, transport = notes_app
    arguments = {"note_id": note_id}
    if name == "notes_update":
        arguments["text"] = "changed"
    async with notes_client(transport, "writer-token") as client:
        with pytest.raises(MCPError) as exc:
            await client.call_tool(name, arguments)
        assert exc.value.error.code == tutorial003.PERMISSION_DENIED
        assert exc.value.error.message == snapshot("Operation not permitted.")
        assert exc.value.error.data is None
    async with notes_client(transport, "other-tenant-token") as client:
        result = await client.call_tool("notes_read", {"note_id": "note-2"})
        assert result.structured_content == {"result": "Private tenant B note"}


@pytest.mark.parametrize("tenant", [None, "", 42])
async def test_a_valid_token_without_a_valid_tenant_claim_cannot_access_notes(
    notes_app: tuple[MCPServer, httpx2.ASGITransport], monkeypatch: pytest.MonkeyPatch, tenant: str | int | None
) -> None:
    """tutorial003 policy: a verified token alone is insufficient without trusted tenant context."""
    token = AccessToken(
        token="no-tenant",
        client_id="demo",
        scopes=["notes:read", "notes:write"],
        resource=tutorial003.RESOURCE,
        claims={"tenant_id": tenant},
    )
    monkeypatch.setitem(tutorial003.KNOWN_TOKENS, token.token, token)
    _, transport = notes_app
    async with notes_client(transport, token.token) as client:
        with pytest.raises(MCPError) as exc:
            await client.call_tool("notes_read", {"note_id": "note-1"})
        assert exc.value.error.code == tutorial003.PERMISSION_DENIED


@pytest.mark.parametrize("token", [None, "unknown-token", "wrong-audience"])
async def test_untrusted_http_identity_is_rejected_before_mcp_dispatch(
    notes_app: tuple[MCPServer, httpx2.ASGITransport], monkeypatch: pytest.MonkeyPatch, token: str | None
) -> None:
    """tutorial003 uses SDK HTTP authentication; raw HTTP observes the pre-protocol 401."""
    monkeypatch.setitem(
        tutorial003.KNOWN_TOKENS,
        "wrong-audience",
        AccessToken(
            token="wrong-audience", client_id="demo", scopes=["notes:read"], resource="https://other.example/mcp"
        ),
    )
    _, transport = notes_app
    headers = {} if token is None else {"Authorization": f"Bearer {token}"}
    async with httpx2.AsyncClient(transport=transport, base_url=tutorial003.RESOURCE) as http_client:
        response = await http_client.post(tutorial003.RESOURCE, json={}, headers=headers)
    assert response.status_code == 401


async def test_in_memory_calls_fail_closed_without_http_identity() -> None:
    """tutorial003 policy: transport bypass does not create an authenticated principal."""
    async with Client(tutorial003.create_server()) as client:
        with pytest.raises(MCPError) as exc:
            await client.call_tool("notes_read", {"note_id": "note-1"})
        assert exc.value.error.code == tutorial003.PERMISSION_DENIED


async def test_handler_authorization_still_denies_writes_without_the_discovery_middleware(
    notes_app: tuple[MCPServer, httpx2.ASGITransport],
) -> None:
    """tutorial003 policy: handler scope checks remain effective independently of provisional middleware."""
    server, transport = notes_app
    server.middleware.remove(tutorial003.tool_permissions)
    async with notes_client(transport, "reader-token") as client:
        with pytest.raises(MCPError) as exc:
            await client.call_tool("notes_update", {"note_id": "note-1", "text": "changed"})
        assert exc.value.error.code == tutorial003.PERMISSION_DENIED
        result = await client.call_tool("notes_read", {"note_id": "note-1"})
        assert result.structured_content == {"result": "Ship the release"}
