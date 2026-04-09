from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import anyio
from pydantic_core import ValidationError
from starlette.types import Receive, Scope, Send
from starlette.websockets import WebSocket

from mcp import types
from mcp.shared._context_streams import create_context_streams
from mcp.shared.message import SessionMessage


@asynccontextmanager
async def websocket_server(
    scope: Scope, receive: Receive, send: Send
) -> AsyncGenerator[
    tuple[MemoryObjectReceiveStream[SessionMessage | Exception], MemoryObjectSendStream[SessionMessage]], None
]:
    """WebSocket server transport for MCP. This is an ASGI application, suitable for use
    with a framework like Starlette and a server like Hypercorn.
    """

    websocket = WebSocket(scope, receive, send)
    await websocket.accept(subprotocol="mcp")

    read_stream_writer, read_stream = create_context_streams[SessionMessage | Exception](0)
    write_stream, write_stream_reader = create_context_streams[SessionMessage](0)

    async def ws_reader() -> None:
        try:
            async with read_stream_writer:
                async for msg in websocket.iter_text():
                    try:
                        client_message = types.jsonrpc_message_adapter.validate_json(msg, by_name=False)
                    except ValidationError as exc:  # pragma: no cover
                        await read_stream_writer.send(exc)
                        continue

                    session_message = SessionMessage(client_message)
                    await read_stream_writer.send(session_message)
        except anyio.ClosedResourceError:  # pragma: no cover
            await websocket.close()

    async def ws_writer() -> None:
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    obj = session_message.message.model_dump_json(by_alias=True, exclude_unset=True)
                    await websocket.send_text(obj)
        except anyio.ClosedResourceError:  # pragma: no cover
            await websocket.close()

    async with anyio.create_task_group() as tg:
        tg.start_soon(ws_reader)
        tg.start_soon(ws_writer)
        yield (read_stream, write_stream)
