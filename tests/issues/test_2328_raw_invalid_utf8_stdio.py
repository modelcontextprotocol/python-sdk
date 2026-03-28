"""Regression test for issue #2328 - raw invalid UTF-8 over stdio."""

import io
from io import TextIOWrapper

import anyio
import pytest
from pydantic import AnyHttpUrl, TypeAdapter

from mcp.server.mcpserver import MCPServer
from mcp.server.stdio import stdio_server
from mcp.types import JSONRPCResponse, jsonrpc_message_adapter


@pytest.mark.anyio
async def test_raw_invalid_utf8_stdio_request_does_not_crash_server() -> None:
    mcp = MCPServer("test")

    @mcp.tool()
    async def fetch(url: str) -> str:
        # Delay validation so stdin can reach EOF and close the session write
        # stream before the tool returns its validation failure.
        await anyio.sleep(0.1)
        return str(TypeAdapter(AnyHttpUrl).validate_python(url))

    initialize = (
        b'{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": '
        b'{"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": '
        b'{"name": "test", "version": "1.0"}}}\n'
    )
    initialized = b'{"jsonrpc": "2.0", "method": "notifications/initialized"}\n'
    malformed_call = (
        b'{"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": '
        b'{"name": "fetch", "arguments": {"url": "http://x\xff\xfe"}}}\n'
    )
    raw_stdin = io.BytesIO(initialize + initialized + malformed_call)
    stdout = io.StringIO()

    async with stdio_server(
        stdin=anyio.AsyncFile(TextIOWrapper(raw_stdin, encoding="utf-8", errors="replace")),
        stdout=anyio.AsyncFile(stdout),
    ) as (read_stream, write_stream):
        with anyio.fail_after(5):
            await mcp._lowlevel_server.run(
                read_stream,
                write_stream,
                mcp._lowlevel_server.create_initialization_options(),
            )

    stdout.seek(0)
    output_lines = [line.strip() for line in stdout.readlines() if line.strip()]

    assert output_lines
    initialize_response = jsonrpc_message_adapter.validate_json(output_lines[0])
    assert isinstance(initialize_response, JSONRPCResponse)
    assert initialize_response.id == 1
