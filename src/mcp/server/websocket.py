import logging
from contextlib import asynccontextmanager

import anyio
from starlette.types import Receive, Scope, Send
from starlette.websockets import WebSocket

import mcp.types as types
from mcp.shared.session import (
    ReadStream,
    ReadStreamWriter,
    WriteStream,
    WriteStreamReader,
)
from mcp.types import MessageFrame

logger = logging.getLogger(__name__)


@asynccontextmanager
async def websocket_server(scope: Scope, receive: Receive, send: Send):
    """
    WebSocket server transport for MCP. This is an ASGI application, suitable to be
    used with a framework like Starlette and a server like Hypercorn.
    """

    websocket = WebSocket(scope, receive, send)
    await websocket.accept(subprotocol="mcp")

    read_stream: ReadStream
    read_stream_writer: ReadStreamWriter

    write_stream: WriteStream
    write_stream_reader: WriteStreamReader

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    async def ws_reader():
        try:
            async with read_stream_writer:
                async for message in websocket.iter_json():
                    try:
                        client_message = types.JSONRPCMessage.model_validate(message)
                    except Exception as exc:
                        await read_stream_writer.send(exc)
                        continue

                    await read_stream_writer.send(
                        MessageFrame(message=client_message, raw=message)
                    )
        except anyio.ClosedResourceError:
            await websocket.close()

    async def ws_writer():
        try:
            async with write_stream_reader:
                async for message in write_stream_reader:
                    obj = message.model_dump(
                        by_alias=True, mode="json", exclude_none=True
                    )
                    await websocket.send_json(obj)
        except anyio.ClosedResourceError:
            await websocket.close()

    async with anyio.create_task_group() as tg:
        tg.start_soon(ws_reader)
        tg.start_soon(ws_writer)
        yield (read_stream, write_stream)
