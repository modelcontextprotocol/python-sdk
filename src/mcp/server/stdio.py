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

import json
import re
import sys
from contextlib import asynccontextmanager
from io import TextIOWrapper
from typing import Any, cast

import anyio
import anyio.lowlevel
import mcp_types as types

from mcp.shared._context_streams import create_context_streams
from mcp.shared.message import SessionMessage

_JSONRPC_ID_PATTERN = re.compile(r'"id"\s*:\s*(-?\d+|"[^"\\]*")')


def _request_id_from_raw_message(line: str) -> types.RequestId | None:
    try:
        raw_message: Any = json.loads(line)
    except Exception:
        raw_message = None

    if not isinstance(raw_message, dict):
        match = _JSONRPC_ID_PATTERN.search(line)
        if not match:
            return None

        raw_request_id = match.group(1)
        if raw_request_id.startswith('"'):
            return json.loads(raw_request_id)
        return int(raw_request_id)

    raw_message_dict = cast(dict[str, Any], raw_message)
    request_id = raw_message_dict.get("id")
    if isinstance(request_id, str) or type(request_id) is int:
        return request_id
    return None


def _error_response_from_parse_failure(line: str, exc: Exception) -> SessionMessage:
    request_id = _request_id_from_raw_message(line)
    message = str(exc)
    if "Invalid JSON" in message:
        code = types.PARSE_ERROR
        prefix = "Parse error"
    else:
        code = types.INVALID_REQUEST
        prefix = "Invalid request"

    return SessionMessage(
        types.JSONRPCError(
            jsonrpc="2.0",
            id=request_id,
            error=types.ErrorData(code=code, message=f"{prefix}: {message}"),
        )
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
                        error_response = _error_response_from_parse_failure(line, exc)
                        await write_stream.send(error_response)
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
