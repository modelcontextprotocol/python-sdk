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
            await server.run(read_stream, write_stream, init_options)

    anyio.run(run_server)
    ```
"""

import sys
from contextlib import asynccontextmanager
from io import TextIOWrapper

import anyio
import anyio.lowlevel
import pydantic_core

from mcp import types
from mcp.shared._context_streams import create_context_streams
from mcp.shared.message import SessionMessage
from mcp.types.jsonrpc import extract_request_id


def _invalid_request_error(line: str) -> types.JSONRPCError | None:
    """Build an Invalid Request error for an id-bearing line that failed envelope validation.

    Per JSON-RPC 2.0, a request that is valid JSON but not a valid request
    object gets a -32600 error response echoing the original request id, so
    the client can correlate the failure. Returns None when the line is not
    valid JSON (parse error, no response expected by existing consumers) or
    when no id can be detected (a malformed notification gets no response).
    """
    try:
        raw = pydantic_core.from_json(line)
    except ValueError:
        return None
    request_id = extract_request_id(raw)
    if request_id is None:
        return None
    return types.JSONRPCError(
        jsonrpc="2.0",
        id=request_id,
        error=types.ErrorData(code=types.INVALID_REQUEST, message="Invalid Request"),
    )


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
                        if (error := _invalid_request_error(line)) is not None:
                            await write_stream.send(SessionMessage(error))
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
