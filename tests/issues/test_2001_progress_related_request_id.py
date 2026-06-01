# Regression test for issue #2001 - progress notifications via SSE in stateless HTTP
# Root cause: send_progress_notification() called without related_request_id.
# Fix: pass related_request_id=self.request_id - see mcpserver/context.py

from unittest.mock import AsyncMock, MagicMock

import pytest

from mcp.server.context import ServerRequestContext
from mcp.server.experimental.request_context import Experimental
from mcp.server.mcpserver import Context

pytestmark = pytest.mark.anyio

async def test_report_progress_passes_related_request_id() -> None:
      """report_progress must forward request_id as related_request_id."""
      mock_session = AsyncMock()
      mock_session.send_progress_notification = AsyncMock()
      request_context = ServerRequestContext(
      request_id="req-2001",
      session=mock_session,
      meta={"progress_token": "tok-progress"},
      lifespan_context=None,
      experimental=Experimental(),
      )
      ctx = Context(request_context=request_context, mcp_server=MagicMock())
      await ctx.report_progress(25, 100, message="quarter done")
      await ctx.report_progress(50, 100)
      await ctx.report_progress(100, 100, message="complete")
      assert mock_session.send_progress_notification.call_count == 3
      mock_session.send_progress_notification.assert_any_call(
      progress_token="tok-progress",
      progress=25.0,
      total=100.0,
      message="quarter done",
      related_request_id="req-2001",
      )
      mock_session.send_progress_notification.assert_any_call(
      progress_token="tok-progress",
      progress=50.0,
      total=100.0,
      message=None,
      related_request_id="req-2001",
      )
      mock_session.send_progress_notification.assert_any_call(
      progress_token="tok-progress",
      progress=100.0,
      total=100.0,
      message="complete",
      related_request_id="req-2001",
      )

async def test_report_progress_no_token_skips_notification() -> None:
      """report_progress is a no-op when no progress_token is present."""
      mock_session = AsyncMock()
      mock_session.send_progress_notification = AsyncMock()
      request_context = ServerRequestContext(
      request_id="req-no-token",
      session=mock_session,
      meta={},
      lifespan_context=None,
      experimental=Experimental(),
      )
      ctx = Context(request_context=request_context, mcp_server=MagicMock())
      await ctx.report_progress(50, 100)
mock_session.send_progress_notification.assert_not_called()

async def test_report_progress_integer_token() -> None:
      """report_progress works when progress_token is an integer (e.g. 0)."""
      mock_session = AsyncMock()
      mock_session.send_progress_notification = AsyncMock()
      request_context = ServerRequestContext(
      request_id="req-int-token",
      session=mock_session,
      meta={"progress_token": 0},
      lifespan_context=None,
      experimental=Experimental(),
      )
      ctx = Context(request_context=request_context, mcp_server=MagicMock())
      await ctx.report_progress(1, 10)
      mock_session.send_progress_notification.assert_awaited_once_with(
      progress_token=0,
      progress=1.0,
      total=10.0,
      message=None,
      related_request_id="req-int-token",
      )
