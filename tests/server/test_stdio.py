import io

import anyio
import pytest

from mcp.server.stdio import stdio_server
from mcp.shared.session import MessageFrame
from mcp.types import JSONRPCMessage, JSONRPCRequest, JSONRPCResponse


@pytest.mark.anyio
async def test_stdio_server():
    stdin = io.StringIO()
    stdout = io.StringIO()

    messages = [
        MessageFrame(
            root=JSONRPCMessage(root=JSONRPCRequest(jsonrpc="2.0", id=1, method="ping"))
        ),
        MessageFrame(
            root=JSONRPCMessage(root=JSONRPCResponse(jsonrpc="2.0", id=2, result={}))
        ),
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
        assert received_messages[0] == MessageFrame(
            root=JSONRPCMessage(root=JSONRPCRequest(jsonrpc="2.0", id=1, method="ping"))
        )
        assert received_messages[1] == MessageFrame(
            root=JSONRPCMessage(root=JSONRPCResponse(jsonrpc="2.0", id=2, result={}))
        )

        # Test sending responses from the server
        responses = [
            MessageFrame(
                root=JSONRPCMessage(
                    root=JSONRPCRequest(jsonrpc="2.0", id=3, method="ping")
                )
            ),
            MessageFrame(
                root=JSONRPCMessage(
                    root=JSONRPCResponse(jsonrpc="2.0", id=4, result={})
                )
            ),
        ]

        async with write_stream:
            for response in responses:
                await write_stream.send(response)

    stdout.seek(0)
    output_lines = stdout.readlines()
    assert len(output_lines) == 2

    received_responses = [
        MessageFrame.model_validate_json(line.strip()) for line in output_lines
    ]
    assert len(received_responses) == 2
    assert received_responses[0] == MessageFrame(
        root=JSONRPCMessage(root=JSONRPCRequest(jsonrpc="2.0", id=3, method="ping"))
    )
    assert received_responses[1] == MessageFrame(
        root=JSONRPCMessage(root=JSONRPCResponse(jsonrpc="2.0", id=4, result={}))
    )
