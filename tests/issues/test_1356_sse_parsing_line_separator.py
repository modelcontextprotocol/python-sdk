"""Test for issue #1356: SSE parsing fails with Unicode line separator characters."""

import multiprocessing
import socket
import time
from collections.abc import Generator
from typing import Any

import anyio
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Mount, Route

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import McpError
from mcp.types import TextContent, Tool

pytestmark = pytest.mark.anyio


class ProblematicUnicodeServer(Server):
    """Test server that returns problematic Unicode characters."""

    def __init__(self):
        super().__init__("ProblematicUnicodeServer")

        @self.list_tools()
        async def handle_list_tools() -> list[Tool]:
            return [
                Tool(
                    name="get_problematic_unicode",
                    description="Returns text with problematic Unicode character U+2028",
                    inputSchema={"type": "object", "properties": {}},
                )
            ]

        @self.call_tool()
        async def handle_call_tool(name: str, args: dict[str, Any]) -> list[TextContent]:
            if name == "get_problematic_unicode":
                # Return text with U+2028 (LINE SEPARATOR) which can cause JSON parsing issues
                # U+2028 is a valid Unicode character but can break JSON parsing in some contexts
                problematic_text = "This text contains a line separator\u2028character that may break JSON parsing"
                return [TextContent(type="text", text=problematic_text)]
            return [TextContent(type="text", text=f"Unknown tool: {name}")]


def make_problematic_server_app() -> Starlette:
    """Create test Starlette app with SSE transport."""
    security_settings = TransportSecuritySettings(
        allowed_hosts=["127.0.0.1:*", "localhost:*"],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*"],
    )
    sse = SseServerTransport("/messages/", security_settings=security_settings)
    server = ProblematicUnicodeServer()

    async def handle_sse(request: Request) -> Response:
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())
        return Response()

    app = Starlette(
        routes=[
            Route("/sse", endpoint=handle_sse),
            Mount("/messages/", app=sse.handle_post_message),
        ]
    )

    return app


def run_problematic_server(server_port: int) -> None:
    """Run the problematic Unicode test server."""
    app = make_problematic_server_app()
    server = uvicorn.Server(config=uvicorn.Config(app=app, host="127.0.0.1", port=server_port, log_level="error"))
    server.run()


@pytest.fixture
def problematic_server_port() -> int:
    """Get an available port for the test server."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def problematic_server(problematic_server_port: int) -> Generator[str, None, None]:
    """Start the problematic Unicode test server in a separate process."""
    proc = multiprocessing.Process(
        target=run_problematic_server, kwargs={"server_port": problematic_server_port}, daemon=True
    )
    proc.start()

    # Wait for server to be running
    max_attempts = 20
    attempt = 0
    while attempt < max_attempts:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(("127.0.0.1", problematic_server_port))
                break
        except ConnectionRefusedError:
            time.sleep(0.1)
            attempt += 1
    else:
        raise RuntimeError(f"Server failed to start after {max_attempts} attempts")

    yield f"http://127.0.0.1:{problematic_server_port}"

    # Clean up
    proc.kill()
    proc.join(timeout=2)


async def test_json_parsing_with_problematic_unicode(problematic_server: str) -> None:
    """Test that special Unicode characters like U+2028 are handled properly.

    This test reproduces issue #1356 where special Unicode characters
    cause JSON parsing to fail and the raw exception is sent to the stream,
    preventing proper error handling.
    """
    # Connect to the server using SSE client
    async with sse_client(problematic_server + "/sse") as streams:
        async with ClientSession(*streams) as session:
            # Initialize the connection
            result = await session.initialize()
            assert result.serverInfo.name == "ProblematicUnicodeServer"

            # Call the tool that returns problematic Unicode
            # This should succeed and not hang

            # Use a timeout to detect if we're hanging
            with anyio.fail_after(5):  # 5 second timeout
                try:
                    response = await session.call_tool("get_problematic_unicode", {})

                    # If we get here, the Unicode was handled properly
                    assert len(response.content) == 1
                    text_content = response.content[0]
                    assert hasattr(text_content, "text"), f"Response doesn't have text: {text_content}"

                    # Type narrowing for pyright
                    from mcp.types import TextContent

                    assert isinstance(text_content, TextContent)

                    expected = "This text contains a line separator\u2028character that may break JSON parsing"
                    assert text_content.text == expected, f"Expected: {expected!r}, Got: {text_content.text!r}"

                except McpError:
                    pytest.fail("Unexpected error with tool call")
                except TimeoutError:
                    # If we timeout, the issue is confirmed - the client hangs
                    pytest.fail("Client hangs when handling problematic Unicode (issue #1356 confirmed)")
                except Exception as e:
                    # We should not get raw exceptions - they should be wrapped as McpError
                    pytest.fail(f"Got raw exception instead of McpError: {type(e).__name__}: {e}")
