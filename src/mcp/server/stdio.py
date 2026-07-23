"""Stdio Server Transport Module

This module provides functionality for creating an stdio-based transport layer
that can be used to communicate with an MCP client through standard input/output
streams.

Example:
    ```python
    async def run_server():
        async with stdio_server() as (read_stream, write_stream):
            # read_stream contains incoming JSONRPCMessages from stdin
            # write_stream allows sending JSONRPCMessages to stdout
            server = await create_my_server()
            await server.run(read_stream, write_stream)

    anyio.run(run_server)
    ```
"""

import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from io import TextIOWrapper

import anyio
import anyio.abc
import anyio.lowlevel
import mcp_types as types
from anyio.streams.buffered import BufferedByteReceiveStream

from mcp.shared._context_streams import ContextReceiveStream, ContextSendStream, create_context_streams
from mcp.shared.message import SessionMessage

__all__ = ["newline_json_transport", "stdio_server"]

_MAX_FRAME_BYTES = 64 * 1024 * 1024
"""Upper bound on one newline-delimited frame; a longer frame ends the read side."""


@asynccontextmanager
async def stdio_server(stdin: anyio.AsyncFile[str] | None = None, stdout: anyio.AsyncFile[str] | None = None):
    """Server transport for stdio: this communicates with an MCP client by reading
    from the current process' stdin and writing to stdout.
    """
    # Purposely not using context managers for these, as we don't want to close
    # standard process handles. Encoding of stdin/stdout as text streams on
    # python is platform-dependent (Windows is particularly problematic), so we
    # re-wrap the underlying binary stream to ensure UTF-8.
    if not stdin:
        stdin = anyio.wrap_file(TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="replace"))
    if not stdout:
        stdout = anyio.wrap_file(TextIOWrapper(sys.stdout.buffer, encoding="utf-8"))

    read_stream_writer, read_stream = create_context_streams[SessionMessage | Exception](0)
    write_stream, write_stream_reader = create_context_streams[SessionMessage](0)

    async def stdin_reader():
        try:
            async with read_stream_writer:
                async for line in stdin:
                    try:
                        message = types.jsonrpc_message_adapter.validate_json(line, by_name=False)
                    except Exception as exc:
                        await read_stream_writer.send(exc)
                        continue

                    session_message = SessionMessage(message)
                    await read_stream_writer.send(session_message)
        except anyio.ClosedResourceError:  # pragma: no cover
            await anyio.lowlevel.checkpoint()

    async def stdout_writer():
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    json = session_message.message.model_dump_json(by_alias=True, exclude_unset=True)
                    await stdout.write(json + "\n")
                    await stdout.flush()
        except anyio.ClosedResourceError:  # pragma: no cover
            await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as tg:
        tg.start_soon(stdin_reader)
        tg.start_soon(stdout_writer)
        yield read_stream, write_stream


@asynccontextmanager
async def newline_json_transport(
    stream: anyio.abc.ByteStream, *, max_frame_bytes: int = _MAX_FRAME_BYTES
) -> AsyncIterator[tuple[ContextReceiveStream[SessionMessage | Exception], ContextSendStream[SessionMessage]]]:
    """The stdio wire over any byte stream: newline-delimited JSON-RPC framing.

    Yields the `(read_stream, write_stream)` pair a server driver consumes,
    framing `stream` exactly as stdio frames its process handles:

    ```python
    async with newline_json_transport(sock) as (read_stream, write_stream):
        await server.run(read_stream, write_stream)
    ```

    A malformed line reaches the read stream as an exception item and the
    connection carries on; a frame longer than `max_frame_bytes` ends the read
    side. This framer never closes `stream` itself.
    """
    read_writer, read_stream = create_context_streams[SessionMessage | Exception](0)
    write_stream, write_reader = create_context_streams[SessionMessage](0)
    buffered = BufferedByteReceiveStream(stream)

    async def frame_reader() -> None:
        async with read_writer:
            while True:
                try:
                    line = await buffered.receive_until(b"\n", max_frame_bytes)
                except (anyio.EndOfStream, anyio.IncompleteRead, anyio.ClosedResourceError):
                    return  # peer closed: end of the inbound stream, the driver's EOF signal
                except anyio.DelimiterNotFound as exc:
                    # A frame overran the bound: the byte stream can no longer be resynchronised.
                    await read_writer.send(exc)
                    return
                try:
                    message = types.jsonrpc_message_adapter.validate_json(line, by_name=False)
                except Exception as exc:
                    await read_writer.send(exc)
                    continue
                await read_writer.send(SessionMessage(message))

    async def frame_writer() -> None:
        async with write_reader:
            async for session_message in write_reader:
                data = session_message.message.model_dump_json(by_alias=True, exclude_unset=True)
                try:
                    await stream.send(data.encode("utf-8") + b"\n")
                except (anyio.BrokenResourceError, anyio.ClosedResourceError):
                    return  # peer gone: outbound frames after this are undeliverable

    async with anyio.create_task_group() as tg:
        tg.start_soon(frame_reader)
        tg.start_soon(frame_writer)
        try:
            yield read_stream, write_stream
        finally:
            # The driver has returned: end both pumps.
            tg.cancel_scope.cancel()
