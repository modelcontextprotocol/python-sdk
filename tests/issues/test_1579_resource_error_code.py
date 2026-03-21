"""Tests for issue #1579: FastMCP read_resource() returns incorrect error code.

FastMCP previously returned error code 0 for resource-not-found because
ResourceError (an MCPServerError subclass) was caught by the generic
Exception handler in the low-level server, which defaults to code 0.

The fix adds a dedicated handler for MCPServerError that maps it to
INVALID_PARAMS (-32602), consistent with the TypeScript SDK and the
emerging spec consensus.
"""

import pytest

from mcp.client import Client
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS

pytestmark = pytest.mark.anyio


async def test_unknown_resource_returns_invalid_params_error_code():
    """Reading an unknown resource returns INVALID_PARAMS (-32602), not 0."""
    mcp = MCPServer()

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("resource://does-not-exist")

        assert exc_info.value.code == INVALID_PARAMS
        assert "Unknown resource" in exc_info.value.message


async def test_resource_read_error_returns_invalid_params_error_code():
    """A resource that raises during read returns INVALID_PARAMS (-32602)."""
    mcp = MCPServer()

    @mcp.resource("resource://failing")
    def failing_resource():
        raise RuntimeError("something broke")

    async with Client(mcp) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.read_resource("resource://failing")

        assert exc_info.value.code == INVALID_PARAMS
        assert "Error reading resource" in exc_info.value.message
