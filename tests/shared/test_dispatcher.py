"""Tests for the Dispatcher abstraction beneath BaseSession."""

from __future__ import annotations

from typing import Any

import anyio
import pytest

from mcp.client.session import ClientSession
from mcp.server.mcpserver import MCPServer
from mcp.shared.dispatcher import (
    JSONRPCDispatcher,
    OnErrorFn,
    OnNotificationFn,
    OnRequestFn,
)
from mcp.shared.memory import create_client_server_memory_streams
from mcp.shared.message import MessageMetadata
from mcp.types import ErrorData, RequestId

pytestmark = pytest.mark.anyio


class SpyDispatcher:
    """A custom Dispatcher that wraps JSONRPCDispatcher and records traffic.

    This is the shape a real non-JSON-RPC dispatcher (gRPC, CBOR, etc.) would
    take: satisfy the Dispatcher Protocol structurally, deal in MCP-level dicts.
    Wrapping JSONRPCDispatcher here lets us assert the session never bypasses us
    while still talking to a real server on the other end.
    """

    def __init__(self, inner: JSONRPCDispatcher) -> None:
        self._inner = inner
        self.sent_requests: list[dict[str, Any]] = []
        self.sent_notifications: list[dict[str, Any]] = []

    def set_handlers(self, on_request: OnRequestFn, on_notification: OnNotificationFn, on_error: OnErrorFn) -> None:
        self._inner.set_handlers(on_request, on_notification, on_error)

    async def run(self) -> None:
        await self._inner.run()

    async def send_request(
        self,
        request_id: RequestId,
        request: dict[str, Any],
        metadata: MessageMetadata = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        self.sent_requests.append(request)
        return await self._inner.send_request(request_id, request, metadata, timeout)

    async def send_notification(
        self, notification: dict[str, Any], related_request_id: RequestId | None = None
    ) -> None:
        self.sent_notifications.append(notification)
        await self._inner.send_notification(notification, related_request_id)

    async def send_response(self, request_id: RequestId, response: dict[str, Any] | ErrorData) -> None:
        await self._inner.send_response(request_id, response)  # pragma: no cover


async def test_client_session_accepts_custom_dispatcher():
    """ClientSession round-trips through a custom dispatcher end-to-end."""
    app = MCPServer("test")

    @app.tool()
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams

        # The spy wraps a real JSON-RPC dispatcher so the server side works unchanged.
        # What matters is that ClientSession has no idea it isn't the default.
        inner = JSONRPCDispatcher(client_read, client_write, response_routers=[])
        spy = SpyDispatcher(inner)

        async with anyio.create_task_group() as tg:
            server = app._lowlevel_server  # type: ignore[reportPrivateUsage]
            tg.start_soon(lambda: server.run(server_read, server_write, server.create_initialization_options()))

            async with ClientSession(dispatcher=spy) as session:
                await session.initialize()
                result = await session.call_tool("greet", {"name": "world"})
                assert result.content[0].text == "Hello, world!"  # type: ignore[union-attr]

            tg.cancel_scope.cancel()

    # Initialize + call_tool + list_tools (output-schema refresh after the call).
    assert [r["method"] for r in spy.sent_requests] == ["initialize", "tools/call", "tools/list"]
    # InitializedNotification.
    assert [n["method"] for n in spy.sent_notifications] == ["notifications/initialized"]


async def test_base_session_requires_streams_or_dispatcher():
    with pytest.raises(TypeError, match="either dispatcher or both"):
        ClientSession()
