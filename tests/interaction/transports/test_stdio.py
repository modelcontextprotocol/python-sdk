"""Stdio subprocess round-trip and in-process framing tests.

Lifecycle edge cases remain in `tests/client/test_stdio.py`.
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
from tests._stamp import unstamped as strip_stamp
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
    """A stdio client round-trips a tool call and notification before clean exit."""
    # Allow slow Windows runners to flush subprocess coverage before escalation.
    monkeypatch.setattr(stdio, "PROCESS_TERMINATION_TIMEOUT", 20.0)

    received: list[LoggingMessageNotificationParams] = []

    async def collect(params: LoggingMessageNotificationParams) -> None:
        received.append(params)

    with tempfile.TemporaryFile(mode="w+", encoding="utf-8", errors="replace") as errlog:
        transport = stdio_client(
            StdioServerParameters(
                command=sys.executable,
                args=["-m", _stdio_server.__name__],
                cwd=str(_REPO_ROOT),
                # Preserve subprocess coverage and suppress anyio's `SyntaxWarning` on Python 3.14.
                env={key: value for key, value in os.environ.items() if key.startswith("COVERAGE_")}
                | {"PYTHONWARNINGS": "ignore::SyntaxWarning"},
            ),
            errlog=errlog,
        )

        # Must exceed session time plus the patched PROCESS_TERMINATION_TIMEOUT (20s).
        with anyio.fail_after(30):
            async with Client(transport, mode="legacy", logging_callback=collect) as client:
                assert client.server_info is not None
                assert client.server_info.name == "stdio-echo"
                result = await client.call_tool("echo", {"text": "across\nprocesses"})

        errlog.seek(0)
        captured_stderr = errlog.read()

    assert result == snapshot(CallToolResult(content=[TextContent(text="across\nprocesses")]))
    # Stdio preserves notification-before-response ordering.
    assert received == snapshot(
        [LoggingMessageNotificationParams(level="info", logger="echo", data="echoing across\nprocesses")]
    )
    # The marker distinguishes clean exit from termination.
    assert captured_stderr == snapshot("stdio-echo: clean exit\n")


@requirement("transport:stdio:dual-era-serving")
async def test_an_auto_mode_client_negotiates_2026_over_the_same_stdio_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The subprocess server the legacy test drives also serves an auto-negotiating client at
    2026-07-28: no handshake, serverInfo from the result stamp, and the log notification still
    arrives ahead of the response because the request carried a logLevel."""
    monkeypatch.setattr(stdio, "PROCESS_TERMINATION_TIMEOUT", 20.0)

    received: list[LoggingMessageNotificationParams] = []

    async def collect(params: LoggingMessageNotificationParams) -> None:
        received.append(params)

    server = StdioServerParameters(
        command=sys.executable,
        args=["-m", _stdio_server.__name__],
        cwd=str(_REPO_ROOT),
        env={key: value for key, value in os.environ.items() if key.startswith("COVERAGE_")}
        | {"PYTHONWARNINGS": "ignore::SyntaxWarning"},
    )

    # Must exceed session time plus the patched PROCESS_TERMINATION_TIMEOUT (20s).
    with anyio.fail_after(30):
        async with Client(server, mode="auto", logging_callback=collect, log_level="info") as client:
            assert client.protocol_version == "2026-07-28"
            assert client.server_info is not None
            assert client.server_info.name == "stdio-echo"
            result = await client.call_tool("echo", {"text": "across\nprocesses"})

    assert strip_stamp(result) == snapshot(CallToolResult(content=[TextContent(text="across\nprocesses")]))
    assert received == snapshot(
        [LoggingMessageNotificationParams(level="info", logger="echo", data="echoing across\nprocesses")]
    )


@requirement("transport:stdio:stream-purity")
@requirement("transport:stdio:no-embedded-newlines")
async def test_stdio_server_writes_one_jsonrpc_message_per_line() -> None:
    """Each `stdio_server` write is one newline-terminated JSON-RPC message."""
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
    assert r"line\nbreak" in lines[0]
    assert r"two\nlines" in lines[1]
