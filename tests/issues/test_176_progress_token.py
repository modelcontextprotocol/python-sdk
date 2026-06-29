from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp.server.context import ServerRequestContext
from mcp.server.mcpserver import Context

pytestmark = pytest.mark.anyio


async def test_progress_token_zero_first_call():
    """Regression for issue #176: a 0-valued progress token must not be treated as falsy and dropped."""
    mock_session = AsyncMock()
    mock_session.report_progress = AsyncMock()

    request_context = ServerRequestContext(
        request_id="test-request",
        session=mock_session,
        method="tools/call",
        meta={"progress_token": 0},
        lifespan_context=None,
        protocol_version="2025-11-25",
    )

    ctx = Context(request_context=request_context, mcp_server=MagicMock())

    await ctx.report_progress(0, 10)
    await ctx.report_progress(5, 10)
    await ctx.report_progress(10, 10)

    assert mock_session.report_progress.await_args_list == [
        ((0, 10, None),),
        ((5, 10, None),),
        ((10, 10, None),),
    ]
