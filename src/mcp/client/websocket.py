import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import anyio
import websockets
from anyio.streams.memory import (
    MemoryObjectReceiveStream,
    MemoryObjectSendStream,
    create_memory_object_stream,
)

import mcp.types as types

logger = logging.getLogger(__name__)

@asynccontextmanager
async def websocket_client(
    url: str
) -> AsyncGenerator[
    tuple[
        MemoryObjectReceiveStream[types.JSONRPCMessage | Exception],
        MemoryObjectSendStream[types.JSONRPCMessage],
    ],
    None
]:
    """
    WebSocket client transport for MCP, symmetrical to the server version.

    Connects to 'url' using the 'mcp' subprotocol, then yields:
        (read_stream, write_stream)

    - read_stream: As you read from this stream, you'll receive either valid
      JSONRPCMessage objects or Exception objects (when validation fails).
    - write_stream: Write JSONRPCMessage objects to this stream to send them
      over the WebSocket to the server.
    """

    # Create two in-memory streams:
    # - One for incoming messages (read_stream_recv, written by ws_reader)
    # - One for outgoing messages (write_stream_send, read by ws_writer)
    read_stream_send, read_stream_recv = create_memory_object_stream(0)
    write_stream_send, write_stream_recv = create_memory_object_stream(0)

    # Connect using websockets, requesting the "mcp" subprotocol
    async with websockets.connect(url, subprotocols=["mcp"]) as ws:
        # Optional check to ensure the server actually accepted "mcp"
        if ws.subprotocol != "mcp":
            raise ValueError(
                f"Server did not accept subprotocol 'mcp'. Actual subprotocol: {ws.subprotocol}"
            )

        async def ws_reader():
            """
            Reads text messages from the WebSocket, parses them as JSON-RPC messages,
            and sends them into read_stream_send.
            """
            try:
                async for raw_text in ws:
                    try:
                        data = json.loads(raw_text)
                        message = types.JSONRPCMessage.model_validate(data)
                        await read_stream_send.send(message)
                    except Exception as exc:
                        # If JSON parse or model validation fails, send the exception
                        await read_stream_send.send(exc)
            except (anyio.ClosedResourceError, websockets.ConnectionClosed):
                pass
            finally:
                # Ensure our read stream is closed
                await read_stream_send.aclose()

        async def ws_writer():
            """
            Reads JSON-RPC messages from write_stream_recv and sends them to the server.
            """
            try:
                async for message in write_stream_recv:
                    # Convert to a dict, then to JSON
                    msg_dict = message.model_dump(
                        by_alias=True, mode="json", exclude_none=True
                    )
                    await ws.send(json.dumps(msg_dict))
            except (anyio.ClosedResourceError, websockets.ConnectionClosed):
                pass
            finally:
                # Ensure our write stream is closed
                await write_stream_recv.aclose()

        async with anyio.create_task_group() as tg:
            # Start reader and writer tasks
            tg.start_soon(ws_reader)
            tg.start_soon(ws_writer)

            # Yield the receive/send streams
            yield (read_stream_recv, write_stream_send)

            # Once the caller's 'async with' block exits, we shut down
            tg.cancel_scope.cancel()
