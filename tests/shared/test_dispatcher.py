"""Tests for the Dispatcher abstraction beneath BaseSession."""

from __future__ import annotations

from typing import Any

import pytest

from mcp.client._memory import InMemoryTransport
from mcp.client.session import ClientSession
from mcp.server.mcpserver import Context, MCPServer
from mcp.shared._context import RequestContext
from mcp.shared.dispatcher import (
    JSONRPCDispatcher,
    OnErrorFn,
    OnNotificationFn,
    OnRequestFn,
)
from mcp.shared.message import MessageMetadata
from mcp.types import (
    CreateMessageRequestParams,
    CreateMessageResult,
    ErrorData,
    RequestId,
    SamplingMessage,
    TextContent,
)

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
        self.sent_responses: list[dict[str, Any] | ErrorData] = []

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
        self.sent_responses.append(response)
        await self._inner.send_response(request_id, response)


async def test_client_session_accepts_custom_dispatcher():
    """ClientSession round-trips through a custom dispatcher end-to-end, including
    a server-initiated request (sampling) so all five dispatcher methods fire."""
    app = MCPServer("test")

    @app.tool()
    async def ask(question: str, ctx: Context) -> str:
        answer = await ctx.session.create_message(
            messages=[SamplingMessage(role="user", content=TextContent(type="text", text=question))],
            max_tokens=10,
        )
        assert isinstance(answer.content, TextContent)
        return answer.content.text

    async def sampling_callback(
        context: RequestContext[ClientSession], params: CreateMessageRequestParams
    ) -> CreateMessageResult:
        return CreateMessageResult(
            role="assistant",
            content=TextContent(type="text", text="42"),
            model="test",
            stop_reason="endTurn",
        )

    # InMemoryTransport runs the server for us and yields client-side streams —
    # we intercept those streams and feed them through a custom dispatcher.
    async with InMemoryTransport(app) as (client_read, client_write):
        inner = JSONRPCDispatcher(client_read, client_write, response_routers=[])
        spy = SpyDispatcher(inner)

        async with ClientSession(dispatcher=spy, sampling_callback=sampling_callback) as session:
            await session.initialize()
            result = await session.call_tool("ask", {"question": "meaning of life?"})
            content = result.content[0]
            assert isinstance(content, TextContent)
            assert content.text == "42"

    # initialize, tools/call (triggers sampling on the server), tools/list (schema refresh)
    assert [r["method"] for r in spy.sent_requests] == ["initialize", "tools/call", "tools/list"]
    assert [n["method"] for n in spy.sent_notifications] == ["notifications/initialized"]
    # The server's sampling/createMessage request hit us; our response went back through the spy.
    assert len(spy.sent_responses) == 1
    response = spy.sent_responses[0]
    assert isinstance(response, dict) and response["model"] == "test"


async def test_base_session_requires_streams_or_dispatcher():
    with pytest.raises(TypeError, match="either dispatcher or both"):
        ClientSession()
