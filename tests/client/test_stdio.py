from unittest.mock import patch

import pytest

from mcp.client.stdio import (
    DEFAULT_INHERITED_ENV_VARS,
    StdioServerParameters,
    stdio_client,
)
from mcp.types import JSONRPCMessage, JSONRPCRequest, JSONRPCResponse


@pytest.mark.anyio
async def test_stdio_client():
    server_parameters = StdioServerParameters(command="/usr/bin/tee")

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
async def test_environment_merging():
    captured_env = {}
    
    async def mock_open_process(*args, **kwargs):
        # Just capture the env and return None - we don't care about the process
        captured_env.update(kwargs.get('env', {}))
        return None

    custom_env = {"CUSTOM_VAR": "test_value", "PATH": "/custom/path"}
    server = StdioServerParameters(command="test", env=custom_env)

    with patch('anyio.open_process', side_effect=mock_open_process):
        try:
            async with stdio_client(server):
                pass
        except:  # noqa: E722
            pass
        
    # Check default environment variables are there
    for var in DEFAULT_INHERITED_ENV_VARS:
        assert var in captured_env

    # and check the custom ones
    assert captured_env["CUSTOM_VAR"] == "test_value"
    assert captured_env["PATH"] == "/custom/path"
