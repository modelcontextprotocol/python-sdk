"""Regression test for issue #2328: raw invalid UTF-8 over stdio must not crash the server."""

import io
from io import TextIOWrapper
from typing import cast

import anyio
import pytest
from pydantic import AnyHttpUrl, AnyUrl, TypeAdapter

from mcp import types
from mcp.server import ServerRequestContext
from mcp.server.lowlevel.server import Server
from mcp.server.mcpserver import MCPServer
from mcp.server.stdio import stdio_server
from mcp.types import JSONRPCError, JSONRPCResponse, jsonrpc_message_adapter


@pytest.mark.anyio
async def test_stdio_server_returns_error_for_raw_invalid_utf8_tool_arguments():
    """Invalid UTF-8 bytes in a request body should become a JSON-RPC error, not a crash."""

    url_adapter = TypeAdapter(AnyUrl)

    async def handle_list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[
                types.Tool(
                    name="fetch",
                    description="Fetch a URL",
                    input_schema={
                        "type": "object",
                        "required": ["url"],
                        "properties": {"url": {"type": "string"}},
                    },
                )
            ]
        )

    async def handle_call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> types.CallToolResult:
        arguments = params.arguments or {}
        url_adapter.validate_python(arguments["url"])
        return types.CallToolResult(content=[types.TextContent(type="text", text="ok")])

    ctx = cast(ServerRequestContext, None)
    list_tools_result = await handle_list_tools(ctx, None)
    assert list_tools_result.tools[0].name == "fetch"

    valid_tool_call_result = await handle_call_tool(
        ctx,
        types.CallToolRequestParams(name="fetch", arguments={"url": "https://example.com"}),
    )
    assert valid_tool_call_result.content == [types.TextContent(type="text", text="ok")]

    server = Server("test-server", on_list_tools=handle_list_tools, on_call_tool=handle_call_tool)

    raw_stdin = io.BytesIO(
        b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}\n'
        b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        b'{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"fetch","arguments":{"url":"http://x\xff\xfe"}}}\n'
    )
    raw_stdout = io.BytesIO()
    stdout = TextIOWrapper(raw_stdout, encoding="utf-8")

    async with stdio_server(
        stdin=anyio.wrap_file(TextIOWrapper(raw_stdin, encoding="utf-8", errors="replace")),
        stdout=anyio.wrap_file(stdout),
    ) as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())

    stdout.flush()
    responses = [
        jsonrpc_message_adapter.validate_json(line) for line in raw_stdout.getvalue().decode("utf-8").splitlines()
    ]

    assert len(responses) == 2
    assert isinstance(responses[0], JSONRPCResponse)
    assert responses[0].id == 1
    assert isinstance(responses[1], JSONRPCError)
    assert responses[1].id == 3
    assert responses[1].error.message


@pytest.mark.anyio
async def test_stdio_server_stays_alive_when_tool_validation_finishes_after_stdin_eof():
    """The MCPServer tool path should not crash if validation loses the response race."""

    mcp = MCPServer("test")

    @mcp.tool()
    async def fetch(url: str) -> str:
        # Delay validation so stdin can hit EOF and close the session write
        # stream before the tool returns its validation failure.
        await anyio.sleep(0.1)
        return str(TypeAdapter(AnyHttpUrl).validate_python(url))

    assert await fetch("https://example.com") == "https://example.com/"

    raw_stdin = io.BytesIO(
        b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}\n'
        b'{"jsonrpc":"2.0","method":"notifications/initialized"}\n'
        b'{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"fetch","arguments":{"url":"http://x\xff\xfe"}}}\n'
    )
    raw_stdout = io.BytesIO()
    stdout = TextIOWrapper(raw_stdout, encoding="utf-8")

    async with stdio_server(
        stdin=anyio.wrap_file(TextIOWrapper(raw_stdin, encoding="utf-8", errors="replace")),
        stdout=anyio.wrap_file(stdout),
    ) as (read_stream, write_stream):
        with anyio.fail_after(5):
            await mcp._lowlevel_server.run(
                read_stream,
                write_stream,
                mcp._lowlevel_server.create_initialization_options(),
            )

    stdout.flush()
    responses = [
        jsonrpc_message_adapter.validate_json(line) for line in raw_stdout.getvalue().decode("utf-8").splitlines()
    ]

    assert responses
    assert isinstance(responses[0], JSONRPCResponse)
    assert responses[0].id == 1
