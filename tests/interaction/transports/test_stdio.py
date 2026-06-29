"""The stdio transport: one subprocess end-to-end test and one in-process framing test.

The subprocess server lives in `_stdio_server.py`, launched via `python -m` so subprocess coverage
applies. stdio is deliberately not a leg of the `connect`-fixture matrix: a subprocess per test
would be slow, and the matrix already proves transport-agnosticism in-process. Process-lifecycle
edge cases (terminate/kill escalation, parse errors) stay in `tests/client/test_stdio.py`.
"""

import io
import json
import os
import sys
import tempfile
from pathlib import Path

import anyio
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    CallToolResult,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    LoggingMessageNotificationParams,
    TextContent,
)
from mcp_types.jsonrpc import jsonrpc_message_adapter

from mcp.client import stdio
from mcp.client.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.stdio import stdio_server
from mcp.shared.message import SessionMessage
from tests.interaction._connect import initialize_body
from tests.interaction._requirements import requirement
from tests.interaction.transports import _stdio_server

pytestmark = pytest.mark.anyio

_REPO_ROOT = Path(__file__).parents[3]


@requirement("transport:stdio")
@requirement("transport:stdio:clean-shutdown")
@requirement("transport:stdio:stderr-passthrough")
async def test_tool_call_and_notification_round_trip_over_a_stdio_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Client round-trips a tool call and notification; the server self-exits when stdin closes."""
    # After stdin closes the child must unwind, flush subprocess coverage, and print the clean-exit
    # line before escalation; the production 2s default is too tight on loaded Windows runners
    # (in-situ p99 ~7s, one >10s CI stall). A premature kill fails the stderr assertion loudly. Not under test.
    monkeypatch.setattr(stdio, "PROCESS_TERMINATION_TIMEOUT", 20.0)

    received: list[LoggingMessageNotificationParams] = []

    async def collect(params: LoggingMessageNotificationParams) -> None:
        received.append(params)

    with tempfile.TemporaryFile(mode="w+") as errlog:
        transport = stdio_client(
            StdioServerParameters(
                command=sys.executable,
                args=["-m", _stdio_server.__name__],
                cwd=str(_REPO_ROOT),
                # stdio_client filters the inherited env, dropping coverage.py's subprocess-support
                # vars. PYTHONWARNINGS: the child recompiles anyio (pytest's pyc tag differs), and on
                # 3.14 anyio's return-in-finally SyntaxWarning would land on the snapshot stderr.
                env={key: value for key, value in os.environ.items() if key.startswith("COVERAGE_")}
                | {"PYTHONWARNINGS": "ignore::SyntaxWarning"},
            ),
            errlog=errlog,
        )

        # Must exceed session time plus the patched PROCESS_TERMINATION_TIMEOUT (20s).
        with anyio.fail_after(30):
            async with Client(transport, mode="legacy", logging_callback=collect) as client:
                assert client.server_info.name == "stdio-echo"
                result = await client.call_tool("echo", {"text": "across\nprocesses"})

        errlog.seek(0)
        captured_stderr = errlog.read()

    assert result == snapshot(CallToolResult(content=[TextContent(text="across\nprocesses")]))
    # One ordered server-to-client stream: the notification-before-response guarantee holds as in-memory.
    assert received == snapshot(
        [LoggingMessageNotificationParams(level="info", logger="echo", data="echoing across\nprocesses")]
    )
    # Written only after the run loop returns on stdin close: proves self-exit, not terminate
    # escalation. The capture itself proves stderr passthrough.
    assert captured_stderr == snapshot("stdio-echo: clean exit\n")


@requirement("transport:stdio:stream-purity")
@requirement("transport:stdio:no-embedded-newlines")
async def test_stdio_server_writes_one_jsonrpc_message_per_line() -> None:
    """Drives `stdio_server` directly over injected in-memory streams to pin the transport's framing.

    Framing only: not a `sys.stdout` guard against handler code (see the divergence on
    `transport:stdio:stream-purity`).
    """
    captured = io.StringIO()
    sent_line = json.dumps(initialize_body(request_id=1)) + "\n"

    with anyio.fail_after(5):
        async with (
            stdio_server(stdin=anyio.wrap_file(io.StringIO(sent_line)), stdout=anyio.wrap_file(captured)) as (
                read_stream,
                write_stream,
            ),
            read_stream,
            write_stream,
        ):
            received = await read_stream.receive()
            assert isinstance(received, SessionMessage)
            assert isinstance(received.message, JSONRPCRequest)
            assert received.message.method == "initialize"

            response = JSONRPCResponse(jsonrpc="2.0", id=1, result={"text": "line\nbreak"})
            notification = JSONRPCNotification(
                jsonrpc="2.0", method="notifications/message", params={"level": "info", "data": "two\nlines"}
            )
            await write_stream.send(SessionMessage(response))
            await write_stream.send(SessionMessage(notification))

    output = captured.getvalue()
    assert output.endswith("\n")
    lines = output.removesuffix("\n").split("\n")
    assert len(lines) == 2
    messages = [jsonrpc_message_adapter.validate_json(line) for line in lines]
    assert [type(message).__name__ for message in messages] == snapshot(["JSONRPCResponse", "JSONRPCNotification"])
    # Payload newlines are JSON-escaped on the wire, not literal newlines that would break the framing.
    assert r"line\nbreak" in lines[0]
    assert r"two\nlines" in lines[1]
