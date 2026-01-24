"""MCP V2 Starlette Adapter - Thin wrapper around StreamableHTTPHandler.

This is the only file with a Starlette dependency. It converts HTTP
requests/responses to and from the framework-agnostic StreamableHTTPHandler.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any  # noqa: F401

import anyio
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from mcp_v2.runner import Lifespan, ServerRunner
from mcp_v2.server import LowLevelServer
from mcp_v2.transport.httphandler import AcceptedResponse, JSONResult, SSEStream, StreamableHTTPHandler
from mcp_v2.types.json_rpc import JSONRPCMessageAdapter


def _format_sse_event(data: str, event_id: str | None = None) -> str:
    """Format a single SSE event."""
    lines: list[str] = []
    if event_id is not None:
        lines.append(f"id: {event_id}")
    lines.append("event: message")
    lines.append(f"data: {data}")
    lines.append("")
    lines.append("")
    return "\n".join(lines)


def create_starlette_app(
    server: LowLevelServer,
    *,
    lifespan: Lifespan | None = None,
) -> Starlette:
    """Create a Starlette ASGI app from a LowLevelServer.

    Usage:
        server = LowLevelServer(name="my-server", version="1.0")

        @server.request_handler("tools/list")
        async def list_tools(ctx, request):
            return ListToolsResult(tools=[...])

        app = create_starlette_app(server)
        uvicorn.run(app, host="0.0.0.0", port=8000)
    """

    @asynccontextmanager
    async def app_lifespan(app: Starlette) -> AsyncIterator[None]:
        runner = ServerRunner(server, lifespan=lifespan)
        async with runner.run() as running:
            async with anyio.create_task_group() as tg:
                app.state.handler = StreamableHTTPHandler(running, tg)
                yield

    async def handle_post(request: Request) -> Response:
        handler: StreamableHTTPHandler = request.app.state.handler
        session_id = request.headers.get("mcp-session-id")

        body = await request.json()
        message = JSONRPCMessageAdapter.validate_python(body)

        result = await handler.handle_post(session_id=session_id, message=message)

        match result:
            case AcceptedResponse():
                return Response(status_code=202)

            case JSONResult(body=response_body, session_id=sid):
                return JSONResponse(
                    content=response_body.model_dump(by_alias=True, exclude_none=True),
                    headers={"mcp-session-id": sid},
                )

            case SSEStream(first_event=first, event_stream=stream, session_id=sid):

                async def generate() -> AsyncIterator[str]:
                    data = first.message.model_dump_json(by_alias=True, exclude_none=True)
                    yield _format_sse_event(data, first.event_id)
                    async with stream:
                        async for event in stream:
                            event_data = event.message.model_dump_json(by_alias=True, exclude_none=True)
                            yield _format_sse_event(event_data, event.event_id)

                from starlette.responses import StreamingResponse

                return StreamingResponse(
                    generate(),
                    media_type="text/event-stream",
                    headers={
                        "mcp-session-id": sid,
                        "Cache-Control": "no-cache, no-transform",
                        "Connection": "keep-alive",
                    },
                )

        return Response(status_code=500)  # unreachable but satisfies type checker

    async def handle_delete(request: Request) -> Response:
        handler: StreamableHTTPHandler = request.app.state.handler
        session_id = request.headers.get("mcp-session-id")
        if not session_id:
            return Response(status_code=400)
        deleted = await handler.handle_delete(session_id)
        return Response(status_code=200 if deleted else 404)

    return Starlette(
        lifespan=app_lifespan,
        routes=[
            Route("/mcp", handle_post, methods=["POST"]),
            Route("/mcp", handle_delete, methods=["DELETE"]),
        ],
    )
