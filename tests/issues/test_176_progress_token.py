from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp.server.fastmcp import Context
from mcp.shared.context import RequestContext

pytestmark = pytest.mark.anyio


async def test_progress_token_zero_first_call():
    """Test that progress notifications work when progress_token is 0 on first call."""

    # Create mock session with progress notification tracking
    mock_session = AsyncMock()
    mock_session.send_progress_notification = AsyncMock()

    # Create request context with progress token 0
    mock_meta = MagicMock()
    mock_meta.progressToken = 0  # This is the key test case - token is 0

    request_context = RequestContext(
        request_id="test-request",
        session=mock_session,
        meta=mock_meta,
        lifespan_context=None,
    )

    # Create context with our mocks
    ctx = Context(request_context=request_context, fastmcp=MagicMock())

    # Test progress reporting
    await ctx.report_progress(0, 10)  # First call with 0
    await ctx.report_progress(5, 10)  # Middle progress
    await ctx.report_progress(10, 10)  # Complete

    # Verify progress notifications
    assert (
        mock_session.send_progress_notification.call_count == 3
    ), "All progress notifications should be sent"
    mock_session.send_progress_notification.assert_any_call(
        progress_token=0, progress=0.0, total=10.0
    )
    mock_session.send_progress_notification.assert_any_call(
        progress_token=0, progress=5.0, total=10.0
    )
    mock_session.send_progress_notification.assert_any_call(
        progress_token=0, progress=10.0, total=10.0
    )
