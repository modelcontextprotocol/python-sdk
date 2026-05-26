"""Transport-parametrized connection factories for the interaction suite.

The `connect` fixture (see conftest.py) hands tests one of these factories so the same test body
runs over each transport without naming any of them: the factory is a drop-in replacement for
constructing `Client(server, ...)` and yields the connected client. The HTTP factories drive the
server's real Starlette app through the in-process streaming bridge, so the full transport layer
(session ids, SSE encoding, session management) runs with no sockets, threads, or subprocesses.
"""

import gc
import warnings
from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Protocol

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from mcp.client.client import Client
from mcp.client.session import ElicitationFnT, ListRootsFnT, LoggingFnT, MessageHandlerFnT, SamplingFnT
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import Server
from mcp.server.mcpserver import MCPServer
from mcp.server.sse import SseServerTransport
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Implementation
from tests.interaction.transports._bridge import StreamingASGITransport

# The in-process app is mounted at this origin purely so URLs are well-formed; nothing listens here.
_BASE_URL = "http://127.0.0.1:8000"


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
) -> AsyncIterator[Client]:
    """Yield a Client connected to the server over the in-memory transport."""
    async with Client(
        server,
        read_timeout_seconds=read_timeout_seconds,
        sampling_callback=sampling_callback,
        list_roots_callback=list_roots_callback,
        logging_callback=logging_callback,
        message_handler=message_handler,
        client_info=client_info,
        elicitation_callback=elicitation_callback,
    ) as client:
        yield client


@asynccontextmanager
async def connect_over_streamable_http(
    server: Server | MCPServer,
    *,
    stateless_http: bool = False,
    json_response: bool = False,
    read_timeout_seconds: float | None = None,
    sampling_callback: SamplingFnT | None = None,
    list_roots_callback: ListRootsFnT | None = None,
    logging_callback: LoggingFnT | None = None,
    message_handler: MessageHandlerFnT | None = None,
    client_info: Implementation | None = None,
    elicitation_callback: ElicitationFnT | None = None,
) -> AsyncIterator[Client]:
    """Yield a Client connected to the server's streamable HTTP app, entirely in process.

    With the defaults this is the matrix leg (stateful sessions, SSE responses); the
    transport-specific tests pass `stateless_http` or `json_response` to select the other
    server modes.
    """
    # DNS-rebinding protection validates Host/Origin headers against a real network attack that
    # cannot exist for an in-process ASGI app; leaving it on would also pull the origin-validation
    # branch (deliberately uncovered in src) into coverage.
    app = server.streamable_http_app(
        stateless_http=stateless_http,
        json_response=json_response,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    async with server.session_manager.run():
        async with httpx.AsyncClient(transport=StreamingASGITransport(app), base_url=_BASE_URL) as http_client:
            transport = streamable_http_client(f"{_BASE_URL}/mcp", http_client=http_client)
            async with Client(
                transport,
                read_timeout_seconds=read_timeout_seconds,
                sampling_callback=sampling_callback,
                list_roots_callback=list_roots_callback,
                logging_callback=logging_callback,
                message_handler=message_handler,
                client_info=client_info,
                elicitation_callback=elicitation_callback,
            ) as client:
                yield client


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
) -> AsyncIterator[Client]:
    """Yield a Client connected to the server's legacy SSE transport, entirely in process."""
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
            base_url=_BASE_URL,
            headers=headers,
            timeout=timeout,
            auth=auth,
        )

    transport = sse_client(f"{_BASE_URL}/sse", httpx_client_factory=httpx_client_factory)
    try:
        async with Client(
            transport,
            read_timeout_seconds=read_timeout_seconds,
            sampling_callback=sampling_callback,
            list_roots_callback=list_roots_callback,
            logging_callback=logging_callback,
            message_handler=message_handler,
            client_info=client_info,
            elicitation_callback=elicitation_callback,
        ) as client:
            yield client
    finally:
        # SseServerTransport.connect_sse hands its internal SSE-chunk receive stream to
        # sse_starlette's EventSourceResponse, which never closes it when its task group is
        # cancelled on disconnect (see notes/findings.md). Collect the orphan here so its
        # ResourceWarning fires deterministically inside this fixture instead of at an
        # arbitrary later GC.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ResourceWarning)
            gc.collect()
