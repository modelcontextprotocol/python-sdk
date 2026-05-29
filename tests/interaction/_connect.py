"""Transport-parametrized connection factories for the interaction suite.

The `connect` fixture (see conftest.py) hands tests one of these factories so the same test body
runs over each transport without naming any of them: the factory yields an initialized
`ClientSession` connected to the given server. v1 has no high-level `Client` class —
`ClientSession` *is* the client. The HTTP factories drive the server's real Starlette app through
the in-process streaming bridge, so the full transport layer (session ids, SSE encoding, session
management) runs with no sockets, threads, or subprocesses.
"""

from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from datetime import timedelta
from typing import Any, Protocol

import httpx
from httpx_sse import ServerSentEvent, aconnect_sse
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route
from starlette.types import Receive, Scope, Send

from mcp.client.session import ClientSession, ElicitationFnT, ListRootsFnT, LoggingFnT, MessageHandlerFnT, SamplingFnT
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server
from mcp.server.auth.middleware.auth_context import AuthContextMiddleware
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.provider import OAuthAuthorizationServerProvider, ProviderTokenVerifier, TokenVerifier
from mcp.server.auth.routes import build_resource_metadata_url, create_auth_routes, create_protected_resource_routes
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
from mcp.server.streamable_http import EventStore
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    ClientCapabilities,
    Implementation,
    InitializeRequestParams,
    JSONRPCMessage,
    JSONRPCRequest,
    JSONRPCResponse,
)
from tests.interaction.transports._bridge import StreamingASGITransport

# The in-process app is mounted at this origin purely so URLs are well-formed; nothing listens here.
BASE_URL = "http://127.0.0.1:8000"

# DNS-rebinding protection validates Host/Origin headers against a real network attack that cannot
# exist for an in-process ASGI app, so the in-process factories disable it; tests that exercise the
# protection itself pass explicit settings (or transport_security=None to get the localhost
# auto-enable behaviour).
NO_DNS_REBINDING_PROTECTION = TransportSecuritySettings(enable_dns_rebinding_protection=False)


class StreamableHTTPASGIApp:
    """Thin ASGI wrapper around `StreamableHTTPSessionManager.handle_request`.

    Starlette's `Route(path, endpoint=...)` treats a *class instance* as a raw ASGI callable
    (matching all HTTP verbs), whereas a coroutine function is wrapped via `request_response`
    and defaults to GET/HEAD only. v1's `FastMCP.streamable_http_app()` relies on this same
    distinction; we inline the wrapper here rather than deep-importing the (non-`__all__`)
    `mcp.server.fastmcp.server.StreamableHTTPASGIApp`.
    """

    def __init__(self, session_manager: StreamableHTTPSessionManager) -> None:
        self.session_manager = session_manager

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        await self.session_manager.handle_request(scope, receive, send)


def _lowlevel(server: Server[Any] | FastMCP) -> Server[Any]:
    """Return the lowlevel `Server` for either flavour.

    Reaching `FastMCP._mcp_server` is the v1 idiom — `mcp.shared.memory` itself does exactly
    this (with the same `# type: ignore`).
    """
    return server._mcp_server if isinstance(server, FastMCP) else server  # type: ignore[reportPrivateUsage]


class Connect(Protocol):
    """Connect a `ClientSession` to a server over the transport selected by the `connect` fixture.

    Accepts the same callback keyword arguments as `ClientSession` and yields the connected,
    initialized session.
    """

    def __call__(
        self,
        server: Server[Any] | FastMCP,
        *,
        read_timeout_seconds: timedelta | None = None,
        sampling_callback: SamplingFnT | None = None,
        elicitation_callback: ElicitationFnT | None = None,
        list_roots_callback: ListRootsFnT | None = None,
        logging_callback: LoggingFnT | None = None,
        message_handler: MessageHandlerFnT | None = None,
        client_info: Implementation | None = None,
    ) -> AbstractAsyncContextManager[ClientSession]: ...


@asynccontextmanager
async def connect_in_memory(
    server: Server[Any] | FastMCP,
    *,
    read_timeout_seconds: timedelta | None = None,
    sampling_callback: SamplingFnT | None = None,
    elicitation_callback: ElicitationFnT | None = None,
    list_roots_callback: ListRootsFnT | None = None,
    logging_callback: LoggingFnT | None = None,
    message_handler: MessageHandlerFnT | None = None,
    client_info: Implementation | None = None,
) -> AsyncIterator[ClientSession]:
    """Yield an initialized `ClientSession` connected to the server over the in-memory transport.

    This is exactly `mcp.shared.memory.create_connected_server_and_client_session` — the
    canonical v1 in-memory idiom — re-exported under the suite's `Connect` shape so the
    transport matrix can parametrize over it.
    """
    async with create_connected_server_and_client_session(
        server,
        read_timeout_seconds=read_timeout_seconds,
        sampling_callback=sampling_callback,
        list_roots_callback=list_roots_callback,
        logging_callback=logging_callback,
        message_handler=message_handler,
        client_info=client_info,
        elicitation_callback=elicitation_callback,
    ) as session:
        yield session


