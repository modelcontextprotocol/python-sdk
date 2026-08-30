"""Tests for GET stream handling when the server rejects GET with 405.

Some production MCP servers (e.g. GitHub Copilot's MCP endpoint) do not offer
a server-initiated SSE stream and answer every GET with ``405 Method Not
Allowed``. Per the Streamable HTTP spec, 405 is the server's definitive way of
saying "no GET stream", so the client must not keep retrying: it burns the
reconnection budget on every session and spams logs with reconnect noise.
"""

import time
from typing import Any, cast
from unittest.mock import MagicMock

import httpx2
import pytest

from mcp.client.streamable_http import StreamableHTTPTransport


class _FailingEventSource:
    """Async context manager that raises immediately on ``__aenter__``."""

    def __init__(self, error: Exception, counter: list[int]) -> None:
        self._error = error
        self._counter = counter

    async def __aenter__(self) -> None:
        self._counter[0] += 1
        raise self._error

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


class _FailingClient:
    def __init__(self, error: Exception, counter: list[int]) -> None:
        self._error = error
        self._counter = counter

    def sse(self, url: str, headers: dict[str, str] | None = None) -> _FailingEventSource:
        return _FailingEventSource(self._error, self._counter)


def _status_error(status_code: int) -> httpx2.HTTPStatusError:
    request = httpx2.Request("GET", "http://localhost:8000/mcp")
    response = httpx2.Response(status_code, request=request)
    return httpx2.HTTPStatusError(
        f"Server returned status {status_code}", request=request, response=response
    )


@pytest.mark.anyio
async def test_get_stream_405_disables_retry() -> None:
    """405 on GET is definitive: stop retrying instead of exhausting attempts."""
    transport = StreamableHTTPTransport("http://localhost:8000/mcp")
    transport.session_id = "session-1"

    attempts = [0]
    client = _FailingClient(_status_error(405), attempts)

    start = time.monotonic()
    await transport.handle_get_stream(client, cast(Any, MagicMock()))
    elapsed = time.monotonic() - start

    assert attempts == [1]  # no retry after a definitive 405
    assert elapsed < 1.0  # no reconnect backoff sleep


@pytest.mark.anyio
async def test_get_stream_other_http_errors_still_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-405 errors keep the existing bounded-retry behavior."""
    from mcp.client import streamable_http as sh

    monkeypatch.setattr(sh, "DEFAULT_RECONNECTION_DELAY_MS", 0)

    transport = StreamableHTTPTransport("http://localhost:8000/mcp")
    transport.session_id = "session-1"

    attempts = [0]
    client = _FailingClient(_status_error(500), attempts)

    await transport.handle_get_stream(client, cast(Any, MagicMock()))

    assert attempts == [sh.MAX_RECONNECTION_ATTEMPTS]
