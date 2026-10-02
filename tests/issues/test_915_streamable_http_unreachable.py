"""Regression test for issue #915.

When a streamable HTTP MCP server is unreachable, httpx transport errors must
complete the pending JSON-RPC waiter instead of escaping into the outer task
group (which surfaces as an uncatchable cancel-scope RuntimeError).
"""

from __future__ import annotations

import anyio
import pytest
from mcp_types import INTERNAL_ERROR

from mcp.client.session_group import ClientSessionGroup, StreamableHttpParameters
from mcp.shared.exceptions import MCPError


@pytest.mark.anyio
async def test_unreachable_streamable_http_server_raises_catchable_error() -> None:
    async with ClientSessionGroup() as group:
        server_params = StreamableHttpParameters(url="http://127.0.0.1:1/mcp/")
        with anyio.fail_after(10):
            with pytest.raises(MCPError) as exc_info:
                await group.connect_to_server(server_params)

    assert exc_info.value.code == INTERNAL_ERROR
    assert "Transport error" in exc_info.value.message