def build_streamable_http_app(
    server: Server[Any] | FastMCP,
    *,
    stateless_http: bool = False,
    json_response: bool = False,
    event_store: EventStore | None = None,
    retry_interval: int | None = None,
    transport_security: TransportSecuritySettings | None = NO_DNS_REBINDING_PROTECTION,
    auth: AuthSettings | None = None,
    token_verifier: TokenVerifier | None = None,
    auth_server_provider: OAuthAuthorizationServerProvider[Any, Any, Any] | None = None,
) -> tuple[Starlette, StreamableHTTPSessionManager]:
    """Assemble a streamable-HTTP Starlette app for either server flavour.

    v1's lowlevel `Server` has no `streamable_http_app()`; this follows
    `FastMCP.streamable_http_app()` (`mcp/server/fastmcp/server.py`) so behaviour matches what a
    v1 user would get from `FastMCP(..., **knobs).streamable_http_app()`. Returns the live
    `StreamableHTTPSessionManager` alongside the app so the caller can enter `manager.run()`
    (the in-process bridge does not drive Starlette lifespan) and so tests can reach
    `manager._server_instances`.

    `/mcp` is mounted via `Route(path, endpoint=<class instance>)` with no `methods=`, exactly
    as FastMCP does — Starlette treats a class-instance endpoint as raw ASGI and matches all
    verbs, which is what the transport requires.

    Unlike `FastMCP.__init__`, this does not enforce `auth_server_provider` XOR
    `token_verifier`; the AS-handler tests pass both.
    """
    manager = StreamableHTTPSessionManager(
        app=_lowlevel(server),
        event_store=event_store,
        json_response=json_response,
        stateless=stateless_http,
        security_settings=transport_security,
        retry_interval=retry_interval,
    )
    asgi = StreamableHTTPASGIApp(manager)

    # FastMCP derives a verifier from the provider at construction time when no explicit verifier
    # is given (mcp/server/fastmcp/server.py:230); the harness has no construction step, so the
    # same derivation runs here so the gating below sees the same verifier FastMCP would.
    verifier = token_verifier
    if auth_server_provider is not None and token_verifier is None:
        verifier = ProviderTokenVerifier(auth_server_provider)

    routes: list[Route] = []
    middleware: list[Middleware] = []
    required_scopes: list[str] = []

    if auth is not None:
        required_scopes = auth.required_scopes or []
        if verifier is not None:
            middleware = [
                Middleware(AuthenticationMiddleware, backend=BearerAuthBackend(verifier)),
                Middleware(AuthContextMiddleware),
            ]
        if auth_server_provider is not None:
            routes.extend(
                create_auth_routes(
                    provider=auth_server_provider,
                    issuer_url=auth.issuer_url,
                    service_documentation_url=auth.service_documentation_url,
                    client_registration_options=auth.client_registration_options,
                    revocation_options=auth.revocation_options,
                )
            )

    if verifier is not None:
        resource_metadata_url = (
            build_resource_metadata_url(auth.resource_server_url)
            if auth is not None and auth.resource_server_url
            else None
        )
        routes.append(Route("/mcp", endpoint=RequireAuthMiddleware(asgi, required_scopes, resource_metadata_url)))
    else:
        routes.append(Route("/mcp", endpoint=asgi))

    if auth is not None and auth.resource_server_url:
        routes.extend(
            create_protected_resource_routes(
                resource_url=auth.resource_server_url,
                authorization_servers=[auth.issuer_url],
                scopes_supported=auth.required_scopes,
            )
        )

    return Starlette(routes=routes, middleware=middleware), manager


