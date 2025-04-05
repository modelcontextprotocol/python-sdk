import shutil

import pytest
from anyio import fail_after

from mcp.client.session import ClientSession
from mcp.client.stdio import (
    ProcessTerminatedEarlyError,
    StdioServerParameters,
    stdio_client,
)
from mcp.types import JSONRPCMessage, JSONRPCRequest, JSONRPCResponse

tee: str = shutil.which("tee")  # type: ignore
python: str = shutil.which("python")  # type: ignore


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
                await write_stream.send(message)

        read_messages = []
        async with read_stream:
            async for message in read_stream:
                if isinstance(message, Exception):
                    raise message

                read_messages.append(message)
                if len(read_messages) == 2:
                    break

        assert len(read_messages) == 2
        assert read_messages[0] == JSONRPCMessage(
            root=JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
        )
        assert read_messages[1] == JSONRPCMessage(
            root=JSONRPCResponse(jsonrpc="2.0", id=2, result={})
        )


@pytest.mark.anyio
@pytest.mark.skipif(python is None, reason="could not find python command")
async def test_initialize_with_exiting_server():
    """
    Test that ClientSession.initialize raises an error if the server process exits.
    """
    # Create a server that will exit during initialization
    server_params = StdioServerParameters(
        command="python",
        args=[
            "-c",
            "import sys; print('Error: Missing API key', file=sys.stderr); sys.exit(1)",
        ],
    )

    with pytest.raises(ProcessTerminatedEarlyError):
        try:
            # Set a timeout to avoid hanging indefinitely if the test fails
            with fail_after(5):
                async with stdio_client(server_params) as (read_stream, write_stream):
                    # Create a client session
                    session = ClientSession(read_stream, write_stream)

                    # This should fail because the server process has exited
                    await session.initialize()
        except TimeoutError:
            pytest.fail("The connection hung and timed out.")
