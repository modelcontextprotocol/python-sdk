"""Regression test for #2678: in-flight responses should not be dropped on stdin EOF.

When a server receives a request and stdin hits EOF while the server is still
processing, the response must still be written to stdout. The fix closes
read_stream_writer in stdin_reader's finally block so the server sees EOF and
can flush pending writes before the task group exits.
"""
import io
import sys
import threading
import time
from io import TextIOWrapper

import anyio
import pytest

from mcp.server.mcpserver import MCPServer
from mcp.types import (
    JSONRPCRequest,
    JSONRPCResponse,
    jsonrpc_message_adapter,
)


class _KeepOpenBytesIO(io.BytesIO):
    """A BytesIO that survives its TextIOWrapper being closed."""

    def close(self) -> None:
        pass


def _run_stdio_bounded(server: MCPServer, timeout: float = 5) -> None:
    def target() -> None:
        server.run("stdio")

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), "run('stdio') did not return after stdin EOF"


def test_stdio_response_not_dropped_on_eof(monkeypatch: pytest.MonkeyPatch) -> None:
    """Server response is written to stdout even when stdin closes right after the request.

    Regression test for #2678: stdin EOF used to close read_stream_writer before
    the server could flush its response through stdout_writer.
    """
    ping = JSONRPCRequest(jsonrpc="2.0", id=1, method="ping")
    stdin_bytes = io.BytesIO(
        ping.model_dump_json(by_alias=True, exclude_none=True).encode() + b"\n"
    )
    captured = _KeepOpenBytesIO()
    monkeypatch.setattr(sys, "stdin", TextIOWrapper(stdin_bytes, encoding="utf-8"))
    monkeypatch.setattr(sys, "stdout", TextIOWrapper(captured, encoding="utf-8"))

    _run_stdio_bounded(MCPServer(name="TestEOF"))

    response = jsonrpc_message_adapter.validate_json(captured.getvalue().decode().strip())
    assert response == JSONRPCResponse(jsonrpc="2.0", id=1, result={})
