"""Behaviour of the streamable-HTTP client transport, observed at the wire.

A real `Client` talks to a real server over the in-process bridge, recording every HTTP request,
so assertions are about what the transport sends rather than what the protocol layer returns.
"""

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

    The caller-supplied `x-trace` header lets tests assert header propagation; reading after exit
    captures the closing DELETE.
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
    # The standalone GET stream is scheduled concurrently with later POSTs, so methods are a multiset.
    assert sorted(request.method for request in recorded) == snapshot(["DELETE", "GET", "POST", "POST", "POST"])
    assert all(request.headers["x-trace"] == "abc" for request in recorded)


@requirement("client-transport:http:session-stored")
async def test_every_request_after_initialize_carries_the_issued_session_id(recorded: list[httpx.Request]) -> None:
    session_ids = {request.headers["mcp-session-id"] for request in _after_initialize(recorded)}
    assert len(session_ids) == 1
    (session_id,) = session_ids
    assert session_id


@requirement("client-transport:http:protocol-version-stored")
@requirement("client-transport:http:protocol-version-header")
async def test_every_request_after_initialize_carries_the_negotiated_protocol_version(
    recorded: list[httpx.Request],
) -> None:
    assert "mcp-protocol-version" not in recorded[0].headers
    versions = {request.headers["mcp-protocol-version"] for request in _after_initialize(recorded)}
    assert versions == snapshot({"2025-11-25"})


@requirement("client-transport:http:accept-header-post")
@requirement("client-transport:http:accept-header-get")
async def test_accept_headers_cover_the_response_representations_the_transport_handles(
    recorded: list[httpx.Request],
) -> None:
    for request in recorded:
        if request.method == "POST":
            assert "application/json" in request.headers["accept"]
            assert "text/event-stream" in request.headers["accept"]
        if request.method == "GET":
            assert "text/event-stream" in request.headers["accept"]


@requirement("client-transport:http:no-reconnect-after-close")
async def test_closing_the_client_sends_delete_and_does_not_reconnect(recorded: list[httpx.Request]) -> None:
    assert recorded[-1].method == "DELETE"
    assert all("last-event-id" not in request.headers for request in recorded)


@requirement("client-transport:http:concurrent-streams")
async def test_concurrent_tool_calls_each_open_a_post_stream_and_receive_their_own_response() -> None:
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
    """Neither 405 surfaces to the caller.

    The GET-stream task swallows the failure and schedules a reconnect that the closing cancel
    interrupts before its delay elapses; the DELETE 405 is logged and ignored.
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
    """The event store gives the client a Last-Event-ID it could resume from; it must not.

    The response arrived and the stream completed normally, so no resumption GET may follow.
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
    """The spec says the client MUST start a new session here; the SDK surfaces an error instead.

    The MUST is tracked at client-transport:http:session-404-reinitialize; this pins current behaviour.
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
