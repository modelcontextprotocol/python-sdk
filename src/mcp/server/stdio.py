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
import mcp_types as types
import pydantic_core

from mcp.shared._context_streams import create_context_streams
from mcp.shared.message import SessionMessage, extract_raw_request_id


def _error_response_for_invalid_line(line: str) -> SessionMessage:
    """Build the JSON-RPC error response for a stdin line that failed message validation.

    Correlates the error with the originating request where possible: for lines that
    are valid JSON but an invalid JSON-RPC envelope, the request id is extracted
    best-effort from the raw payload (Invalid Request, -32600); for lines that are
    not valid JSON, a null id is used (Parse error, -32700), per the JSON-RPC 2.0
    specification.

    Args:
        line: The raw stdin line that failed to validate as a JSON-RPC message.

    Returns:
        A `SessionMessage` wrapping the `JSONRPCError` to write back to the client.
    """
    try:
        raw_message = pydantic_core.from_json(line)
    except ValueError:
        request_id = None
        error = types.ErrorData(code=types.PARSE_ERROR, message="Parse error")
    else:
        request_id = extract_raw_request_id(raw_message)
        error = types.ErrorData(code=types.INVALID_REQUEST, message="Invalid Request")
    return SessionMessage(types.JSONRPCError(jsonrpc="2.0", id=request_id, error=error))


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
                        try:
                            await write_stream.send(_error_response_for_invalid_line(line))
                        except anyio.ClosedResourceError:
                            # The server side already closed the write stream; the
                            # error response cannot be delivered, but the exception
                            # below still surfaces the bad line in-stream.
                            await anyio.lowlevel.checkpoint()
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
