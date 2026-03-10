"""Regression tests for memory stream leaks in client transports.

When a connection error occurs (404, 403, ConnectError), transport context
managers must close ALL 4 memory stream ends they created. anyio memory streams
are paired but independent — closing the writer does NOT close the reader.
Unclosed stream ends emit ResourceWarning on GC, which pytest promotes to a
test failure in whatever test happens to be running when GC triggers.

These tests force GC after the transport context exits, so any leaked stream
triggers a ResourceWarning immediately and deterministically here, rather than
nondeterministically in an unrelated later test.
"""

import gc
import socket

import httpx
import pytest

from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.client.websocket import websocket_client


def _unused_tcp_port() -> int:
    """Return a port with no listener. Binding then closing leaves the port unbound."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.mark.anyio
async def test_sse_client_closes_all_streams_on_connection_error() -> None:
    """sse_client must close all 4 stream ends when the connection fails.

    Before the fix, only read_stream_writer and write_stream were closed in
    the finally block. read_stream and write_stream_reader were leaked.
    """
    port = _unused_tcp_port()

    # sse_client enters a task group BEFORE connecting, so anyio wraps the
    # ConnectError from aconnect_sse in an ExceptionGroup. ExceptionGroup is
    # an Exception subclass, so we catch broadly and verify the sub-exception.
    with pytest.raises(Exception) as exc_info:  # noqa: B017
        async with sse_client(f"http://127.0.0.1:{port}/sse"):
            pytest.fail("should not reach here")  # pragma: no cover

    assert exc_info.group_contains(httpx.ConnectError)

    # If any stream leaked, gc.collect() triggers ResourceWarning in __del__,
    # which pytest's filterwarnings=["error"] promotes to a test failure.
    gc.collect()


@pytest.mark.anyio
async def test_streamable_http_client_closes_all_streams_on_exit() -> None:
    """streamable_http_client must close all 4 stream ends on exit.

    Before the fix, read_stream was never closed — not even on the happy path.
    This test enters and exits the context without sending any messages, so no
    network connection is ever attempted (streamable_http connects lazily).
    """
    async with streamable_http_client("http://127.0.0.1:1/mcp"):
        pass

    gc.collect()


@pytest.mark.anyio
async def test_websocket_client_closes_all_streams_on_connection_error() -> None:
    """websocket_client must close all 4 stream ends when ws_connect fails.

    Before the fix, there was no try/finally at all — if ws_connect raised,
    all 4 streams were leaked.
    """
    port = _unused_tcp_port()

    with pytest.raises(OSError):
        async with websocket_client(f"ws://127.0.0.1:{port}/ws"):
            pytest.fail("should not reach here")  # pragma: no cover

    gc.collect()
