"""Test for issue #552: stdio_client hangs on Windows."""

import json
import sys
from textwrap import dedent

import anyio
import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.version import HANDSHAKE_PROTOCOL_VERSIONS
from mcp.types import InitializeResult


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific test")  # pragma: no cover
@pytest.mark.anyio
async def test_initialize_succeeds_and_shutdown_returns_after_the_server_exits_mid_session():
    """Initialize completes and shutdown returns when the server exits mid-session.

    This is the proactor pipe scenario that hung on Windows 11 (issue #552). The positive
    assertion matters: a session that errors quickly would also "not hang".
    """
    # A minimal server: answer initialize correctly, then exit.
    server_script = dedent(f"""
        import json
        import sys

        line = sys.stdin.readline()
        request = json.loads(line)

        response = {{
            "jsonrpc": "2.0",
            "id": request["id"],
            "result": {{
                "protocolVersion": {json.dumps(HANDSHAKE_PROTOCOL_VERSIONS[-1])},
                "capabilities": {{}},
                "serverInfo": {{"name": "test-server", "version": "1.0"}}
            }}
        }}
        print(json.dumps(response))
        sys.stdout.flush()
    """).strip()

    params = StdioServerParameters(
        command=sys.executable,
        args=["-c", server_script],
    )

    with anyio.fail_after(10):
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                result = await session.initialize()
                assert isinstance(result, InitializeResult)
                assert result.server_info.name == "test-server"
            # Exiting ClientSession and stdio_client must not hang even though the
            # server process is already gone.
