import io
import sys
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from io import TextIOWrapper

import anyio
import pytest
from mcp_types import JSONRPCMessage, JSONRPCRequest, JSONRPCResponse, jsonrpc_message_adapter

from mcp.server.mcpserver import MCPServer
from mcp.server.stdio import stdio_server
from mcp.shared.message import SessionMessage


@pytest.mark.anyio
async def test_stdio_server_round_trips_messages_over_injected_streams() -> None:
    """Each JSON-RPC message is framed as exactly one line, in both directions."""
    stdin = io.StringIO()
    stdout = io.StringIO()

    messages = [
        JSONRPCRequest(jsonrpc="2.0", id=1, method="ping"),
        JSONRPCResponse(jsonrpc="2.0", id=2, result={}),
    ]

    for message in messages:
        stdin.write(message.model_dump_json(by_alias=True, exclude_none=True) + "\n")
    stdin.seek(0)

    with anyio.fail_after(5):
        async with stdio_server(stdin=anyio.AsyncFile(stdin), stdout=anyio.AsyncFile(stdout)) as (
            read_stream,
            write_stream,
        ):
            async with read_stream:
                received_messages: list[JSONRPCMessage] = []
                for _ in range(2):
                    received = await read_stream.receive()
                    assert not isinstance(received, Exception)
                    received_messages.append(received.message)

            assert received_messages[0] == JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
            assert received_messages[1] == JSONRPCResponse(jsonrpc="2.0", id=2, result={})

            responses = [
                JSONRPCRequest(jsonrpc="2.0", id=3, method="ping"),
                JSONRPCResponse(jsonrpc="2.0", id=4, result={}),
            ]

            for response in responses:
                await write_stream.send(SessionMessage(response))
            await write_stream.aclose()

    stdout.seek(0)
    output_lines = stdout.readlines()
    assert len(output_lines) == 2

    received_responses = [jsonrpc_message_adapter.validate_json(line.strip()) for line in output_lines]
    assert received_responses[0] == JSONRPCRequest(jsonrpc="2.0", id=3, method="ping")
    assert received_responses[1] == JSONRPCResponse(jsonrpc="2.0", id=4, result={})


@pytest.mark.anyio
async def test_stdio_server_invalid_utf8(monkeypatch: pytest.MonkeyPatch) -> None:
    """Invalid UTF-8 stdin lines surface as in-stream exceptions; later valid messages still arrive."""
    valid = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    raw_stdin = io.BytesIO(b"\xff\xfe\n" + valid.model_dump_json(by_alias=True, exclude_none=True).encode() + b"\n")

    # Exercise stdio_server()'s default path, which re-wraps sys.stdin.buffer with errors='replace'.
    monkeypatch.setattr(sys, "stdin", TextIOWrapper(raw_stdin, encoding="utf-8"))
    monkeypatch.setattr(sys, "stdout", TextIOWrapper(io.BytesIO(), encoding="utf-8"))

    with anyio.fail_after(5):
        async with stdio_server() as (read_stream, write_stream):
            await write_stream.aclose()
            async with read_stream:  # pragma: no branch
                # \xff\xfe -> U+FFFD U+FFFD -> JSON parse fails -> exception in stream
                first = await read_stream.receive()
                assert isinstance(first, Exception)

                second = await read_stream.receive()
                assert isinstance(second, SessionMessage)
                assert second.message == valid


class _KeepOpenBytesIO(io.BytesIO):
    """BytesIO that ignores close(), so output stays readable after `run()` tears down its TextIOWrapper."""

    def close(self) -> None:
        pass


def _run_stdio_bounded(server: MCPServer) -> None:
    """Run the blocking `server.run("stdio")` in a daemon thread joined with a 5s bound.

    `run()` owns its event loop, so `anyio.fail_after` can't bound it; the join timeout turns a
    hang into a red test. An exception escaping `run()` still fails: pytest's unhandled-thread
    warning is escalated by `filterwarnings = ["error"]`.
    """

    def target() -> None:
        server.run("stdio")

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(5)
    assert not thread.is_alive(), 'run("stdio") did not return after stdin EOF'


def test_mcpserver_run_stdio_serves_until_stdin_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    ping = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    stdin_bytes = io.BytesIO(ping.model_dump_json(by_alias=True, exclude_none=True).encode() + b"\n")
    captured = _KeepOpenBytesIO()
    monkeypatch.setattr(sys, "stdin", TextIOWrapper(stdin_bytes, encoding="utf-8"))
    monkeypatch.setattr(sys, "stdout", TextIOWrapper(captured, encoding="utf-8"))

    _run_stdio_bounded(MCPServer(name="RunStdioServer"))

    response = jsonrpc_message_adapter.validate_json(captured.getvalue().decode().strip())
    assert response == JSONRPCResponse(jsonrpc="2.0", id=1, result={})


def test_mcpserver_run_stdio_runs_lifespan_cleanup_after_stdin_closes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression for issue #1027: stdin EOF must end the run loop and unwind the lifespan, not kill it."""
    events: list[str] = []

    @asynccontextmanager
    async def lifespan(server: MCPServer) -> AsyncIterator[None]:
        events.append("setup")
        try:
            yield
        finally:
            events.append("cleanup")

    ping = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    stdin_bytes = io.BytesIO(ping.model_dump_json(by_alias=True, exclude_none=True).encode() + b"\n")
    captured = _KeepOpenBytesIO()
    monkeypatch.setattr(sys, "stdin", TextIOWrapper(stdin_bytes, encoding="utf-8"))
    monkeypatch.setattr(sys, "stdout", TextIOWrapper(captured, encoding="utf-8"))

    _run_stdio_bounded(MCPServer(name="LifespanStdioServer", lifespan=lifespan))

    assert events == ["setup", "cleanup"]
    response = jsonrpc_message_adapter.validate_json(captured.getvalue().decode().strip())
    assert response == JSONRPCResponse(jsonrpc="2.0", id=1, result={})
