import shutil

import pytest

from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage, JSONRPCRequest, JSONRPCResponse

tee: str = shutil.which("tee")  # type: ignore


@pytest.mark.anyio
@pytest.mark.skipif(tee is None, reason="could not find tee command")
async def test_stdio_client():
    server_parameters = StdioServerParameters(command=tee)

    async with stdio_client(server_parameters) as (read_stream, write_stream):
        # Test sending and receiving messages
        messages = [
            JSONRPCMessage(root=JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")),
            JSONRPCMessage(root=JSONRPCResponse(jsonrpc="2.0", id=2, result={})),
        ]

        async with write_stream:
            for message in messages:
                session_message = SessionMessage(message)
                await write_stream.send(session_message)

        read_messages = []
        async with read_stream:
            async for message in read_stream:
                if isinstance(message, Exception):
                    raise message

                read_messages.append(message.message)
                if len(read_messages) == 2:
                    break

        assert len(read_messages) == 2
        assert read_messages[0] == JSONRPCMessage(
            root=JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
        )
        assert read_messages[1] == JSONRPCMessage(
            root=JSONRPCResponse(jsonrpc="2.0", id=2, result={})
        )
