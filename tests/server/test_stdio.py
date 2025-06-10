import io
import tempfile
from pathlib import Path

import anyio
import pytest

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.stdio import stdio_server
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, JSONRPCRequest, JSONRPCResponse


@pytest.mark.anyio
async def test_stdio_server():
    stdin = io.StringIO()
    stdout = io.StringIO()

    messages = [
        JSONRPCMessage(root=JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")),
        JSONRPCMessage(root=JSONRPCResponse(jsonrpc="2.0", id=2, result={})),
    ]

    for message in messages:
        stdin.write(message.model_dump_json(by_alias=True, exclude_none=True) + "\n")
    stdin.seek(0)

    async with stdio_server(
        stdin=anyio.AsyncFile(stdin), stdout=anyio.AsyncFile(stdout)
    ) as (read_stream, write_stream):
        received_messages = []
        async with read_stream:
            async for message in read_stream:
                if isinstance(message, Exception):
                    raise message
                received_messages.append(message.message)
                if len(received_messages) == 2:
                    break

        # Verify received messages
        assert len(received_messages) == 2
        assert received_messages[0] == JSONRPCMessage(
            root=JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
        )
        assert received_messages[1] == JSONRPCMessage(
            root=JSONRPCResponse(jsonrpc="2.0", id=2, result={})
        )

        # Test sending responses from the server
        responses = [
            JSONRPCMessage(root=JSONRPCRequest(jsonrpc="2.0", id=3, method="ping")),
            JSONRPCMessage(root=JSONRPCResponse(jsonrpc="2.0", id=4, result={})),
        ]

        async with write_stream:
            for response in responses:
                session_message = SessionMessage(response)
                await write_stream.send(session_message)

    stdout.seek(0)
    output_lines = stdout.readlines()
    assert len(output_lines) == 2

    received_responses = [
        JSONRPCMessage.model_validate_json(line.strip()) for line in output_lines
    ]
    assert len(received_responses) == 2
    assert received_responses[0] == JSONRPCMessage(
        root=JSONRPCRequest(jsonrpc="2.0", id=3, method="ping")
    )
    assert received_responses[1] == JSONRPCMessage(
        root=JSONRPCResponse(jsonrpc="2.0", id=4, result={})
    )


@pytest.mark.anyio
async def test_stateless_stdio():
    """Test that stateless stdio mode allows tool calls without initialization."""
    with tempfile.TemporaryDirectory() as temp_dir:
        server_path = Path(temp_dir) / "server.py"
        
        with open(server_path, "w") as f:
            f.write("""
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("StatelessServer")
mcp.settings.stateless_stdio = True

@mcp.tool()
def echo(message: str) -> str:
    return f"Echo: {message}"

if __name__ == "__main__":
    mcp.run()
""")

        server_params = StdioServerParameters(
            command="python",
            args=[str(server_path)],
        )

        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                result = await session.call_tool("echo", {"message": "hello"})
                assert len(result.content) == 1
                assert result.content[0].type == "text"
                assert getattr(result.content[0], "text") == "Echo: hello"
