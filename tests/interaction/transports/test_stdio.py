"""The stdio transport: one subprocess end-to-end test and one in-process framing test.

Everything else in the suite runs in a single process; the subprocess test exists to prove the same
client↔server round trip works over the stdio transport's real boundary (a child process whose
stdin/stdout carry one newline-delimited JSON-RPC message per line). The server lives in
`_stdio_server.py` and is launched via `python -m` so subprocess coverage measurement applies.

The framing test drives `stdio_server` in-process by passing it injected text streams instead of the
real stdin/stdout, so the raw lines the transport writes can be asserted directly without a process
boundary.

stdio is deliberately not a leg of the `connect`-fixture matrix: spawning a subprocess per test
would be slow, and the matrix already proves transport-agnosticism over three in-process
transports. Process-lifecycle edge cases (escalation to terminate/kill, parse errors) are covered by
`tests/client/test_stdio.py` and stay deferred here.
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

from mcp.client import stdio
from mcp.client.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.stdio import stdio_server
from mcp.shared.message import SessionMessage
from mcp.types import (
    CallToolResult,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    LoggingMessageNotificationParams,
    TextContent,
)
from mcp.types.jsonrpc import jsonrpc_message_adapter
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
    """A Client connected over stdio initializes, calls a tool with arguments, receives the
    server's log notification before the call returns, and the server exits when the transport
    closes its stdin."""
    # After shutdown closes the child's stdin, the child must unwind its run loop, write the
    # clean-exit line asserted below, and let coverage's atexit hook persist the subprocess data
    # file (enabled by the COVERAGE_ passthrough below) before the grace period expires. The
    # production 2s default proved too tight on slow Windows runners: the escalation killed the
    # child mid-atexit — after the asserted stderr line, so the test stayed green — and the
    # silently missing data file tripped the 100% coverage gate. The timeout is not under test.
    monkeypatch.setattr(stdio, "PROCESS_TERMINATION_TIMEOUT", 10.0)

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
                # SyntaxWarning is suppressed because the child compiles dependencies from source
                # (pytest's pyc tag doesn't match a plain python child's): at the anyio>=4.9 floor,
                # Python 3.14 emits a compile-time warning for anyio's return-in-finally, which
                # would land on the snapshot-asserted stderr below.
                env={key: value for key, value in os.environ.items() if key.startswith("COVERAGE_")}
                | {"PYTHONWARNINGS": "ignore::SyntaxWarning"},
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
    # escalation, without a timing-based assertion. The capture itself proves stderr passthrough:
    # the transport routes the child's stderr to the caller's `errlog` without consuming it.
    assert captured_stderr == snapshot("stdio-echo: clean exit\n")


@requirement("transport:stdio:stream-purity")
@requirement("transport:stdio:no-embedded-newlines")
async def test_stdio_server_writes_one_jsonrpc_message_per_line() -> None:
    """Everything `stdio_server` writes is a valid JSON-RPC message on its own line, and nothing else.

    The transport's stdin/stdout parameters are public, so the test injects in-process text streams
    instead of the real process handles and drives the read/write streams directly: a JSON-RPC line on
    stdin is parsed and delivered, and every message sent on the write stream appears as exactly one
    newline-terminated line whose payload newlines are JSON-escaped. This proves the transport's own
    framing; it does not guard `sys.stdout` against handler code that prints to it directly (see the
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
