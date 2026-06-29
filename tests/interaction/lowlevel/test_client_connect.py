"""Client connect-time negotiation: mode selection, server/discover, and the per-request envelope.

Each test drives `Client` and observes traffic at a recording seam: `RecordingTransport` for the
legacy stream pair, `mounted_app`'s httpx event hook for in-process streamable HTTP.
"""

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import anyio
import httpx
import mcp_types as types
import pytest
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION_META_KEY,
    UNSUPPORTED_PROTOCOL_VERSION,
    DiscoverResult,
    Implementation,
    InitializeResult,
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    ServerCapabilities,
    ToolsCapability,
)
from mcp_types.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION, MODERN_PROTOCOL_VERSIONS

from mcp import MCPError
from mcp.client._memory import InMemoryTransport
from mcp.client._transport import TransportStreams
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server, ServerRequestContext
from mcp.shared.memory import MessageStream, create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from tests.interaction._connect import BASE_URL, Connect, mounted_app
from tests.interaction._helpers import RecordingTransport
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio


def _tools_server(name: str = "negotiator") -> Server:
    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="noop", input_schema={"type": "object"})])

    return Server(name, on_list_tools=list_tools)


def _request_recorder() -> tuple[list[httpx.Request], Callable[[httpx.Request], Awaitable[None]]]:
    captured: list[httpx.Request] = []

    async def on_request(request: httpx.Request) -> None:
        captured.append(request)

    return captured, on_request


@requirement("lifecycle:mode:legacy-never-probes")
async def test_legacy_mode_sends_initialize_and_never_probes_discover() -> None:
    """`mode='legacy'` stays byte-identical to the pre-2026 client: a 2025-era server never sees modern vocabulary."""
    recording = RecordingTransport(InMemoryTransport(_tools_server()))

    with anyio.fail_after(5):
        async with Client(recording, mode="legacy") as client:
            await client.list_tools()

    sent = [m.message for m in recording.sent]
    methods = [m.method for m in sent if isinstance(m, JSONRPCRequest | JSONRPCNotification)]
    assert methods[0] == "initialize"
    assert "server/discover" not in methods
    assert "notifications/initialized" in methods


@requirement("lifecycle:mode:pin-never-handshakes")
async def test_pinned_mode_sends_no_connect_time_traffic() -> None:
    """A version pin adopts a synthesized DiscoverResult locally; nothing crosses the wire until the first call."""
    requests, on_request = _request_recorder()

    with anyio.fail_after(5):
        async with (
            mounted_app(_tools_server(), on_request=on_request) as (http, _),
            Client(streamable_http_client(f"{BASE_URL}/mcp", http_client=http), mode=LATEST_MODERN_VERSION) as client,
        ):
            assert requests == []
            result = await client.list_tools()

    bodies = [json.loads(r.content) for r in requests]
    assert [b["method"] for b in bodies] == ["tools/list"]
    assert PROTOCOL_VERSION_META_KEY in bodies[0]["params"]["_meta"]
    assert [t.name for t in result.tools] == ["noop"]


@requirement("lifecycle:mode:prior-discover-zero-rtt")
async def test_prior_discover_populates_state_with_zero_connect_time_traffic() -> None:
    prior = DiscoverResult(
        supported_versions=[LATEST_MODERN_VERSION],
        capabilities=ServerCapabilities(tools=ToolsCapability(list_changed=False)),
        server_info=Implementation(name="cached-server", version="9.9.9"),
    )
    requests, on_request = _request_recorder()

    with anyio.fail_after(5):
        async with (
            mounted_app(_tools_server(), on_request=on_request) as (http, _),
            Client(
                streamable_http_client(f"{BASE_URL}/mcp", http_client=http),
                mode=LATEST_MODERN_VERSION,
                prior_discover=prior,
            ) as client,
        ):
            assert requests == []
            assert client.server_info == Implementation(name="cached-server", version="9.9.9")
            assert client.server_capabilities.tools == ToolsCapability(list_changed=False)
            await client.list_tools()

    assert [json.loads(r.content)["method"] for r in requests] == ["tools/list"]


