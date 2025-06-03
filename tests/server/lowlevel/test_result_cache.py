import pytest
from mcp import types
from mcp.server.lowlevel.result_cache import ResultCache
from unittest.mock import AsyncMock, Mock, patch
from contextlib import AsyncExitStack

@pytest.mark.anyio
async def test_async_call():
    """Tests basic async call"""
    async def test_call(call: types.CallToolRequest) -> types.ServerResult:
        return types.ServerResult(types.CallToolResult(
            content=[types.TextContent(
                type="text",
                text="test"
            )]
        ))
    async_call = types.CallToolAsyncRequest(
        method="tools/async/call",
        params=types.CallToolAsyncRequestParams(
            name="test"
        )
    )

    mock_session = AsyncMock()
    mock_context = Mock()
    mock_context.session = mock_session
    result_cache = ResultCache(max_size=1, max_keep_alive=1)
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(result_cache)
        async_call_ref = await result_cache.start_call(test_call, async_call, mock_context)
        assert async_call_ref.token is not None

        result = await result_cache.get_result(types.GetToolAsyncResultRequest(
            method="tools/async/get",
            params=types.GetToolAsyncResultRequestParams(
                token = async_call_ref.token
            )
        ))

        assert not result.isError
        assert not result.isPending
        assert len(result.content) == 1
        assert type(result.content[0]) is types.TextContent
        assert result.content[0].text == "test"

@pytest.mark.anyio
async def test_async_join_call_progress():
    """Tests basic async call"""
    async def test_call(call: types.CallToolRequest) -> types.ServerResult:
        return types.ServerResult(types.CallToolResult(
            content=[types.TextContent(
                type="text",
                text="test"
            )]
        ))
    async_call = types.CallToolAsyncRequest(
        method="tools/async/call",
        params=types.CallToolAsyncRequestParams(
            name="test"
        )
    )

    mock_session_1 = AsyncMock()
    mock_context_1 = Mock()
    mock_context_1.session = mock_session_1

    mock_session_2 = AsyncMock()
    mock_context_2 = Mock()

    mock_context_2.session = mock_session_2
    mock_session_2.send_progress_notification.result = None

    result_cache = ResultCache(max_size=1, max_keep_alive=1)
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(result_cache)
        async_call_ref = await result_cache.start_call(test_call, async_call, mock_context_1)
        assert async_call_ref.token is not None

        await result_cache.join_call(
            req=types.JoinCallToolAsyncRequest(
                method="tools/async/join",
                params=types.JoinCallToolRequestParams(
                    token=async_call_ref.token,
                    _meta = types.RequestParams.Meta(
                        progressToken="test"
                    )
                )
            ),
            ctx=mock_context_2
        )
        assert async_call_ref.token is not None
        await result_cache.notification_hook(
            session=mock_session_1, 
            notification=types.ServerNotification(types.ProgressNotification(
                method="notifications/progress",
                params=types.ProgressNotificationParams(
                    progressToken="test",
                    progress=1
                )
            )))

        result = await result_cache.get_result(types.GetToolAsyncResultRequest(
            method="tools/async/get",
            params=types.GetToolAsyncResultRequestParams(
                token = async_call_ref.token
            )
        ))

        assert not result.isError
        assert not result.isPending
        assert len(result.content) == 1
        assert type(result.content[0]) is types.TextContent
        assert result.content[0].text == "test"
        mock_context_1.send_progress_notification.assert_not_called()
        mock_session_2.send_progress_notification.assert_called_with(
            progress_token="test", 
            progress=1.0, 
            total=None, 
            message=None, 
            resource_uri = None
        )
