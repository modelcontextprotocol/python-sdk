import shutil

import pytest
from anyio import fail_after

from mcp.client.stdio import (
    ProcessTerminatedEarlyError,
    StdioServerParameters,
    stdio_client,
)
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
async def test_stdio_client_bad_path():
    """Check that the connection doesn't hang if process errors."""
    server_parameters = StdioServerParameters(
        command="uv", args=["run", "non-existent-file.py"]
    )

    with pytest.raises(ProcessTerminatedEarlyError):
        try:
            with fail_after(1):
                async with stdio_client(server_parameters) as (
                    read_stream,
                    _,
                ):
                    # Try waiting for read_stream so that we don't exit before the
                    #  process fails.
                    async with read_stream:
                        async for message in read_stream:
                            if isinstance(message, Exception):
                                raise message

                    pass
        except TimeoutError:
            pytest.fail("The connection hung.")
