"""Behaviour of the streamable-HTTP client transport itself, observed at the wire.

These tests connect a real `Client` to a real server over the in-process bridge, recording every
HTTP request the SDK client issues, so the assertions are about what the transport sends (headers,
methods, ordering) rather than what the protocol layer on top of it returns. The recording is the
wire-level instrument; the SDK client never exposes these details.
"""

import json
from collections.abc import AsyncIterator

import anyio
import httpx
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import INVALID_REQUEST, CallToolResult, ErrorData, ListToolsResult, TextContent, Tool
from starlette.types import Receive, Scope, Send

from mcp import MCPError
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext
from tests.interaction._connect import BASE_URL, NO_DNS_REBINDING_PROTECTION, client_via_http, mounted_app
from tests.interaction._requirements import requirement
from tests.interaction.transports._bridge import StreamingASGITransport
from tests.interaction.transports._event_store import SequencedEventStore

pytestmark = pytest.mark.anyio


def _tooled_server() -> Server:
    """A low-level server with one echo tool, used by every test in this file."""

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name="echo", description="Echo text.", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "echo"
        assert params.arguments is not None
        return CallToolResult(content=[TextContent(text=str(params.arguments["text"]))])

    return Server("echoer", on_list_tools=list_tools, on_call_tool=call_tool)


@pytest.fixture
async def recorded() -> AsyncIterator[list[httpx.Request]]:
    """Connect a `Client` over a recording HTTP client, list tools, exit, and yield every request sent.

    The HTTP client carries one caller-supplied header (`x-trace`) so its propagation can be
    asserted; the recording captures the closing DELETE because it is read after the `Client` has
    fully exited.
    """
    requests: list[httpx.Request] = []

    async def record(request: httpx.Request) -> None:
        requests.append(request)

    async with mounted_app(_tooled_server(), on_request=record, headers={"x-trace": "abc"}) as (http, _):
        async with client_via_http(http) as client:
            result = await client.list_tools()
        assert [tool.name for tool in result.tools] == ["echo"]

    yield requests


def _after_initialize(recorded: list[httpx.Request]) -> list[httpx.Request]:
    """Every recorded request after the initialize POST (which carries no session yet)."""
    assert recorded[0].method == "POST"
    assert "mcp-session-id" not in recorded[0].headers
    return recorded[1:]


@requirement("client-transport:http:custom-client")
@requirement("client-transport:http:custom-headers")
async def test_the_client_uses_the_supplied_http_client_and_propagates_its_headers(
    recorded: list[httpx.Request],
) -> None:
    """A caller-supplied `httpx.AsyncClient` is used for every request and carries its own headers.

    The recording itself proves the supplied client is the one in use; the propagated header
    proves the SDK transport does not replace the caller's client configuration.
    """
    # Exact ordering past the first request is not guaranteed (the standalone GET stream is
    # scheduled concurrently with later POSTs), so methods are asserted as a multiset.
    assert sorted(request.method for request in recorded) == snapshot(["DELETE", "GET", "POST", "POST", "POST"])
    assert all(request.headers["x-trace"] == "abc" for request in recorded)


@requirement("client-transport:http:session-stored")
async def test_every_request_after_initialize_carries_the_issued_session_id(recorded: list[httpx.Request]) -> None:
    """The session id from the initialize response is sent on every subsequent request."""
    session_ids = {request.headers["mcp-session-id"] for request in _after_initialize(recorded)}
    assert len(session_ids) == 1
    (session_id,) = session_ids
    assert session_id


@requirement("client-transport:http:protocol-version-stored")
@requirement("client-transport:http:protocol-version-header")
async def test_every_request_after_initialize_carries_the_negotiated_protocol_version(
    recorded: list[httpx.Request],
) -> None:
    """The negotiated protocol version is sent on every subsequent request (and not on initialize)."""
    assert "mcp-protocol-version" not in recorded[0].headers
    versions = {request.headers["mcp-protocol-version"] for request in _after_initialize(recorded)}
    assert versions == snapshot({"2025-11-25"})


@requirement("client-transport:http:accept-header-post")
@requirement("client-transport:http:accept-header-get")
async def test_accept_headers_cover_the_response_representations_the_transport_handles(
    recorded: list[httpx.Request],
) -> None:
    """POSTs accept both JSON and SSE; the standalone GET stream accepts SSE."""
    for request in recorded:
        if request.method == "POST":
            assert "application/json" in request.headers["accept"]
            assert "text/event-stream" in request.headers["accept"]
        if request.method == "GET":
            assert "text/event-stream" in request.headers["accept"]


