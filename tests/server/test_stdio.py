import io

import anyio
import pytest

from mcp.server.stdio import stdio_server
from mcp.types import JSONRPCMessage, JSONRPCRequest, JSONRPCResponse, MessageFrame


@pytest.mark.anyio
async def test_stdio_server():
    stdin = io.StringIO()
    stdout = io.StringIO()

    messages = [
        JSONRPCRequest(jsonrpc="2.0", id=1, method="ping"),
        JSONRPCResponse(jsonrpc="2.0", id=2, result={}),
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
                received_messages.append(message)
                if len(received_messages) == 2:
                    break

        # Verify received messages
        assert len(received_messages) == 2
        assert isinstance(received_messages[0].message, JSONRPCMessage)
        assert isinstance(received_messages[0].message.root, JSONRPCRequest)
        assert received_messages[0].message.root.id == 1
        assert received_messages[0].message.root.method == "ping"

        assert isinstance(received_messages[1].message, JSONRPCMessage)
        assert isinstance(received_messages[1].message.root, JSONRPCResponse)
        assert received_messages[1].message.root.id == 2

        # Test sending responses from the server
        responses = [
            MessageFrame(
                message=JSONRPCMessage(
                    root=JSONRPCRequest(jsonrpc="2.0", id=3, method="ping")
                ),
                raw=None,
            ),
            MessageFrame(
                message=JSONRPCMessage(
                    root=JSONRPCResponse(jsonrpc="2.0", id=4, result={})
                ),
                raw=None,
            ),
        ]

        async with write_stream:
            for response in responses:
                await write_stream.send(response)

    stdout.seek(0)
    output_lines = stdout.readlines()
    assert len(output_lines) == 2

    # Parse and verify the JSON responses directly
    request_json = JSONRPCRequest.model_validate_json(output_lines[0].strip())
    response_json = JSONRPCResponse.model_validate_json(output_lines[1].strip())

    assert request_json.id == 3
    assert request_json.method == "ping"
    assert response_json.id == 4
