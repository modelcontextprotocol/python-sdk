"""The suite's one stdio end-to-end test: a real SDK Server in a subprocess, driven by Client.

Everything else in the suite runs in a single process; this test exists to prove the same
client↔server round trip works over the stdio transport's real boundary (a child process whose
stdin/stdout carry one newline-delimited JSON-RPC message per line). The server lives in
`_stdio_server.py` and is launched via `python -m` so subprocess coverage measurement applies.

stdio is deliberately not a leg of the `connect`-fixture matrix: spawning a subprocess per test
would be slow, and the matrix already proves transport-agnosticism over three in-process
transports. Process-lifecycle edge cases (escalation to terminate/kill, stderr handling, parse
errors) are covered by `tests/client/test_stdio.py` and stay deferred here.
"""

import os
import sys
import tempfile
from pathlib import Path

import anyio
import pytest
from inline_snapshot import snapshot

from mcp.client.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult, LoggingMessageNotificationParams, TextContent
from tests.interaction._requirements import requirement
from tests.interaction.transports import _stdio_server

pytestmark = pytest.mark.anyio

_REPO_ROOT = Path(__file__).parents[3]


@requirement("transport:stdio")
@requirement("transport:stdio:clean-shutdown")
async def test_tool_call_and_notification_round_trip_over_a_stdio_subprocess() -> None:
    """A Client connected over stdio initializes, calls a tool with arguments, receives the
    server's log notification before the call returns, and the server exits when the transport
    closes its stdin."""
    received: list[LoggingMessageNotificationParams] = []

    async def collect(params: LoggingMessageNotificationParams) -> None:
        received.append(params)

    with tempfile.TemporaryFile(mode="w+") as errlog:
        transport = stdio_client(
            StdioServerParameters(
                command=sys.executable,
                args=["-m", _stdio_server.__name__],
                cwd=str(_REPO_ROOT),
                # stdio_client deliberately filters the inherited environment to a safe minimum,
                # which drops the variables coverage.py's subprocess support uses; pass them through
                # so the server module is measured. Empty when not running under coverage.
                env={key: value for key, value in os.environ.items() if key.startswith("COVERAGE_")},
            ),
            errlog=errlog,
        )

        with anyio.fail_after(10):
            async with Client(transport, logging_callback=collect) as client:
                assert client.initialize_result.server_info.name == "stdio-echo"
                result = await client.call_tool("echo", {"text": "across\nprocesses"})

        errlog.seek(0)
        captured_stderr = errlog.read()

    assert result == snapshot(CallToolResult(content=[TextContent(text="across\nprocesses")]))
    # stdio carries one ordered server→client stream, so the same notification-before-response
    # guarantee holds here as for the in-memory transport.
    assert received == snapshot(
        [LoggingMessageNotificationParams(level="info", logger="echo", data="echoing across\nprocesses")]
    )
    # The server writes this line only after its run loop returns, which happens when stdin closes:
    # seeing it proves the process exited on its own rather than via the transport's terminate
    # escalation, without a timing-based assertion.
    assert captured_stderr == snapshot("stdio-echo: clean exit\n")
