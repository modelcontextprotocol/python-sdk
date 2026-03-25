"""MCPServer.run_stdio_async forwards optional stdin/stdout to stdio_server."""

from __future__ import annotations

import io
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import anyio
import pytest

from mcp.server.mcpserver import MCPServer


@pytest.mark.anyio
async def test_run_stdio_async_passes_streams_to_stdio_server(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    @asynccontextmanager
    async def spy_stdio_server(stdin=None, stdout=None):
        captured["stdin"] = stdin
        captured["stdout"] = stdout
        read_stream = AsyncMock()
        write_stream = AsyncMock()
        yield read_stream, write_stream

    async def noop_run(*_args, **_kwargs):
        return None

    monkeypatch.setattr("mcp.server.mcpserver.server.stdio_server", spy_stdio_server)

    server = MCPServer("test-stdio-spy")
    monkeypatch.setattr(server._lowlevel_server, "run", noop_run)
    monkeypatch.setattr(server._lowlevel_server, "create_initialization_options", lambda: object())

    sin = io.StringIO()
    sout = io.StringIO()
    await server.run_stdio_async(
        stdin=anyio.AsyncFile(sin),
        stdout=anyio.AsyncFile(sout),
    )

    assert captured["stdin"] is not None
    assert captured["stdout"] is not None
