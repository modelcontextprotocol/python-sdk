from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp.server.context import ServerRequestContext
from mcp.server.mcpserver import Context

pytestmark = pytest.mark.anyio


async def test_progress_token_zero_first_call():
    """Regression: progress reporting must not be gated on a falsy token.

    Issue #176: the original Context.report_progress treated token 0 as "no token" and
    silently dropped progress. Context now delegates unconditionally to
    ServerSession.report_progress (which calls DispatchContext.progress, whose JSONRPC
    implementation gates on `is None`, not truthiness), so a request whose meta carries
    a 0-valued token still emits all three reports.
    """
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