@requirement("lifecycle:discover:basic")
async def test_auto_mode_probes_server_discover_and_adopts_the_result() -> None:
    requests, on_request = _request_recorder()
    server = _tools_server("discoverable")

    with anyio.fail_after(5):
        async with (
            mounted_app(server, on_request=on_request) as (http, _),
            Client(streamable_http_client(f"{BASE_URL}/mcp", http_client=http), mode="auto") as client,
        ):
            assert client.protocol_version == LATEST_MODERN_VERSION
            assert client.server_info.name == "discoverable"
            await client.list_tools()

    bodies = [json.loads(r.content) for r in requests]
    assert bodies[0]["method"] == "server/discover"
    assert "initialize" not in [b["method"] for b in bodies]


@requirement("lifecycle:discover:retry-on-32022")
async def test_auto_mode_retries_discover_once_on_unsupported_protocol_version() -> None:
    """The client re-probes once at the intersection of `error.data.supported` and its own modern versions."""
    calls: list[str | None] = []

    async def discover(ctx: ServerRequestContext, params: types.RequestParams | None) -> DiscoverResult:
        proposed = ctx.meta.get(PROTOCOL_VERSION_META_KEY) if ctx.meta else None
        calls.append(proposed)
        if len(calls) == 1:
            raise MCPError(
                code=UNSUPPORTED_PROTOCOL_VERSION,
                message="unsupported protocol version",
                data={"supported": list(MODERN_PROTOCOL_VERSIONS), "requested": proposed},
            )
        return DiscoverResult(
            supported_versions=list(MODERN_PROTOCOL_VERSIONS),
            capabilities=ServerCapabilities(),
            server_info=Implementation(name="picky", version="1.0.0"),
        )

    server = _tools_server("picky")
    server.add_request_handler("server/discover", types.RequestParams, discover)
    requests, on_request = _request_recorder()

    with anyio.fail_after(5):
        async with (
            mounted_app(server, on_request=on_request) as (http, _),
            Client(streamable_http_client(f"{BASE_URL}/mcp", http_client=http), mode="auto") as client,
        ):
            assert client.protocol_version == LATEST_MODERN_VERSION

    assert calls == [LATEST_MODERN_VERSION, LATEST_MODERN_VERSION]
    assert [json.loads(r.content)["method"] for r in requests][:2] == ["server/discover", "server/discover"]


@requirement("lifecycle:discover:network-error-raises")
async def test_auto_mode_propagates_a_network_error_from_discover_without_initializing() -> None:
    """Rpc-errors and 4xx fall back to `initialize`; only real outages and the disjoint-modern -32022
    propagate — an outage is never an era verdict.

    The error arrives wrapped in the transport's task-group teardown, so `RaisesGroup` flattens before
    matching. The probe POST is recorded before the raise, proving the `initialize` fallback never ran.
    """
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        raise httpx.ConnectError("connection refused")

    with anyio.fail_after(5):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.RaisesGroup(httpx.ConnectError, flatten_subgroups=True):  # pragma: no branch
                async with Client(streamable_http_client(f"{BASE_URL}/mcp", http_client=http), mode="auto"):
                    raise NotImplementedError("entering the Client should have raised")  # pragma: no cover

    assert [json.loads(r.content)["method"] for r in requests] == ["server/discover"]


