from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp.server.fastmcp import Context
from mcp.shared.context import RequestContext

pytestmark = pytest.mark.anyio


async def test_report_progress_passes_related_request_id():
    """Test that Context.report_progress() passes related_request_id to
    send_progress_notification so that progress notifications are correctly
    routed in stateless HTTP / SSE transports.

    Regression test for https://github.com/modelcontextprotocol/python-sdk/issues/2001
    """
    mock_session = AsyncMock()
    mock_session.send_progress_notification = AsyncMock()

    mock_meta = MagicMock()
    mock_meta.progressToken = "test-progress-token"

    request_context = RequestContext(
        request_id="req-42",
        session=mock_session,
        meta=mock_meta,
        lifespan_context=None,
    )

    ctx = Context(request_context=request_context, fastmcp=MagicMock())

    await ctx.report_progress(0.5, total=1.0, message="halfway")

    mock_session.send_progress_notification.assert_called_once_with(
        progress_token="test-progress-token",
        progress=0.5,
        total=1.0,
        message="halfway",
        related_request_id="req-42",
    )
