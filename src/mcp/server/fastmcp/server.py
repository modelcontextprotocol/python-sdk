from __future__ import annotations

from typing import Any

from mcp.server.mcpserver.server import MCPServer
from mcp.server.streamable_http_manager import StreamableHTTPASGIApp as _StreamableHTTPASGIApp

StreamableHTTPASGIApp = _StreamableHTTPASGIApp


class FastMCP:
    """Small compatibility wrapper used by examples.

    This repository's public server implementation is `mcp.server.mcpserver.server.MCPServer`.
    Some examples use a `FastMCP` naming convention and expect an attribute called `_mcp_server`
    that can be passed into `StreamableHTTPSessionManager`.
    """

    def __init__(
        self,
        *,
        name: str,
        instructions: str = "",
        host: str | None = None,
        port: int | None = None,
        auth: Any = None,
        **kwargs: Any,
    ) -> None:
        # host/port are kept for the example interface; `MCPServer` itself does not need them.
        self.host = host
        self.port = port

        self._server = MCPServer(
            name=name,
            instructions=instructions,
            auth=auth,
            **kwargs,
        )

        # Examples expect this to be the low-level Server instance.
        self._mcp_server = getattr(self._server, "_lowlevel_server")

    def tool(self, *args: Any, **kwargs: Any):
        return self._server.tool(*args, **kwargs)