@requirement("client-transport:http:no-reconnect-after-close")
async def test_closing_the_client_sends_delete_and_does_not_reconnect(recorded: list[httpx.Request]) -> None:
    """Client teardown sends DELETE and issues no further requests (no resumption GET)."""
    assert recorded[-1].method == "DELETE"
    assert all("last-event-id" not in request.headers for request in recorded)


@requirement("client-transport:http:concurrent-streams")
async def test_concurrent_tool_calls_each_open_a_post_stream_and_receive_their_own_response() -> None:
    """Three tool calls issued at once each open their own POST stream and get the right answer."""
    requests: list[httpx.Request] = []
    results: dict[int, CallToolResult] = {}

    async def record(request: httpx.Request) -> None:
        requests.append(request)

    async with mounted_app(_tooled_server(), on_request=record) as (http, _), client_via_http(http) as client:

        async def call(n: int) -> None:
            results[n] = await client.call_tool("echo", {"text": str(n)})

        with anyio.fail_after(5):  # pragma: no branch
            async with anyio.create_task_group() as tg:  # pragma: no branch
                for n in (1, 2, 3):
                    tg.start_soon(call, n)

    assert results == snapshot(
        {
            1: CallToolResult(content=[TextContent(text="1")]),
            2: CallToolResult(content=[TextContent(text="2")]),
            3: CallToolResult(content=[TextContent(text="3")]),
        }
    )
    tools_call_posts = [r for r in requests if r.method == "POST" and b'"tools/call"' in r.content]
    assert len(tools_call_posts) == 3


