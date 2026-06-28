"""Client connect-time negotiation: mode selection, server/discover, and the per-request envelope.

These tests pin what `Client(..., mode=...)` puts on the wire BEFORE the caller's first call --
the legacy initialize handshake, the modern `server/discover` probe, or nothing at all -- and
that a modern-negotiated session stamps the three-key `io.modelcontextprotocol/*` `_meta`
envelope on every subsequent request. Each test drives the highest public surface (`Client`)
and observes traffic at a recording seam: `RecordingTransport` for the legacy stream pair, and
`mounted_app`'s httpx event hook for the in-process streamable-HTTP transport.

The fallback test alone hand-plays the server's side of the wire, because no real `Server`
answers `server/discover` with -32601.
"""

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import anyio
import httpx
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION_META_KEY,
    UNSUPPORTED_PROTOCOL_VERSION,
    CompletionsCapability,
    DiscoverResult,
    Implementation,
    InitializeResult,
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    PromptsCapability,
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
    """A low-level server with one list-tools handler, so a feature request has something to reach."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="noop", input_schema={"type": "object"})])

    return Server(name, on_list_tools=list_tools)


def _request_recorder() -> tuple[list[httpx.Request], Callable[[httpx.Request], Awaitable[None]]]:
    """Return a list and an `on_request` hook that appends each outgoing httpx request to it."""
    captured: list[httpx.Request] = []

    async def on_request(request: httpx.Request) -> None:
        captured.append(request)

    return captured, on_request


@requirement("lifecycle:mode:legacy-never-probes")
async def test_legacy_mode_sends_initialize_and_never_probes_discover() -> None:
    """`Client(server, mode='legacy')` opens with `initialize` and never sends `server/discover`.

    Requirement `lifecycle:mode:legacy-never-probes` (sdk-defined): ``mode='legacy'`` must remain
    byte-identical to the pre-2026 client so a 2025-era server never observes modern vocabulary.
    """
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
    """`Client(..., mode='2026-07-28')` sends nothing on entry; the caller's first call is the first wire request.

    Requirement `lifecycle:mode:pin-never-handshakes` (sdk-defined): a version pin adopts a
    synthesized DiscoverResult locally, so no `initialize` and no `server/discover` ever cross
    the wire. Asserted at the in-process streamable-HTTP seam via the httpx event hook.
    """
    requests, on_request = _request_recorder()

    with anyio.fail_after(5):
        async with (
            mounted_app(_tools_server(), on_request=on_request) as (http, _),
            Client(streamable_http_client(f"{BASE_URL}/mcp", http_client=http), mode=LATEST_MODERN_VERSION) as client,
        ):
            assert requests == []  # entering the Client produced zero HTTP traffic
            result = await client.list_tools()

    bodies = [json.loads(r.content) for r in requests]
    assert [b["method"] for b in bodies] == ["tools/list"]
    assert PROTOCOL_VERSION_META_KEY in bodies[0]["params"]["_meta"]
    assert [t.name for t in result.tools] == ["noop"]


@requirement("lifecycle:mode:prior-discover-zero-rtt")
async def test_prior_discover_populates_state_with_zero_connect_time_traffic() -> None:
    """`Client(..., mode=<pin>, prior_discover=...)` sends nothing on entry and exposes the prior server_info.

    Requirement `lifecycle:mode:prior-discover-zero-rtt` (sdk-defined): a previously-obtained
    DiscoverResult is installed via `adopt()` so server_info and capabilities are available
    immediately with zero round trips.
    """
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
    """`Client(..., mode='auto')` sends `server/discover` first and adopts the returned version and server_info.

    Requirement `lifecycle:discover:basic` (spec server/discover): the probe is a
    single `server/discover` request whose result carries supported versions, capabilities,
    server_info and the cache-hint fields, after which the session is modern-negotiated.
    """
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
    """A -32022 from `server/discover` triggers exactly one retry at the highest mutual modern version.

    Requirement `lifecycle:discover:retry-on-32022` (spec basic/versioning#protocol-version-negotiation): the
    client intersects `error.data.supported` with its own modern versions and re-probes once;
    the second success is adopted. The server's `server/discover` handler is overridden to fail
    the first call and succeed on the second.
    """
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
    """A network/connection error during `server/discover` propagates to the caller without falling back.

    Requirement `lifecycle:discover:network-error-raises` (sdk-defined): under the denylist policy
    every server-sent rpc-error and every transport-layer 4xx falls back to `initialize()`; the
    only probe failures that reach the caller are real outages — network errors, anyio resource
    errors, and the disjoint-modern -32022 case. Exercised here as an `httpx.ConnectError` from
    the underlying transport, which the policy must not classify as an era verdict. The error
    reaches the test wrapped in the streamable-http transport's task-group teardown, so
    `pytest.RaisesGroup` flattens before matching. The probe POST is recorded before the
    transport raises, so the `initialize` fallback observably did not happen.
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
    """A legacy server's rejection of `server/discover` makes an auto-negotiating client fall back to `initialize`.

    Requirement `lifecycle:discover:fallback-method-not-found` (spec stdio#backward-compatibility):
    a legacy-era server that does not implement `server/discover` is connected to via the
    handshake, and the session lands at a handshake-era protocol version. The probe rejection
    arrives as METHOD_NOT_FOUND from a server that routes the unknown method, or as
    INVALID_REQUEST from a deployed v1.x stateful streamable-HTTP server that rejects the
    session-id-less probe before dispatch. A real `Server` always implements `server/discover`,
    so this test plays the server's side of the wire by hand. Reserve this pattern for behaviour
    no real server can be made to produce.
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
    """Each modern-session request's `params._meta` carries protocolVersion, clientInfo and clientCapabilities.

    Requirement `lifecycle:envelope:stamped-on-every-request` (spec basic#_meta): the per-request
    envelope replaces the initialize handshake's once-per-session exchange. Asserted server-side
    by capturing `ctx.meta` inside the handler.
    """
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
    """On streamable-HTTP, the `MCP-Protocol-Version` header on each POST equals `_meta.protocolVersion` in its body.

    Requirement `lifecycle:envelope:header-matches-meta` (spec streamable-http#protocol-version-header): the
    body-derived header and the envelope's protocol version are kept in lockstep so the server's
    header-based routing and body-based validation never disagree.
    """
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


@requirement("lifecycle:discover:instructions")
async def test_discover_carries_server_instructions_and_omits_them_when_undeclared() -> None:
    """A server's instructions string arrives through the `server/discover` result; an undeclared one reads None.

    Requirement `lifecycle:discover:instructions` (spec server/discover#discoverresult): the field
    rides the discover result, so the client connects in its default auto mode -- the only public
    vehicle that performs a real `server/discover` round trip (the fixture's pinned 2026 cells adopt
    a synthesized empty DiscoverResult and never observe server-side discover content). Asserting
    the modern protocol version on both arms proves the carrier was discover, not an initialize
    fallback, which would also expose instructions.
    """
    with anyio.fail_after(5):
        async with Client(Server("guided", instructions="Call the add tool.")) as client:
            assert client.protocol_version == LATEST_MODERN_VERSION
            assert client.instructions == snapshot("Call the add tool.")

    with anyio.fail_after(5):
        async with Client(Server("unguided")) as client:
            assert client.protocol_version == LATEST_MODERN_VERSION
            assert client.instructions is None


@requirement("lifecycle:discover:capabilities:from-handlers")
async def test_discover_capabilities_reflect_registered_handlers() -> None:
    """The discover result advertises a capability per registered handler area and omits the rest.

    Requirement `lifecycle:discover:capabilities:from-handlers` (spec server/discover#response):
    capabilities derive from the registered handlers; the full-object snapshot proves the
    unregistered areas stay None, and the bare server advertises nothing at all. `list_changed=False`
    comes from the default NotificationOptions, as in the 2025 initialize sibling. Only era-clean
    areas (tools/prompts/completions) are registered on purpose: the derivation is era-agnostic, so
    a subscribe or logging handler would advertise a capability whose method is era-removed at
    2026-07-28 -- a quirk deliberately left unpinned here.
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        """Registered only so the tools capability is advertised; never called."""
        raise NotImplementedError

    async def list_prompts(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListPromptsResult:
        """Registered only so the prompts capability is advertised; never called."""
        raise NotImplementedError

    async def completion(ctx: ServerRequestContext, params: types.CompleteRequestParams) -> types.CompleteResult:
        """Registered only so the completions capability is advertised; never called."""
        raise NotImplementedError

    server = Server("capable", on_list_tools=list_tools, on_list_prompts=list_prompts, on_completion=completion)

    with anyio.fail_after(5):
        async with Client(server) as client:
            assert client.protocol_version == LATEST_MODERN_VERSION
            assert client.server_capabilities == snapshot(
                ServerCapabilities(
                    prompts=PromptsCapability(list_changed=False),
                    completions=CompletionsCapability(),
                    tools=ToolsCapability(list_changed=False),
                )
            )

    with anyio.fail_after(5):
        async with Client(Server("bare")) as client:
            assert client.server_capabilities == ServerCapabilities()


@requirement("lifecycle:mode:auto-probes-first")
async def test_auto_mode_sends_discover_before_any_other_request_at_its_preferred_modern_version() -> None:
    """An auto-negotiating client's first wire request is `server/discover`, stamped with its preferred modern version.

    Requirement `lifecycle:mode:auto-probes-first` (spec stdio#backward-compatibility, a SHOULD): a
    dual-era client sends the probe before any other request, carrying its preferred modern version
    in `_meta.protocolVersion`. The complete recorded method sequence is the before-any-other-request
    clause -- nothing preceded the probe and nothing rode alongside it. The spec sentence lives on
    the stdio page but binds connect-time ordering in transport-independent client code, asserted
    here at the in-process streamable-HTTP seam like the sibling backward-compatibility entries.
    """
    requests, on_request = _request_recorder()

    with anyio.fail_after(5):
        async with (
            mounted_app(_tools_server(), on_request=on_request) as (http, _),
            Client(streamable_http_client(f"{BASE_URL}/mcp", http_client=http), mode="auto") as client,
        ):
            await client.list_tools()

    bodies = [json.loads(r.content) for r in requests]
    assert [b["method"] for b in bodies] == ["server/discover", "tools/list"]
    assert bodies[0]["params"]["_meta"][PROTOCOL_VERSION_META_KEY] == LATEST_MODERN_VERSION


@requirement("lifecycle:discover:era-cached")
async def test_auto_mode_probes_discover_once_and_reuses_it_for_the_connection_lifetime() -> None:
    """One `server/discover` probe serves the whole connection; an explicit `discover()` re-fetches nothing.

    Requirement `lifecycle:discover:era-cached` (spec basic/versioning#backward-compatibility-with-
    initialization-based-versions, a SHOULD): the era determination is cached for the connection.
    The complete recorded method list proves exactly one probe preceded three feature calls and
    that the explicit `discover()` call added no POST. `ClientSession` is reached directly because
    `Client` exposes no re-fetch surface; `discover()` / `discover_result` are its documented
    cache API. The `is` assert proves the same adopted object is returned, not an equal copy.
    """
    requests, on_request = _request_recorder()

    with anyio.fail_after(5):
        async with (
            mounted_app(_tools_server(), on_request=on_request) as (http, _),
            Client(streamable_http_client(f"{BASE_URL}/mcp", http_client=http), mode="auto") as client,
        ):
            adopted = client.session.discover_result
            await client.list_tools()
            await client.list_tools()
            await client.list_tools()
            again = await client.session.discover()

    assert [json.loads(r.content)["method"] for r in requests] == [
        "server/discover",
        "tools/list",
        "tools/list",
        "tools/list",
    ]
    assert again is adopted


@requirement("lifecycle:discover:retry-on-32022")
async def test_auto_mode_raises_when_discover_rejects_with_a_disjoint_supported_list() -> None:
    """A -32022 whose `supported` list shares no version with the client raises -- no retry, no initialize.

    Requirement `lifecycle:discover:retry-on-32022` (spec basic/versioning#protocol-version-negotiation):
    the empty-intersection clause. The overridden `server/discover` handler advertises only
    "1999-12-31": a modern member would trigger the one-shot retry and a handshake member the
    initialize fallback, so the fully-disjoint list isolates the raise. The wire record asserted
    after the app context is the equally load-bearing negative -- exactly one probe, no second
    probe, no `initialize` (spec stdio#backward-compatibility: a recognized modern error must not
    fall back to the handshake). The error surfaces through the streamable-http task-group
    teardown as nested ExceptionGroups, so `RaisesGroup` flattens before matching; only the code
    is checked because the message and data are this test's own scripted values.
    """

    async def discover(ctx: ServerRequestContext, params: types.RequestParams | None) -> DiscoverResult:
        proposed = ctx.meta.get(PROTOCOL_VERSION_META_KEY) if ctx.meta else None
        raise MCPError(
            code=UNSUPPORTED_PROTOCOL_VERSION,
            message="unsupported protocol version",
            data={"supported": ["1999-12-31"], "requested": proposed},
        )

    server = _tools_server("disjoint")
    server.add_request_handler("server/discover", types.RequestParams, discover)
    requests, on_request = _request_recorder()

    with anyio.fail_after(5):
        async with mounted_app(server, on_request=on_request) as (http, _):
            with pytest.RaisesGroup(
                pytest.RaisesExc(MCPError, check=lambda e: e.error.code == UNSUPPORTED_PROTOCOL_VERSION),
                flatten_subgroups=True,
            ):
                async with Client(streamable_http_client(f"{BASE_URL}/mcp", http_client=http), mode="auto"):
                    raise NotImplementedError("entering the Client should have raised")  # pragma: no cover

    assert [json.loads(r.content)["method"] for r in requests] == ["server/discover"]
