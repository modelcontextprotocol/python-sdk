import logging
from contextlib import asynccontextmanager

import anyio
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pydantic_core import ValidationError
from starlette.types import Receive, Scope, Send
from starlette.websockets import WebSocket
from typing_extensions import deprecated

import mcp.types as types
from mcp.server.transport_security import TransportSecurityMiddleware, TransportSecuritySettings
from mcp.shared.message import SessionMessage

logger = logging.getLogger(__name__)


@deprecated(  # pragma: no cover
    "The WebSocket server transport is deprecated and will be removed in mcp 2.0. WebSocket was never part of"
    " the MCP specification; use the streamable HTTP transport instead."
)
@asynccontextmanager
async def websocket_server(
    scope: Scope,
    receive: Receive,
    send: Send,
    security_settings: TransportSecuritySettings | None = None,
):
    """
    WebSocket server transport for MCP. This is an ASGI application, suitable to be
    used with a framework like Starlette and a server like Hypercorn.

    Set `security_settings` to enable Host/Origin header validation before the
    handshake is accepted (same settings type as the SSE and Streamable HTTP
    transports). When validation fails this raises `ValueError` after rejecting
    the handshake.

    Deprecated: this transport will be removed in mcp 2.0. WebSocket was never
    part of the MCP specification; use the streamable HTTP transport instead.
    """

    websocket = WebSocket(scope, receive, send)

    security = TransportSecurityMiddleware(security_settings)
    error_response = await security.validate_request(websocket, is_post=False)
    if error_response is not None:
        # Reject the handshake; the ASGI server maps a pre-accept close to HTTP 403.
        await websocket.close()
        raise ValueError("Request validation failed")

    await websocket.accept(subprotocol="mcp")

    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception]
    read_stream_writer: MemoryObjectSendStream[SessionMessage | Exception]

    write_stream: MemoryObjectSendStream[SessionMessage]
    write_stream_reader: MemoryObjectReceiveStream[SessionMessage]

    read_stream_writer, read_stream = anyio.create_memory_object_stream(0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream(0)

    async def ws_reader():
        try:
            async with read_stream_writer:
                async for msg in websocket.iter_text():
                    try:
                        client_message = types.JSONRPCMessage.model_validate_json(msg)
                    except ValidationError as exc:
                        await read_stream_writer.send(exc)
                        continue

                    session_message = SessionMessage(client_message)
                    await read_stream_writer.send(session_message)
        except anyio.ClosedResourceError:
            await websocket.close()

    async def ws_writer():
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    obj = session_message.message.model_dump_json(by_alias=True, exclude_none=True)
                    await websocket.send_text(obj)
        except anyio.ClosedResourceError:
            await websocket.close()

    async with anyio.create_task_group() as tg:
        tg.start_soon(ws_reader)
        tg.start_soon(ws_writer)
        yield (read_stream, write_stream)
