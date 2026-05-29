"""Streamable HTTP session lifecycle: creation, routing, termination, and stateless mode.

A test here speaks raw HTTP only when its assertion is the wire contract -- which header is
issued, which status code answers which condition -- that the SDK `Client` cannot observe.
Everything else is `Client`-driven against the same mounted session manager. Transport-agnostic
behaviour is covered by the `connect`-fixture matrix.
"""

import re

import anyio
import httpx
import pytest
from inline_snapshot import snapshot

from mcp.server import Server
from mcp.types import JSONRPCResponse, ListToolsResult, Tool
from tests.interaction._connect import (
    base_headers,
    client_via_http,
    initialize_body,
    initialize_via_http,
    mounted_app,
    post_jsonrpc,
)
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


def _server() -> Server:
    """A minimal low-level server with one tool, so subsequent-request routing can be observed."""
    server = Server("hosted")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [Tool(name="noop", description="Does nothing.", inputSchema={"type": "object"})]

    return server


@requirement("hosting:session:create")
@requirement("hosting:session:id-charset")
async def test_initialize_issues_a_visible_ascii_session_id() -> None:
    """An initialize POST without a session ID creates a session and returns a visible-ASCII Mcp-Session-Id."""
    async with mounted_app(_server()) as (http, _):
        response, messages = await post_jsonrpc(http, initialize_body())

    assert response.status_code == 200
    session_id = response.headers.get("mcp-session-id")
    assert session_id is not None
    # The spec requires the session ID to consist only of visible ASCII (0x21-0x7E).
    assert re.fullmatch(r"[\x21-\x7E]+", session_id)
    assert isinstance(messages[0].root, JSONRPCResponse)
    assert messages[0].root.id == 1


@requirement("hosting:session:reuse")
async def test_subsequent_requests_with_the_session_id_route_to_the_same_session() -> None:
    """Requests carrying the issued Mcp-Session-Id reuse that session's transport rather than creating another."""
    async with mounted_app(_server()) as (http, manager):
        async with client_via_http(http) as client:
            await client.list_tools()
            await client.list_tools()
            # The session count is the only signal that distinguishes routing-to-existing from
            # silently creating a second session: both produce a successful result.
            assert len(manager._server_instances) == 1


@requirement("hosting:session:unknown-id")
async def test_requests_with_an_unknown_session_id_return_404() -> None:
    """POST, GET, and DELETE each carrying an unknown Mcp-Session-Id are answered 404 by the manager."""
    async with mounted_app(_server()) as (http, _):
        post = await http.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
            headers=base_headers(session_id="not-a-session"),
        )
        get = await http.get("/mcp", headers=base_headers(session_id="not-a-session"))
        delete = await http.delete("/mcp", headers=base_headers(session_id="not-a-session"))

    assert (post.status_code, post.json()) == snapshot(
        (404, {"jsonrpc": "2.0", "id": "server-error", "error": {"code": -32600, "message": "Session not found"}})
    )
    assert (get.status_code, delete.status_code) == (404, 404)


@requirement("hosting:session:missing-id")
async def test_non_initialize_post_without_a_session_id_returns_400() -> None:
    """A non-initialize POST that omits Mcp-Session-Id in stateful mode is rejected with 400."""
    async with mounted_app(_server()) as (http, _):
        await initialize_via_http(http)
        response = await http.post(
            "/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=base_headers()
        )

    assert (response.status_code, response.json()) == snapshot(
        (
            400,
            {
                "jsonrpc": "2.0",
                "id": "server-error",
                "error": {"code": -32600, "message": "Bad Request: Missing session ID"},
            },
        )
    )


@requirement("hosting:session:delete")
@requirement("hosting:session:post-termination-404")
async def test_delete_terminates_the_session_and_subsequent_requests_return_404() -> None:
    """DELETE with a valid Mcp-Session-Id terminates the session; further requests on that ID return 404."""
    async with mounted_app(_server()) as (http, manager):
        session_id = await initialize_via_http(http)

        delete = await http.delete("/mcp", headers=base_headers(session_id=session_id))
        assert delete.status_code == 200

        # The manager keeps the terminated transport registered, so the next request reaches the
        # transport's own _terminated check rather than the manager's unknown-session path.
        assert session_id in manager._server_instances
        post = await http.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers=base_headers(session_id=session_id),
        )
        assert (post.status_code, post.json()) == snapshot(
            (
                404,
                {
                    "jsonrpc": "2.0",
                    "id": "server-error",
                    "error": {"code": -32600, "message": "Not Found: Session has been terminated"},
                },
            )
        )


@requirement("hosting:session:isolation")
async def test_terminating_one_session_leaves_others_working() -> None:
    """Terminating one session on a manager does not disturb a concurrent session on the same manager."""
    async with mounted_app(_server()) as (http, manager):
        async with client_via_http(http) as survivor:
            async with client_via_http(http) as terminated:
                await terminated.list_tools()
                assert len(manager._server_instances) == 2
            # `terminated` has exited (its DELETE has been sent); `survivor` still answers.
            result = await survivor.list_tools()

    assert result.tools[0].name == "noop"


@requirement("hosting:session:reinitialize")
async def test_second_initialize_on_an_existing_session_is_accepted() -> None:
    """A second initialize POST carrying an existing session ID is processed rather than rejected.

    See the divergence on the requirement: the entry expects a rejection, but the SDK forwards the
    second initialize to the running server, which answers it as a fresh handshake.
    """
    async with mounted_app(_server()) as (http, manager):
        session_id = await initialize_via_http(http)
        response, messages = await post_jsonrpc(http, initialize_body(request_id=2), session_id=session_id)
        assert len(manager._server_instances) == 1

    assert response.status_code == snapshot(200)
    assert isinstance(messages[0].root, JSONRPCResponse)
    assert messages[0].root.id == 2


@requirement("hosting:stateless:no-session-id")
@requirement("hosting:stateless:no-reuse")
async def test_stateless_mode_never_issues_a_session_id() -> None:
    """A stateless server issues no Mcp-Session-Id and creates no persistent transport.

    The recording proves no request the SDK client sent carried an Mcp-Session-Id (the server
    cannot have issued one, or the client would echo it); the empty instance map proves the
    manager kept no transport between requests.
    """
    requests: list[httpx.Request] = []

    async def record(request: httpx.Request) -> None:
        requests.append(request)

    async with mounted_app(_server(), stateless_http=True, on_request=record) as (http, manager):
        async with client_via_http(http) as client:
            result = await client.list_tools()
            assert manager._server_instances == {}

    assert result.tools[0].name == "noop"
    assert all("mcp-session-id" not in request.headers for request in requests)
    assert "DELETE" not in {request.method for request in requests}


@requirement("hosting:stateless:concurrent-clients")
async def test_stateless_mode_serves_concurrent_clients_independently() -> None:
    """Two clients connected concurrently to the same stateless app each complete a round trip."""
    results: dict[str, ListToolsResult] = {}

    async with mounted_app(_server(), stateless_http=True) as (http, _):

        async def list_via(label: str) -> None:
            async with client_via_http(http) as client:
                results[label] = await client.list_tools()

        with anyio.fail_after(5):
            async with anyio.create_task_group() as tg:  # pragma: no branch
                tg.start_soon(list_via, "a")
                tg.start_soon(list_via, "b")

    assert results["a"].tools[0].name == "noop"
    assert results["b"].tools[0].name == "noop"
