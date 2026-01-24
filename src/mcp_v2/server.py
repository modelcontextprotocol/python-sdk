"""MCP V2 LowLevelServer - Pure handler registry and dispatch.

No I/O, no lifecycle, no transport knowledge. Just dispatch.
The equivalent of an ASGI app — not a web server.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel

from mcp_v2.context import RequestContext
from mcp_v2.types.common import ServerCapabilities
from mcp_v2.types.json_rpc import (
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    ErrorData,
    JSONRPCErrorResponse,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    JSONRPCResultResponse,
)

logger = logging.getLogger(__name__)

RequestHandler = Callable[[RequestContext, JSONRPCRequest], Awaitable[Any]]
NotificationHandler = Callable[[RequestContext, JSONRPCNotification], Awaitable[None]]


class LowLevelServer:
    """Pure handler registry + dispatch. No run loop, no transport, no lifecycle.

    Usage:
        server = LowLevelServer(name="my-server", version="1.0")

        @server.request_handler("tools/list")
        async def list_tools(ctx: RequestContext, request: JSONRPCRequest):
            return ListToolsResult(tools=[...])

        @server.request_handler("tools/call")
        async def call_tool(ctx: RequestContext, request: JSONRPCRequest):
            params = CallToolRequestParams.model_validate(request.params)
            await ctx.send_notification("notifications/progress", {"progress": 0.5})
            return CallToolResult(content=[TextContent(text="done")])
    """

    def __init__(self, *, name: str, version: str) -> None:
        self.name = name
        self.version = version
        self._request_handlers: dict[str, RequestHandler] = {}
        self._notification_handlers: dict[str, NotificationHandler] = {}

    def request_handler(self, method: str) -> Callable[[RequestHandler], RequestHandler]:
        """Decorator to register a request handler for a given method."""

        def decorator(fn: RequestHandler) -> RequestHandler:
            self._request_handlers[method] = fn
            return fn

        return decorator

    def notification_handler(self, method: str) -> Callable[[NotificationHandler], NotificationHandler]:
        """Decorator to register a notification handler for a given method."""

        def decorator(fn: NotificationHandler) -> NotificationHandler:
            self._notification_handlers[method] = fn
            return fn

        return decorator

    async def dispatch_request(self, ctx: RequestContext, request: JSONRPCRequest) -> JSONRPCResponse:
        """Dispatch a request to the appropriate handler."""
        handler = self._request_handlers.get(request.method)
        if not handler:
            return JSONRPCErrorResponse(
                id=request.id,
                error=ErrorData(code=METHOD_NOT_FOUND, message=f"Method not found: {request.method}"),
            )
        try:
            result = await handler(ctx, request)
            # Handler can return a BaseModel (serialized) or a raw dict
            if isinstance(result, BaseModel):
                result_data = result.model_dump(by_alias=True, exclude_none=True)
            elif isinstance(result, dict):
                result_data = result
            else:
                result_data = {}
            return JSONRPCResultResponse(id=request.id, result=result_data)
        except Exception:
            logger.exception("Handler error for %s", request.method)
            return JSONRPCErrorResponse(
                id=request.id,
                error=ErrorData(code=INTERNAL_ERROR, message="Internal error"),
            )

    async def dispatch_notification(self, ctx: RequestContext, notification: JSONRPCNotification) -> None:
        """Dispatch a notification to the appropriate handler."""
        handler = self._notification_handlers.get(notification.method)
        if handler:
            try:
                await handler(ctx, notification)
            except Exception:
                logger.exception("Notification handler error for %s", notification.method)

    def get_capabilities(self) -> ServerCapabilities:
        """Derive capabilities from registered handlers."""
        caps = ServerCapabilities()
        if "tools/list" in self._request_handlers or "tools/call" in self._request_handlers:
            caps.tools = {}
        if "prompts/list" in self._request_handlers or "prompts/get" in self._request_handlers:
            caps.prompts = {}
        if "resources/list" in self._request_handlers or "resources/read" in self._request_handlers:
            caps.resources = {}
        if "logging/setLevel" in self._request_handlers:
            caps.logging = {}
        return caps
