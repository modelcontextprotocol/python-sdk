"""Companion examples for src/mcp/server/sse.py docstrings."""

from __future__ import annotations

from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from mcp.server.lowlevel.server import Server
from mcp.server.sse import SseServerTransport


def module_overview(app: Server[Any], port: int) -> None:
    # region module_overview
    # Create an SSE transport at an endpoint
    sse = SseServerTransport("/messages/")

    # Define handler functions
    async def handle_sse(request: Request) -> Response:
        async with sse.connect_sse(
            request.scope,
            request.receive,
            request._send,
        ) as streams:
            await app.run(streams[0], streams[1], app.create_initialization_options())
        # Return empty response to avoid NoneType error
        return Response()

    # Create Starlette routes for SSE and message handling
    routes = [
        Route("/sse", endpoint=handle_sse, methods=["GET"]),
        Mount("/messages/", app=sse.handle_post_message),
    ]

    # Create and run Starlette app
    starlette_app = Starlette(routes=routes)
    uvicorn.run(starlette_app, host="127.0.0.1", port=port)
    # endregion module_overview
