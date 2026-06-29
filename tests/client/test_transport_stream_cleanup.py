"""Regression tests for memory stream leaks in client transports.

On connection errors (404, 403, ConnectError) transports must close all 4 memory stream
ends they created — anyio streams are paired but independent, so closing the writer does
NOT close the reader. Leaked ends emit ResourceWarning on GC (promoted to a test failure
by pytest); forcing gc.collect() here surfaces the leak deterministically instead of
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


@contextmanager
def _assert_no_memory_stream_leak() -> Iterator[None]:
    """Fail if any anyio MemoryObject stream emits ResourceWarning during the block.

    Unrelated unraisables (e.g. PipeHandle from flaky stdio tests on the same xdist worker)
    are deliberately ignored.
    """
    leaked: list[str] = []
    old_hook = sys.unraisablehook

    def hook(args: "sys.UnraisableHookArgs") -> None:  # pragma: no cover
        # Runs only when a leak occurs (hence the pragma). For finalizer unraisables,
        # args.object is the __del__ function, not the stream — match on exc_value instead.
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
    """Streams are created only after the SSE connection succeeds, so ConnectError leaks
    nothing. Before the fix, streams were created pre-connect and only 2 of 4 were closed."""
    with _assert_no_memory_stream_leak():
        with pytest.raises(httpx.ConnectError):
            async with sse_client(f"http://127.0.0.1:{free_tcp_port}/sse"):
                pytest.fail("should not reach here")  # pragma: no cover


@pytest.mark.anyio
async def test_sse_client_closes_all_streams_on_http_error() -> None:
    """Streams are created only after raise_for_status() passes, so HTTPStatusError
    propagates bare (not wrapped in an ExceptionGroup) — the task group is never entered."""

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
    """Before the fix, read_stream was never closed — not even on the happy path. No messages
    are sent, so no network connection is attempted (streamable_http connects lazily)."""
    with _assert_no_memory_stream_leak():
        async with streamable_http_client("http://127.0.0.1:1/mcp"):
            pass
