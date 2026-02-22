"""Tests for server-scoped lifespan functionality."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from mcp.server.lowlevel.server import Server
from mcp.server.server_lifespan import ServerLifespanManager, server_lifespan_context_var
from mcp.types import TextContent, CallToolResult, CallToolRequestParams


@pytest.mark.anyio
async def test_server_lifespan_runs_once_at_startup():
    """Test that server lifespan runs once and context is accessible."""

    @asynccontextmanager
    async def server_lifespan(server: Server) -> AsyncIterator[dict[str, str]]:
        """Server lifespan that sets up shared resource."""
        yield {"server_message": "Hello from server lifespan!"}

    manager = ServerLifespanManager(server_lifespan=server_lifespan)

    # Create a dummy server instance
    dummy_server = Server("test")

    # Run the server lifespan
    async with manager.run(dummy_server):
        # Context should be available
        context = manager.get_context()
        assert context == {"server_message": "Hello from server lifespan!"}

        # Context should also be available via context variable
        context_from_var = server_lifespan_context_var.get()
        assert context_from_var == {"server_message": "Hello from server lifespan!"}


@pytest.mark.anyio
async def test_server_lifespan_context_persists_across_sessions():
    """Test that server lifespan context is shared across multiple sessions."""

    @asynccontextmanager
    async def server_lifespan(server: Server) -> AsyncIterator[dict[str, int]]:
        """Server lifespan with a counter."""
        yield {"call_count": 0}

    manager = ServerLifespanManager(server_lifespan=server_lifespan)

    # Create a dummy server instance
    dummy_server = Server("test")

    async with manager.run(dummy_server):
        # First "session" - read and modify context
        context1 = manager.get_context()
        assert context1["call_count"] == 0
        # Note: We can't modify the context directly as it's yielded
        # But the same context object should be accessible

        # Second "session" - same context
        context2 = manager.get_context()
        assert context2 is context1  # Same object
        assert context2["call_count"] == 0


@pytest.mark.anyio
async def test_default_server_lifespan():
    """Test that default server lifespan works (does nothing)."""
    from mcp.server.server_lifespan import default_server_lifespan

    @asynccontextmanager
    async def dummy_server():
        yield

    async with default_server_lifespan(None):  # type: ignore
        # Should not raise any errors
        pass


@pytest.mark.anyio
async def test_get_context_raises_when_not_set():
    """Test that get_context raises LookupError when context not set."""
    from mcp.server.server_lifespan import ServerLifespanManager

    # Try to get context without running lifespan
    with pytest.raises(LookupError, match="Server lifespan context is not available"):
        ServerLifespanManager.get_context()
