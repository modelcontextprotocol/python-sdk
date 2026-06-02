"""The stdio transport: one subprocess end-to-end test and one in-process framing test.

The subprocess test proves the client-server round trip over the transport's real process
boundary; its server lives in `_stdio_server.py` and is launched via `python -m` so subprocess
coverage measurement applies. The framing test drives `stdio_server` over injected in-process
streams instead.

stdio is deliberately not a leg of the `connect`-fixture matrix: a subprocess per test would be
slow, and the matrix already proves transport-agnosticism in-process. Process-lifecycle edge
cases (terminate/kill escalation, parse errors) stay in `tests/client/test_stdio.py`.
"""

import io
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import TextIO, cast

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
    """A stdio-subprocess Client round-trips a tool call, a notification, and a clean exit.

    The Client initializes, calls a tool with arguments, and receives the server's log
    notification before the call returns; the server exits when the transport closes its
    stdin.
    """
    # After stdin closes, the child must unwind, flush its subprocess coverage data, and write
    # the clean-exit line before escalation (the server saves coverage *before* printing, so a
    # post-print kill can no longer silently lose the data file -- see _stdio_server.main). The
    # production 2s default is too tight for the unwind+save tail on loaded Windows runners
    # (measured in-situ p99 of the whole test is ~7s); a kill before the print fails the stderr
    # assertion below loudly rather than tripping the coverage gate. The 20s grace covers even a
    # badly starved runner (a >10s stall has been seen once in CI) and costs nothing when the
    # child exits promptly. Not under test.
    monkeypatch.setattr(stdio, "PROCESS_TERMINATION_TIMEOUT", 20.0)

    received: list[LoggingMessageNotificationParams] = []

    async def collect(params: LoggingMessageNotificationParams) -> None:
        received.append(params)

    with tempfile.TemporaryFile(mode="w+") as errlog_file:
        errlog = cast(TextIO, errlog_file)
        transport = stdio_client(
            StdioServerParameters(
                command=sys.executable,
                args=["-m", _stdio_server.__name__],
                cwd=str(_REPO_ROOT),
                # stdio_client filters the inherited environment, dropping the variables
                # coverage.py's subprocess support uses; pass them through so the server module is
                # measured. PYTHONWARNINGS: the child recompiles anyio (pytest's pyc tag differs),
                # and on 3.14 anyio's return-in-finally SyntaxWarning would land on the snapshot stderr.
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
    # stdio carries one ordered server-to-client stream, so the same notification-before-response
    # guarantee holds here as for the in-memory transport.
    assert received == snapshot(
        [LoggingMessageNotificationParams(level="info", logger="echo", data="echoing across\nprocesses")]
    )
    # The server writes this line only after its run loop returns, which happens when stdin closes:
    # seeing it proves the process exited on its own rather than via the transport's terminate
    # escalation, without a timing-based assertion. The suffix check keeps the test stable if the
    # child interpreter emits dependency warnings before the server's own stderr line.
    assert captured_stderr.endswith("stdio-echo: clean exit\n")


@requirement("transport:stdio:stream-purity")
@requirement("transport:stdio:no-embedded-newlines")
async def test_stdio_server_writes_one_jsonrpc_message_per_line() -> None:
    """Every `stdio_server` write is one valid JSON-RPC message on its own line.

    Each line is newline-terminated with payload newlines JSON-escaped. This proves the
    transport's own framing; it does not guard `sys.stdout` against handler code (see the
    divergence on `transport:stdio:stream-purity`).
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
    # The newline inside the payload is JSON-escaped on the wire, not a literal newline that would
    # break the one-message-per-line framing.
    assert r"line\nbreak" in lines[0]
    assert r"two\nlines" in lines[1]