@requirement("lifecycle:discover:fallback-method-not-found")
@pytest.mark.parametrize(
    ("probe_code", "probe_message"),
    [
        (METHOD_NOT_FOUND, "Method not found"),
        (INVALID_REQUEST, "Bad Request: Missing session ID"),
    ],
    ids=["method-not-found", "invalid-request"],
)
async def test_auto_mode_falls_back_to_initialize_on_a_legacy_probe_rejection(
    probe_code: int, probe_message: str
) -> None:
    """A real `Server` always implements `server/discover`, so the server side is scripted by hand.

    METHOD_NOT_FOUND comes from a server that routes the unknown method; INVALID_REQUEST from a
    deployed v1.x stateful streamable-HTTP server that rejects the session-id-less probe before
    dispatch. Reserve the scripted pattern for behaviour no real server can be made to produce.
    """
    methods_seen: list[str] = []

    async def scripted_server(streams: MessageStream) -> None:
        server_read, server_write = streams
        async for message in server_read:
            assert isinstance(message, SessionMessage)
            frame = message.message
            assert isinstance(frame, JSONRPCRequest | JSONRPCNotification)
            methods_seen.append(frame.method)
            if isinstance(frame, JSONRPCRequest) and frame.method == "server/discover":
                error = types.ErrorData(code=probe_code, message=probe_message)
                await server_write.send(SessionMessage(JSONRPCError(jsonrpc="2.0", id=frame.id, error=error)))
            elif isinstance(frame, JSONRPCRequest) and frame.method == "initialize":
                result = InitializeResult(
                    protocol_version=LATEST_HANDSHAKE_VERSION,
                    capabilities=ServerCapabilities(),
                    server_info=Implementation(name="legacy-only", version="0.0.1"),
                )
                await server_write.send(
                    SessionMessage(
                        JSONRPCResponse(
                            jsonrpc="2.0",
                            id=frame.id,
                            result=result.model_dump(by_alias=True, mode="json", exclude_none=True),
                        )
                    )
                )
            # notifications/initialized (and anything else) is observed and ignored.

    @asynccontextmanager
    async def scripted_transport() -> AsyncIterator[TransportStreams]:
        async with (
            create_client_server_memory_streams() as ((client_read, client_write), server_streams),
            anyio.create_task_group() as tg,
        ):
            tg.start_soon(scripted_server, server_streams)
            yield client_read, client_write
            tg.cancel_scope.cancel()

    with anyio.fail_after(5):
        async with Client(scripted_transport(), mode="auto") as client:
            assert client.protocol_version == LATEST_HANDSHAKE_VERSION
            assert client.server_info.name == "legacy-only"

    assert methods_seen == ["server/discover", "initialize", "notifications/initialized"]


@requirement("lifecycle:envelope:stamped-on-every-request")
async def test_every_request_on_a_modern_session_carries_the_three_key_meta_envelope(connect: Connect) -> None:
    """The per-request envelope replaces the initialize handshake's once-per-session exchange."""
    observed: list[dict[str, object]] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        assert ctx.meta is not None
        observed.append(dict(ctx.meta))
        return types.ListToolsResult(tools=[])

    server = Server("stamped", on_list_tools=list_tools)

    with anyio.fail_after(5):
        async with connect(server, client_info=Implementation(name="enveloper", version="1.2.3")) as client:
            await client.list_tools()
            await client.list_tools()

    assert len(observed) == 2
    for meta in observed:
        assert meta[PROTOCOL_VERSION_META_KEY] == LATEST_MODERN_VERSION
        assert meta[CLIENT_INFO_META_KEY] == {"name": "enveloper", "version": "1.2.3"}
        assert CLIENT_CAPABILITIES_META_KEY in meta


@requirement("lifecycle:envelope:header-matches-meta")
async def test_http_protocol_version_header_matches_meta_protocol_version_on_every_post() -> None:
    """Header and envelope stay in lockstep so header-based routing and body-based validation never disagree."""
    requests, on_request = _request_recorder()

    with anyio.fail_after(5):
        async with (
            mounted_app(_tools_server(), on_request=on_request) as (http, _),
            Client(streamable_http_client(f"{BASE_URL}/mcp", http_client=http), mode=LATEST_MODERN_VERSION) as client,
        ):
            await client.list_tools()
            await client.list_tools()

    assert requests, "no HTTP traffic recorded"
    for request in requests:
        body = json.loads(request.content)
        assert request.headers["mcp-protocol-version"] == body["params"]["_meta"][PROTOCOL_VERSION_META_KEY]
        assert request.headers["mcp-protocol-version"] == LATEST_MODERN_VERSION