@requirement("client-transport:http:sse-405-tolerated")
@requirement("client-transport:http:terminate-405-ok")
async def test_client_tolerates_405_on_get_and_delete() -> None:
    """A 405 on the standalone GET stream or the closing DELETE does not fail the connection.

    The GET-stream task swallows the failure and schedules a reconnect that the closing cancel
    interrupts before it ever sleeps the full default delay; the DELETE 405 is logged and ignored.
    Neither surfaces to the caller.
    """
    server = _tooled_server()
    real_app = server.streamable_http_app(transport_security=NO_DNS_REBINDING_PROTECTION)

    async def filter_methods(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in ("GET", "DELETE"):
            await send({"type": "http.response.start", "status": 405, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        await real_app(scope, receive, send)

    async with (
        server.session_manager.run(),
        httpx.AsyncClient(transport=StreamingASGITransport(filter_methods), base_url=BASE_URL) as http_client,
    ):
        transport = streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client)
        with anyio.fail_after(5):  # pragma: no branch
            async with Client(transport, mode="legacy") as client:  # pragma: no branch
                result = await client.list_tools()

    assert [tool.name for tool in result.tools] == ["echo"]


@requirement("client-transport:http:no-reconnect-after-response")
async def test_a_completed_post_stream_is_not_reconnected() -> None:
    """A POST stream that delivered its response closes without a resumption GET.

    With an event store the server stamps every SSE event with an ID, so the client transport has a
    Last-Event-ID it could resume from -- the test proves it does not, because the response arrived
    and the stream completed normally.
    """
    requests: list[httpx.Request] = []

    async def record(request: httpx.Request) -> None:
        requests.append(request)

    server = _tooled_server()
    async with (
        mounted_app(server, event_store=SequencedEventStore(), retry_interval=0, on_request=record) as (http, _),
        client_via_http(http) as client,
    ):
        with anyio.fail_after(5):
            result = await client.list_tools()

    assert [tool.name for tool in result.tools] == ["echo"]
    resumption_gets = [r for r in requests if r.method == "GET" and "last-event-id" in r.headers]
    assert resumption_gets == []


@requirement("client-transport:http:404-surfaces")
async def test_a_404_mid_session_surfaces_as_a_session_terminated_error() -> None:
    """A 404 in response to a request after initialization is reported to the caller as an MCP error.

    The spec says the client MUST start a new session in this situation; the SDK instead surfaces a
    `Session terminated` error to the caller. The spec's MUST is tracked at
    client-transport:http:session-404-reinitialize; this test pins the SDK's current behaviour.
    """
    server = _tooled_server()
    real_app = server.streamable_http_app(transport_security=NO_DNS_REBINDING_PROTECTION)
    initialize_seen = anyio.Event()

    async def first_post_then_404(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] == "POST" and initialize_seen.is_set():
            await send({"type": "http.response.start", "status": 404, "headers": []})
            await send({"type": "http.response.body", "body": b""})
            return
        if scope["type"] == "http" and scope["method"] == "POST":
            initialize_seen.set()
        await real_app(scope, receive, send)

    async with (
        server.session_manager.run(),
        httpx.AsyncClient(transport=StreamingASGITransport(first_post_then_404), base_url=BASE_URL) as http_client,
    ):
        transport = streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client)
        with anyio.fail_after(5):  # pragma: no branch
            async with Client(transport, mode="legacy") as client:  # pragma: no branch
                with pytest.raises(MCPError) as exc_info:  # pragma: no branch
                    await client.list_tools()

    assert exc_info.value.error == snapshot(ErrorData(code=INVALID_REQUEST, message="Session terminated"))


def _blocking_server(started: anyio.Event, cancelled: anyio.Event) -> Server:
    """A server whose `block` tool parks until cancelled; `echo` answers normally."""

    async def list_tools(ctx: ServerRequestContext, params: types.PaginatedRequestParams | None) -> ListToolsResult:
        return ListToolsResult(tools=[Tool(name=name, input_schema={"type": "object"}) for name in ("block", "echo")])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        if params.name == "block":
            started.set()
            try:
                await anyio.Event().wait()  # parked until the client's abandonment cancels it
            except anyio.get_cancelled_exc_class():
                cancelled.set()
                raise
        assert params.name == "echo"
        return CallToolResult(content=[TextContent(text="ok")])

    return Server("blocker", on_list_tools=list_tools, on_call_tool=call_tool)


@requirement("client-transport:http:cancel-closes-stream")
async def test_at_2026_abandoning_a_call_closes_its_stream_and_posts_nothing() -> None:
    """At 2026-07-28, abandoning an in-flight call aborts that call's own POST - the server sees
    the disconnect and cancels exactly that handler - and no notifications/cancelled is POSTed.

    The follow-up echo call bounds the negative: POSTs leave the client's writer serially, so a
    cancel frame would have to appear before the echo's POST.
    """
    handler_started = anyio.Event()
    handler_cancelled = anyio.Event()
    requests: list[tuple[str, bytes]] = []

    async def record(request: httpx.Request) -> None:
        requests.append((request.method, request.content))

    server = _blocking_server(handler_started, handler_cancelled)
    async with mounted_app(server, on_request=record) as (http, _):
        transport = streamable_http_client(f"{BASE_URL}/mcp", http_client=http)
        async with Client(transport, mode="2026-07-28") as client:
            await client.list_tools()  # settles the schema cache so the calls below add no refresh POST
            abandon = anyio.CancelScope()

            async def call_and_abandon() -> None:
                with abandon:
                    await client.call_tool("block", {})
                    raise NotImplementedError  # unreachable: the call never resolves

            async with anyio.create_task_group() as tg:
                tg.start_soon(call_and_abandon)
                with anyio.fail_after(5):
                    await handler_started.wait()
                abandon.cancel()
                with anyio.fail_after(5):
                    await handler_cancelled.wait()

            result = await client.call_tool("echo", {})
            assert result.content == [TextContent(text="ok")]

    wire = [(method, json.loads(body)["method"] if body else None) for method, body in requests]
    assert wire == snapshot([("POST", "tools/list"), ("POST", "tools/call"), ("POST", "tools/call")])


@requirement("client-transport:http:cancel-posts-frame")
async def test_at_2025_abandoning_a_call_posts_exactly_one_cancelled_frame() -> None:
    """At 2025-era revisions, abandoning an in-flight call POSTs one notifications/cancelled
    naming the abandoned request's id - the frame is the legacy HTTP spelling of cancellation,
    and it interrupts the server-side handler.
    """
    handler_started = anyio.Event()
    handler_cancelled = anyio.Event()
    requests: list[tuple[str, bytes]] = []

    async def record(request: httpx.Request) -> None:
        requests.append((request.method, request.content))

    server = _blocking_server(handler_started, handler_cancelled)
    async with mounted_app(server, on_request=record) as (http, _):
        async with client_via_http(http) as client:
            abandon = anyio.CancelScope()

            async def call_and_abandon() -> None:
                with abandon:
                    await client.call_tool("block", {})
                    raise NotImplementedError  # unreachable: the call never resolves

            async with anyio.create_task_group() as tg:
                tg.start_soon(call_and_abandon)
                with anyio.fail_after(5):
                    await handler_started.wait()
                abandon.cancel()
                with anyio.fail_after(5):
                    await handler_cancelled.wait()
            # Let the abandoned call's late error response arrive and be dropped while the
            # client is still open, so teardown never races its delivery.
            await anyio.wait_all_tasks_blocked()

    posts = [json.loads(body) for method, body in requests if method == "POST" and body]
    block_calls = [p for p in posts if p.get("method") == "tools/call" and p["params"]["name"] == "block"]
    cancels = [p for p in posts if p.get("method") == "notifications/cancelled"]
    assert len(block_calls) == 1
    assert [c["params"]["requestId"] for c in cancels] == [block_calls[0]["id"]]