@asynccontextmanager
async def connect_over_streamable_http(
    server: Server[Any] | FastMCP,
    *,
    stateless_http: bool = False,
    json_response: bool = False,
    event_store: EventStore | None = None,
    retry_interval: int | None = None,
    read_timeout_seconds: timedelta | None = None,
    sampling_callback: SamplingFnT | None = None,
    elicitation_callback: ElicitationFnT | None = None,
    list_roots_callback: ListRootsFnT | None = None,
    logging_callback: LoggingFnT | None = None,
    message_handler: MessageHandlerFnT | None = None,
    client_info: Implementation | None = None,
) -> AsyncIterator[ClientSession]:
    """Yield an initialized `ClientSession` over the server's streamable HTTP app, entirely in process.

    With the defaults this is the matrix leg (stateful sessions, SSE responses); the
    transport-specific tests pass `stateless_http` or `json_response` to select the other
    server modes, and the resumability tests pass an `event_store` (with `retry_interval=0` so
    the client's reconnection wait is a no-op).
    """
    app, manager = build_streamable_http_app(
        server,
        stateless_http=stateless_http,
        json_response=json_response,
        event_store=event_store,
        retry_interval=retry_interval,
    )
    async with (
        manager.run(),
        httpx.AsyncClient(transport=StreamingASGITransport(app), base_url=BASE_URL) as http_client,
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read, write, _get_session_id),
        ClientSession(
            read,
            write,
            read_timeout_seconds=read_timeout_seconds,
            sampling_callback=sampling_callback,
            list_roots_callback=list_roots_callback,
            logging_callback=logging_callback,
            message_handler=message_handler,
            client_info=client_info,
            elicitation_callback=elicitation_callback,
        ) as session,
    ):
        await session.initialize()
        yield session


@asynccontextmanager
async def mounted_app(
    server: Server[Any] | FastMCP,
    *,
    stateless_http: bool = False,
    json_response: bool = False,
    event_store: EventStore | None = None,
    retry_interval: int | None = None,
    transport_security: TransportSecuritySettings | None = NO_DNS_REBINDING_PROTECTION,
    on_request: Callable[[httpx.Request], Awaitable[None]] | None = None,
    headers: dict[str, str] | None = None,
    auth: AuthSettings | None = None,
    token_verifier: TokenVerifier | None = None,
    auth_server_provider: OAuthAuthorizationServerProvider[Any, Any, Any] | None = None,
) -> AsyncIterator[tuple[httpx.AsyncClient, StreamableHTTPSessionManager]]:
    """Mount the server's streamable HTTP app on the in-process bridge and yield an httpx client.

    Yields the httpx client (rooted at the in-process origin) and the live session manager. Tests
    use this in two ways: for raw-httpx assertions (status codes, headers, SSE bytes) the test
    speaks HTTP through the yielded client directly; for client-driven assertions the test wraps
    that client in `client_via_http(http)`, which lets several `ClientSession`s share the one
    mounted session manager. `on_request` records every outgoing HTTP request before it leaves the
    yielded client.

    DNS-rebinding protection is disabled by default; pass explicit settings (or `None` for the
    localhost auto-enable behaviour) to test the protection itself.
    """
    app, manager = build_streamable_http_app(
        server,
        stateless_http=stateless_http,
        json_response=json_response,
        event_store=event_store,
        retry_interval=retry_interval,
        transport_security=transport_security,
        auth=auth,
        token_verifier=token_verifier,
        auth_server_provider=auth_server_provider,
    )
    event_hooks = {"request": [on_request]} if on_request is not None else None
    async with (
        manager.run(),
        httpx.AsyncClient(
            transport=StreamingASGITransport(app), base_url=BASE_URL, event_hooks=event_hooks, headers=headers
        ) as http_client,
    ):
        yield http_client, manager


@asynccontextmanager
async def client_via_http(
    http_client: httpx.AsyncClient,
    *,
    logging_callback: LoggingFnT | None = None,
    message_handler: MessageHandlerFnT | None = None,
    elicitation_callback: ElicitationFnT | None = None,
) -> AsyncIterator[ClientSession]:
    """Connect a `ClientSession` over an already-mounted streamable HTTP app.

    Use with `mounted_app(...)` so several `ClientSession`s share the one session manager, or
    so a client-driven assertion can sit alongside raw-httpx assertions in the same test. The
    underlying `httpx.AsyncClient` is left open when the session exits.
    """
    async with (
        streamable_http_client(f"{BASE_URL}/mcp", http_client=http_client) as (read, write, _get_session_id),
        ClientSession(
            read,
            write,
            logging_callback=logging_callback,
            message_handler=message_handler,
            elicitation_callback=elicitation_callback,
        ) as session,
    ):
        await session.initialize()
        yield session


def parse_sse_messages(events: Iterable[ServerSentEvent]) -> list[JSONRPCMessage]:
    """Decode SSE events into JSON-RPC messages, skipping priming events that carry no data."""
    return [JSONRPCMessage.model_validate_json(event.data) for event in events if event.data]


