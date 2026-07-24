"""Transport-parametrized connection factories for the interaction suite.

The `connect` fixture (see conftest.py) hands tests one of these factories so the same test body
runs over each transport without naming any of them: the factory is a drop-in replacement for
constructing `Client(server, ...)` and yields the connected client. The HTTP factories drive the
server's real Starlette app through the in-process streaming bridge, so the full transport layer
(session ids, SSE encoding, session management) runs with no sockets, threads, or subprocesses.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from functools import partial
from typing import Any, Protocol

import httpx2
from httpx2 import ServerSentEvent
from mcp_types import (
    ClientCapabilities,
    Implementation,
    InitializeRequestParams,
    JSONRPCMessage,
    JSONRPCRequest,
    JSONRPCResponse,
    jsonrpc_message_adapter,
)
from mcp_types.version import LATEST_HANDSHAKE_VERSION, MODERN_PROTOCOL_VERSIONS
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from mcp.client.client import Client
from mcp.client.extension import ClientExtension
from mcp.client.session import ElicitationFnT, ListRootsFnT, LoggingFnT, MessageHandlerFnT, SamplingFnT
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server
from mcp.server.auth.provider import OAuthAuthorizationServerProvider, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http import EventStore
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from tests.interaction.transports._bridge import StreamingASGITransport

# The in-process app is mounted at this origin purely so URLs are well-formed; nothing listens here.
BASE_URL = "http://127.0.0.1:8000"

# DNS-rebinding protection validates Host/Origin headers against a real network attack that cannot
# exist for an in-process ASGI app, so the in-process factories disable it; tests that exercise the
# protection itself pass explicit settings (or transport_security=None to get the localhost
# auto-enable behaviour).
NO_DNS_REBINDING_PROTECTION = TransportSecuritySettings(enable_dns_rebinding_protection=False)


class Connect(Protocol):
    """Connect a Client to a server over the transport selected by the `connect` fixture.

    Accepts the same keyword arguments as `Client` and yields the connected client.
    """

    def __call__(
        self,
        server: Server | MCPServer,
        *,
        read_timeout_seconds: float | None = None,
        sampling_callback: SamplingFnT | None = None,
        list_roots_callback: ListRootsFnT | None = None,
        logging_callback: LoggingFnT | None = None,
        message_handler: MessageHandlerFnT | None = None,
        client_info: Implementation | None = None,
        elicitation_callback: ElicitationFnT | None = None,
        extensions: Sequence[ClientExtension] | None = None,
        spec_version: str = LATEST_HANDSHAKE_VERSION,
    ) -> AbstractAsyncContextManager[Client]: ...


@asynccontextmanager
async def connect_in_memory(
    server: Server | MCPServer,
    *,
    read_timeout_seconds: float | None = None,
    sampling_callback: SamplingFnT | None = None,
    list_roots_callback: ListRootsFnT | None = None,
    logging_callback: LoggingFnT | None = None,
    message_handler: MessageHandlerFnT | None = None,
    client_info: Implementation | None = None,
    elicitation_callback: ElicitationFnT | None = None,
    extensions: Sequence[ClientExtension] | None = None,
    spec_version: str = LATEST_HANDSHAKE_VERSION,
) -> AsyncIterator[Client]:
    """Yield a Client connected to the server over the in-memory transport.

    When `spec_version` is a modern (2026-07-28+) revision the Client is opened with
    `mode=<version>`, which drives the server through the DirectDispatcher peer-pair
    (per-request `serve_one`, no initialize handshake) instead of the legacy stream pair.
    """
    async with Client(
        server,
        mode=spec_version if spec_version in MODERN_PROTOCOL_VERSIONS else "legacy",
        read_timeout_seconds=read_timeout_seconds,
        sampling_callback=sampling_callback,
        list_roots_callback=list_roots_callback,
        logging_callback=logging_callback,
        message_handler=message_handler,
        client_info=client_info,
        elicitation_callback=elicitation_callback,
        extensions=extensions,
    ) as client:
        yield client


@asynccontextmanager
async def connect_over_streamable_http(
    server: Server | MCPServer,
    *,
    stateless_http: bool = False,
    json_response: bool = False,
    event_store: EventStore | None = None,
    retry_interval: int | None = None,
    read_timeout_seconds: float | None = None,
    sampling_callback: SamplingFnT | None = None,
    list_roots_callback: ListRootsFnT | None = None,
    logging_callback: LoggingFnT | None = None,
    message_handler: MessageHandlerFnT | None = None,
    client_info: Implementation | None = None,
    elicitation_callback: ElicitationFnT | None = None,
    extensions: Sequence[ClientExtension] | None = None,
    spec_version: str = LATEST_HANDSHAKE_VERSION,
) -> AsyncIterator[Client]:
    """Yield a Client connected to the server's streamable HTTP app, entirely in process.

    With the defaults this is the matrix leg (stateful sessions, SSE responses); the stateless
    matrix arm binds `stateless_http=True` (see `connect_over_streamable_http_stateless`);
    transport-specific tests pass `json_response` to select the other server mode, and the
    resumability tests pass an `event_store` (with `retry_interval=0` so the client's
    reconnection wait is a no-op).

    When `spec_version` is a modern (2026-07-28+) revision the Client is opened with
    `mode=<version>`, which adopts a synthesized DiscoverResult instead of running the legacy
    initialize handshake.
    """
    app = server.streamable_http_app(
        stateless_http=stateless_http,
        json_response=json_response,
        event_store=event_store,
        retry_interval=retry_interval,
        transport_security=NO_DNS_REBINDING_PROTECTION,
    )
    async with (
        server.session_manager.run(),
        httpx2.AsyncClient(transport=StreamingASGITransport(app), base_url=BASE_URL) as http_client,
        Client(
            streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client),
            mode=spec_version if spec_version in MODERN_PROTOCOL_VERSIONS else "legacy",
            read_timeout_seconds=read_timeout_seconds,
            sampling_callback=sampling_callback,
            list_roots_callback=list_roots_callback,
            logging_callback=logging_callback,
            message_handler=message_handler,
            client_info=client_info,
            elicitation_callback=elicitation_callback,
            extensions=extensions,
        ) as client,
    ):
        yield client


connect_over_streamable_http_stateless: Connect = partial(connect_over_streamable_http, stateless_http=True)
"""The streamable-http matrix arm with the server in stateless mode (fresh transport per request,
no session id, no standalone GET stream). The same shared Server instance backs every request --
stateless mode does not require a server factory."""


@asynccontextmanager
async def mounted_app(
    server: Server | MCPServer,
    *,
    stateless_http: bool = False,
    json_response: bool = False,
    event_store: EventStore | None = None,
    retry_interval: int | None = None,
    transport_security: TransportSecuritySettings | None = NO_DNS_REBINDING_PROTECTION,
    on_request: Callable[[httpx2.Request], Awaitable[None]] | None = None,
    on_response: Callable[[httpx2.Response], Awaitable[None]] | None = None,
    headers: dict[str, str] | None = None,
    auth: AuthSettings | None = None,
    token_verifier: TokenVerifier | None = None,
    auth_server_provider: OAuthAuthorizationServerProvider[Any, Any, Any] | None = None,
) -> AsyncIterator[tuple[httpx2.AsyncClient, StreamableHTTPSessionManager]]:
    """Mount the server's streamable HTTP app on the in-process bridge and yield an httpx2 client.

    Yields the httpx2 client (rooted at the in-process origin) and the live session manager. Tests
    use this in two ways: for raw-httpx2 assertions (status codes, headers, SSE bytes) the test
    speaks HTTP through the yielded client directly; for client-driven assertions the test wraps
    that client in `client_via_http(http)`, which lets several `Client`s share the one mounted
    session manager. `on_request` observes every outgoing HTTP request before it leaves the
    yielded client; `on_response` observes every HTTP response as its headers arrive (response
    bodies of SSE streams are not yet read at that point).

    DNS-rebinding protection is disabled by default; pass explicit settings (or `None` for the
    localhost auto-enable behaviour) to test the protection itself.
    """
    lowlevel = server._lowlevel_server if isinstance(server, MCPServer) else server
    app = lowlevel.streamable_http_app(
        stateless_http=stateless_http,
        json_response=json_response,
        event_store=event_store,
        retry_interval=retry_interval,
        transport_security=transport_security,
        auth=auth,
        token_verifier=token_verifier,
        auth_server_provider=auth_server_provider,
    )
    event_hooks: dict[str, list[Callable[..., Awaitable[None]]]] = {}
    if on_request is not None:
        event_hooks["request"] = [on_request]
    if on_response is not None:
        event_hooks["response"] = [on_response]
    async with (
        server.session_manager.run(),
        httpx2.AsyncClient(
            transport=StreamingASGITransport(app), base_url=BASE_URL, event_hooks=event_hooks, headers=headers
        ) as http_client,
    ):
        yield http_client, server.session_manager


@asynccontextmanager
async def client_via_http(
    http_client: httpx2.AsyncClient,
    *,
    logging_callback: LoggingFnT | None = None,
    message_handler: MessageHandlerFnT | None = None,
    elicitation_callback: ElicitationFnT | None = None,
) -> AsyncIterator[Client]:
    """Connect a `Client` over an already-mounted streamable HTTP app.

    Use with `mounted_app(...)` so several `Client`s share the one session manager, or so a
    client-driven assertion can sit alongside raw-httpx2 assertions in the same test. The
    underlying `httpx2.AsyncClient` is left open when the `Client` exits.
    """
    transport = streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client)
    async with Client(
        transport,
        # Callers assert the legacy HTTP wire shape (session-id header, standalone GET stream,
        # closing DELETE); the modern flow is sessionless and would silently change the subject.
        mode="legacy",
        logging_callback=logging_callback,
        message_handler=message_handler,
        elicitation_callback=elicitation_callback,
    ) as client:
        yield client


def parse_sse_messages(events: Iterable[ServerSentEvent]) -> list[JSONRPCMessage]:
    """Decode SSE events into JSON-RPC messages, skipping priming events that carry no data."""
    return [jsonrpc_message_adapter.validate_json(event.data) for event in events if event.data]


async def post_jsonrpc(
    http: httpx2.AsyncClient, body: dict[str, object], *, session_id: str | None = None
) -> tuple[httpx2.Response, list[JSONRPCMessage]]:
    """POST a JSON-RPC body and read its SSE response stream to completion.

    Returns the HTTP response (for header/status assertions) and the parsed JSON-RPC messages
    that arrived on the response's SSE stream. Only meaningful for requests the server answers
    with `text/event-stream`; for error responses or 202 notification acknowledgements, use
    `httpx2.AsyncClient.post` directly and assert on the response.
    """
    async with http.sse("/mcp", method="POST", json=body, headers=base_headers(session_id=session_id)) as source:
        events = [event async for event in source]
    return source.response, parse_sse_messages(events)


def base_headers(*, session_id: str | None = None) -> dict[str, str]:
    """Standard request headers for raw-httpx2 streamable-HTTP tests.

    Every well-formed request carries these (Accept covering both response representations,
    Content-Type for POST bodies, MCP-Protocol-Version at the newest handshake revision, and the session
    ID once one exists), so a test that wants to assert a specific rejection only varies the one
    header under test.
    """
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "mcp-protocol-version": LATEST_HANDSHAKE_VERSION,
    }
    if session_id is not None:
        headers["mcp-session-id"] = session_id
    return headers


def initialize_body(request_id: int = 1) -> dict[str, object]:
    """A wire-level initialize JSON-RPC request body, exactly as an SDK client would send it."""
    params = InitializeRequestParams(
        protocol_version=LATEST_HANDSHAKE_VERSION,
        capabilities=ClientCapabilities(),
        client_info=Implementation(name="raw", version="0.0.0"),
    )
    return JSONRPCRequest(
        jsonrpc="2.0", id=request_id, method="initialize", params=params.model_dump(by_alias=True, exclude_none=True)
    ).model_dump(by_alias=True, exclude_none=True)


async def initialize_via_http(http: httpx2.AsyncClient) -> str:
    """Perform the initialize handshake over a raw `httpx2.AsyncClient` and return the session ID.

    Validates the SSE response and sends the `notifications/initialized` follow-up, so the server
    is fully ready for subsequent feature requests when this returns.
    """
    async with http.sse("/mcp", method="POST", json=initialize_body(), headers=base_headers()) as source:
        assert source.response.status_code == 200
        # An event-store-backed server opens the stream with a priming event (empty data); skip it.
        events = [event async for event in source if event.data]
    assert len(events) == 1
    assert JSONRPCResponse.model_validate_json(events[0].data).id == 1
    session_id = source.response.headers["mcp-session-id"]
    initialized = await http.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers=base_headers(session_id=session_id),
    )
    assert initialized.status_code == 202
    return session_id


def build_sse_app(server: Server | MCPServer) -> tuple[Starlette, SseServerTransport]:
    """Mount a server on a Starlette app exposing the legacy SSE transport at /sse and /messages/.

    `MCPServer.sse_app()` exists but does not expose the underlying `SseServerTransport`, which
    the SSE-specific tests need; building the app explicitly here gives both server flavours the
    same routing while keeping that handle.
    """
    sse = SseServerTransport(
        "/messages/", security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )
    lowlevel = server._lowlevel_server if isinstance(server, MCPServer) else server

    async def handle_sse(request: Request) -> Response:
        async with sse.connect_sse(request.scope, request.receive, request._send) as (read, write):
            await lowlevel.run(read, write, lowlevel.create_initialization_options())
        return Response()

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse, methods=["GET"]),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )
    return app, sse


@asynccontextmanager
async def connect_over_sse(
    server: Server | MCPServer,
    *,
    read_timeout_seconds: float | None = None,
    sampling_callback: SamplingFnT | None = None,
    list_roots_callback: ListRootsFnT | None = None,
    logging_callback: LoggingFnT | None = None,
    message_handler: MessageHandlerFnT | None = None,
    client_info: Implementation | None = None,
    elicitation_callback: ElicitationFnT | None = None,
    extensions: Sequence[ClientExtension] | None = None,
    spec_version: str = LATEST_HANDSHAKE_VERSION,
) -> AsyncIterator[Client]:
    """Yield a Client connected to the server's legacy SSE transport, entirely in process."""
    app, _ = build_sse_app(server)

    def httpx_client_factory(
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
    ) -> httpx2.AsyncClient:
        # The SSE server transport's connect_sse runs the entire MCP session inside the GET
        # request and only releases its streams after that request observes a disconnect, so the
        # bridge must let the application drain rather than cancelling at close.
        return httpx2.AsyncClient(
            transport=StreamingASGITransport(app, cancel_on_close=False),
            base_url=BASE_URL,
            headers=headers,
            timeout=timeout,
            auth=auth,
        )

    transport = sse_client(f"{BASE_URL}/sse", httpx_client_factory=httpx_client_factory)
    async with Client(
        transport,
        # SSE is a legacy-only transport; the modern path has no SSE story.
        mode="legacy",
        read_timeout_seconds=read_timeout_seconds,
        sampling_callback=sampling_callback,
        list_roots_callback=list_roots_callback,
        logging_callback=logging_callback,
        message_handler=message_handler,
        client_info=client_info,
        elicitation_callback=elicitation_callback,
        extensions=extensions,
    ) as client:
        yield client
