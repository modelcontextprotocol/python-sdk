"""MCP V2 Runner - ServerRunner and RunningServer.

The runner bridges the LowLevelServer (pure dispatch) with transports.
It manages lifecycle (lifespan), handles the init handshake, and dispatches
messages to the server.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any, TypeVar

from mcp_v2.context import RequestContext, ResponseSink
from mcp_v2.server import LowLevelServer
from mcp_v2.session import SessionInfo
from mcp_v2.types.base import LATEST_PROTOCOL_VERSION
from mcp_v2.types.common import ServerCapabilities
from mcp_v2.types.initialize import InitializeRequestParams, InitializeResult
from mcp_v2.types.json_rpc import (
    JSONRPCMessage,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResultResponse,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

Lifespan = Callable[[LowLevelServer], AbstractAsyncContextManager[Any]]


@asynccontextmanager
async def _default_lifespan(server: LowLevelServer) -> AsyncIterator[dict[str, Any]]:
    yield {}


class ServerRunner:
    """Manages lifecycle and produces a RunningServer.

    Usage:
        runner = ServerRunner(server, lifespan=my_lifespan)
        async with runner.run() as running:
            # Use running.handle_message() with your transport
            ...
    """

    def __init__(self, server: LowLevelServer, *, lifespan: Lifespan | None = None) -> None:
        self.server = server
        self._lifespan = lifespan or _default_lifespan

    @asynccontextmanager
    async def run(self) -> AsyncIterator[RunningServer]:
        """Enter server lifespan once, yield a running server."""
        async with self._lifespan(self.server) as server_state:
            yield RunningServer(self.server, server_state)


class RunningServer:
    """A server with active lifespan, ready to handle requests.

    Handles the init handshake internally — the LowLevelServer never sees
    'initialize' as a request. It's protocol machinery, not application logic.
    """

    def __init__(self, server: LowLevelServer, server_state: Any) -> None:
        self._server = server
        self._server_state = server_state

    async def handle_message(
        self,
        sink: ResponseSink,
        message: JSONRPCMessage,
        *,
        session: SessionInfo | None = None,
    ) -> SessionInfo | None:
        """Dispatch a single message. Returns SessionInfo if this was an init handshake.

        For init requests: handles the handshake, responds via sink, returns new SessionInfo.
        For regular requests: dispatches to server, responds via sink, returns None.
        For notifications: dispatches to server, returns None.
        """
        if isinstance(message, JSONRPCRequest):
            if message.method == "initialize":
                return await self._handle_initialize(sink, message)

            ctx = RequestContext(
                server_state=self._server_state,
                session=session,
                request_id=message.id,
                _sink=sink,
            )
            response = await self._server.dispatch_request(ctx, message)
            await sink.send_result(response)
            return None

        if isinstance(message, JSONRPCNotification):
            if message.method == "notifications/initialized":
                # Ack the initialized notification — no-op
                return None
            ctx = RequestContext(
                server_state=self._server_state,
                session=session,
                request_id="notification",
                _sink=sink,
            )
            await self._server.dispatch_notification(ctx, message)
            return None

        # Responses from client (for server→client requests) would be routed
        # by the transport layer, not here. If we get one here, ignore it.
        return None

    async def _handle_initialize(self, sink: ResponseSink, request: JSONRPCRequest) -> SessionInfo:
        """Handle the initialize handshake. Returns the new SessionInfo."""
        params = InitializeRequestParams.model_validate(request.params)

        # Negotiate protocol version
        protocol_version = LATEST_PROTOCOL_VERSION

        capabilities = self._server.get_capabilities()

        result = InitializeResult.model_validate(
            {
                "protocolVersion": protocol_version,
                "capabilities": capabilities.model_dump(by_alias=True, exclude_none=True),
                "serverInfo": {"name": self._server.name, "version": self._server.version},
            }
        )

        response = JSONRPCResultResponse(
            id=request.id,
            result=result.model_dump(by_alias=True, exclude_none=True),
        )
        await sink.send_result(response)

        session_info = SessionInfo(
            client_info=params.client_info,
            client_capabilities=params.capabilities,
            protocol_version=protocol_version,
        )
        return session_info

    @property
    def capabilities(self) -> ServerCapabilities:
        return self._server.get_capabilities()

    @property
    def server_state(self) -> Any:
        return self._server_state
