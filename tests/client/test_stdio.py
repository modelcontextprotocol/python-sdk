import re
import shutil
import sys

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup
else:
    ExceptionGroup = ExceptionGroup

import pytest

from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import JSONRPCMessage, JSONRPCRequest, JSONRPCResponse

tee: str = shutil.which("tee")  # type: ignore


@pytest.mark.anyio
@pytest.mark.skipif(tee is None, reason="could not find tee command")
async def test_stdio_client():
    server_parameters = StdioServerParameters(command=tee)

    async with stdio_client(server_parameters) as (read_stream, write_stream):
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
                if len(read_messages) == len(messages):
                    break

        assert read_messages == messages


@pytest.mark.anyio
async def test_stdio_client_spawn_failure():
    server_parameters = StdioServerParameters(command="/does/not/exist")

    with pytest.raises(RuntimeError, match="Failed to spawn process"):
        async with stdio_client(server_parameters):
            pytest.fail("Should never be reached.")


@pytest.mark.anyio
async def test_stdio_client_nonzero_exit():
    server_parameters = StdioServerParameters(
        command="python", args=["-c", "import sys; sys.exit(2)"]
    )

    with pytest.raises(ExceptionGroup) as eg_info:
        async with stdio_client(server_parameters, startup_wait_time=0.2):
            pytest.fail("Should never be reached.")

    exc = eg_info.value.exceptions[0]
    assert isinstance(exc, RuntimeError)
    assert re.search(r"exited with code 2", str(exc))