async def post_jsonrpc(
    http: httpx.AsyncClient, body: dict[str, object], *, session_id: str | None = None
) -> tuple[httpx.Response, list[JSONRPCMessage]]:
    """POST a JSON-RPC body and read its SSE response stream to completion.

    Returns the HTTP response (for header/status assertions) and the parsed JSON-RPC messages
    that arrived on the response's SSE stream. Only meaningful for requests the server answers
    with `text/event-stream`; for error responses or 202 notification acknowledgements, use
    `httpx.AsyncClient.post` directly and assert on the response.
    """
    async with aconnect_sse(http, "POST", "/mcp", json=body, headers=base_headers(session_id=session_id)) as source:
        events = [event async for event in source.aiter_sse()]
    return source.response, parse_sse_messages(events)


def base_headers(*, session_id: str | None = None) -> dict[str, str]:
    """Standard request headers for raw-httpx streamable-HTTP tests.

    Every well-formed request carries these (Accept covering both response representations,
    Content-Type for POST bodies, MCP-Protocol-Version at the latest revision, and the session
    ID once one exists), so a test that wants to assert a specific rejection only varies the one
    header under test.
    """
    headers = {
        "accept": "application/json, text/event-stream",
        "content-type": "application/json",
        "mcp-protocol-version": LATEST_PROTOCOL_VERSION,
    }
    if session_id is not None:
        headers["mcp-session-id"] = session_id
    return headers


def initialize_body(request_id: int = 1) -> dict[str, object]:
    """A wire-level initialize JSON-RPC request body, exactly as an SDK client would send it."""
    params = InitializeRequestParams(
        protocolVersion=LATEST_PROTOCOL_VERSION,
        capabilities=ClientCapabilities(),
        clientInfo=Implementation(name="raw", version="0.0.0"),
    )
    return JSONRPCRequest(
        jsonrpc="2.0", id=request_id, method="initialize", params=params.model_dump(by_alias=True, exclude_none=True)
    ).model_dump(by_alias=True, exclude_none=True)


async def initialize_via_http(http: httpx.AsyncClient) -> str:
    """Perform the initialize handshake over a raw `httpx.AsyncClient` and return the session ID.

    Validates the SSE response and sends the `notifications/initialized` follow-up, so the server
    is fully ready for subsequent feature requests when this returns.
    """
    async with aconnect_sse(http, "POST", "/mcp", json=initialize_body(), headers=base_headers()) as source:
        assert source.response.status_code == 200
        # An event-store-backed server opens the stream with a priming event (empty data); skip it.
        events = [event async for event in source.aiter_sse() if event.data]
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


def build_sse_app(server: Server[Any] | FastMCP) -> tuple[Starlette, SseServerTransport]:
    """Mount a server on a Starlette app exposing the legacy SSE transport at /sse and /messages/.

    `FastMCP.sse_app()` exists but does not expose the underlying `SseServerTransport`, which
    the SSE-specific tests need; building the app explicitly here gives both server flavours the
    same routing while keeping that handle.
    """
    sse = SseServerTransport("/messages/", security_settings=NO_DNS_REBINDING_PROTECTION)
    lowlevel = _lowlevel(server)

    async def handle_sse(request: Request) -> Response:
        async with sse.connect_sse(request.scope, request.receive, request._send) as (read, write):  # type: ignore[reportPrivateUsage]
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
    server: Server[Any] | FastMCP,
    *,
    read_timeout_seconds: timedelta | None = None,
    sampling_callback: SamplingFnT | None = None,
    elicitation_callback: ElicitationFnT | None = None,
    list_roots_callback: ListRootsFnT | None = None,
    logging_callback: LoggingFnT | None = None,
    message_handler: MessageHandlerFnT | None = None,
    client_info: Implementation | None = None,
) -> AsyncIterator[ClientSession]:
    """Yield an initialized `ClientSession` over the server's legacy SSE transport, entirely in process."""
    app, _ = build_sse_app(server)

    def httpx_client_factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        # The SSE server transport's connect_sse runs the entire MCP session inside the GET
        # request and only releases its streams after that request observes a disconnect, so the
        # bridge must let the application drain rather than cancelling at close.
        return httpx.AsyncClient(
            transport=StreamingASGITransport(app, cancel_on_close=False),
            base_url=BASE_URL,
            headers=headers,
            timeout=timeout,
            auth=auth,
        )

    async with (
        sse_client(f"{BASE_URL}/sse", httpx_client_factory=httpx_client_factory) as (read, write),
        ClientSession(
            read,
            write,
            read_timeout_seconds=read_timeout_seconds,
            sampling_callback=sampling_callback,
            list_roots_callback=list_roots_callback,
            logging_callback=logging_callback,
            message_handler=message_handler,
            client_info=client_info,
            elicitation_callback=elicitation_callback,
        ) as session,
    ):
        await session.initialize()
        yield session
