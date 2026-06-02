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
import sys
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
import pytest

from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.client.websocket import websocket_client


@contextmanager
def _assert_no_memory_stream_leak() -> Iterator[None]:
    """Fail if any anyio MemoryObject stream emits ResourceWarning during the block.

    Uses a custom sys.unraisablehook to capture ONLY MemoryObject stream leaks,
    ignoring unrelated resources (e.g. PipeHandle from flaky stdio tests on the
    same xdist worker). gc.collect() is forced after the block to make leaks
    deterministic.
    """
    leaked: list[str] = []
    old_hook = sys.unraisablehook

    def hook(args: "sys.UnraisableHookArgs") -> None:  # pragma: no cover
        # Only executes if a leak occurs (i.e. the bug is present).
        # args.object is the __del__ function (not the stream instance) when
        # unraisablehook fires from a finalizer, so check exc_value — the
        # actual ResourceWarning("Unclosed <MemoryObjectSendStream at ...>").
        # Non-MemoryObject unraisables (e.g. PipeHandle leaked by an earlier
        # flaky test on the same xdist worker) are deliberately ignored —
        # this test should not fail for another test's resource leak.
        if "MemoryObject" in str(args.exc_value):
            leaked.append(str(args.exc_value))

    sys.unraisablehook = hook
    try:
        yield
        gc.collect()
        assert not leaked, f"Memory streams leaked: {leaked}"
    finally:
        sys.unraisablehook = old_hook


@pytest.mark.anyio
async def test_sse_client_closes_all_streams_on_connection_error(free_tcp_port: int) -> None:
    """sse_client creates streams only after the SSE connection succeeds, so a
    ConnectError propagates directly with nothing to leak.

    Before the fix, streams were created before connecting and only 2 of 4 were
    closed in the finally block.
    """
    with _assert_no_memory_stream_leak():
        with pytest.raises(httpx.ConnectError):
            async with sse_client(f"http://127.0.0.1:{free_tcp_port}/sse"):
                pytest.fail("should not reach here")  # pragma: no cover


@pytest.mark.anyio
async def test_sse_client_closes_all_streams_on_http_error() -> None:
    """sse_client creates streams only after raise_for_status() passes, so an
    HTTPStatusError from a 4xx/5xx response propagates bare (not wrapped in an
    ExceptionGroup) with nothing to leak — the task group is never entered.
    """

    def return_403(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    def mock_factory(
        headers: dict[str, str] | None = None,
        timeout: httpx.Timeout | None = None,
        auth: httpx.Auth | None = None,
    ) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(return_403))

    with _assert_no_memory_stream_leak():
        with pytest.raises(httpx.HTTPStatusError):
            async with sse_client("http://test/sse", httpx_client_factory=mock_factory):
                pytest.fail("should not reach here")  # pragma: no cover


@pytest.mark.anyio
async def test_streamable_http_client_closes_all_streams_on_exit() -> None:
    """streamable_http_client must close all 4 stream ends on exit.

    Before the fix, read_stream was never closed — not even on the happy path.
    This test enters and exits the context without sending any messages, so no
    network connection is ever attempted (streamable_http connects lazily).
    """
    with _assert_no_memory_stream_leak():
        async with streamable_http_client("http://127.0.0.1:1/mcp"):
            pass


@pytest.mark.anyio
async def test_websocket_client_closes_all_streams_on_connection_error(free_tcp_port: int) -> None:
    """websocket_client must close all 4 stream ends when ws_connect fails.

    Before the fix, there was no try/finally at all — if ws_connect raised,
    all 4 streams were leaked.
    """
    with _assert_no_memory_stream_leak():
        with pytest.raises(OSError):
            async with websocket_client(f"ws://127.0.0.1:{free_tcp_port}/ws"):
                pytest.fail("should not reach here")  # pragma: no cover
