from contextlib import AsyncExitStack
from unittest.mock import AsyncMock, Mock

import anyio
import pytest

from mcp import types
from mcp.server.lowlevel.result_cache import ResultCache


@pytest.mark.anyio
async def test_async_call():
    """Tests basic async call"""

    async def test_call(call: types.CallToolRequest) -> types.ServerResult:
        return types.ServerResult(
            types.CallToolResult(content=[types.TextContent(type="text", text="test")])
        )

    async_call = types.CallToolAsyncRequest(
        method="tools/async/call", params=types.CallToolAsyncRequestParams(name="test")
    )

    mock_session = AsyncMock()
    mock_context = Mock()
    mock_context.session = mock_session
    result_cache = ResultCache(max_size=1, max_keep_alive=1)
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(result_cache)
        async_call_ref = await result_cache.start_call(
            test_call, async_call, mock_context
        )
        assert async_call_ref.token is not None

        result = await result_cache.get_result(
            types.GetToolAsyncResultRequest(
                method="tools/async/get",
                params=types.GetToolAsyncResultRequestParams(
                    token=async_call_ref.token
                ),
            )
        )

        assert not result.isError
        assert not result.isPending
        assert len(result.content) == 1
        assert type(result.content[0]) is types.TextContent
        assert result.content[0].text == "test"


@pytest.mark.anyio
async def test_async_join_call_progress():
    """Tests basic async call"""

    async def test_call(call: types.CallToolRequest) -> types.ServerResult:
        return types.ServerResult(
            types.CallToolResult(content=[types.TextContent(type="text", text="test")])
        )

    async_call = types.CallToolAsyncRequest(
        method="tools/async/call", params=types.CallToolAsyncRequestParams(name="test")
    )

    mock_session_1 = AsyncMock()
    mock_context_1 = Mock()
    mock_context_1.session = mock_session_1

    mock_session_2 = AsyncMock()
    mock_context_2 = Mock()

    mock_context_2.session = mock_session_2

    result_cache = ResultCache(max_size=1, max_keep_alive=1)
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(result_cache)
        async_call_ref = await result_cache.start_call(
            test_call, async_call, mock_context_1
        )
        assert async_call_ref.token is not None

        await result_cache.join_call(
            req=types.JoinCallToolAsyncRequest(
                method="tools/async/join",
                params=types.JoinCallToolRequestParams(
                    token=async_call_ref.token,
                    _meta=types.RequestParams.Meta(progressToken="test"),
                ),
            ),
            ctx=mock_context_2,
        )
        assert async_call_ref.token is not None
        await result_cache.notification_hook(
            session=mock_session_1,
            notification=types.ServerNotification(
                types.ProgressNotification(
                    method="notifications/progress",
                    params=types.ProgressNotificationParams(
                        progressToken="test", progress=1
                    ),
                )
            ),
        )

        result = await result_cache.get_result(
            types.GetToolAsyncResultRequest(
                method="tools/async/get",
                params=types.GetToolAsyncResultRequestParams(
                    token=async_call_ref.token
                ),
            )
        )

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
            resource_uri=None,
        )


@pytest.mark.anyio
async def test_async_cancel_in_progress():
    """Tests cancelling an in progress async call"""

    async def slow_call(call: types.CallToolRequest) -> types.ServerResult:
        with anyio.move_on_after(10) as scope:
            await anyio.sleep(10)

        if scope.cancel_called:
            return types.ServerResult(
                types.CallToolResult(
                    content=[
                        types.TextContent(type="text", text="should be discarded")
                    ],
                    isError=True,
                )
            )
        else:
            return types.ServerResult(
                types.CallToolResult(
                    content=[types.TextContent(type="text", text="test")]
                )
            )

    async_call = types.CallToolAsyncRequest(
        method="tools/async/call", params=types.CallToolAsyncRequestParams(name="test")
    )

    mock_session_1 = AsyncMock()
    mock_context_1 = Mock()
    mock_context_1.session = mock_session_1

    result_cache = ResultCache(max_size=1, max_keep_alive=1)
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(result_cache)
        async_call_ref = await result_cache.start_call(
            slow_call, async_call, mock_context_1
        )
        assert async_call_ref.token is not None

        await result_cache.cancel(
            notification=types.CancelToolAsyncNotification(
                method="tools/async/cancel",
                params=types.CancelToolAsyncNotificationParams(
                    token=async_call_ref.token
                ),
            ),
        )

        assert async_call_ref.token is not None
        await result_cache.notification_hook(
            session=mock_session_1,
            notification=types.ServerNotification(
                types.ProgressNotification(
                    method="notifications/progress",
                    params=types.ProgressNotificationParams(
                        progressToken="test", progress=1
                    ),
                )
            ),
        )

        result = await result_cache.get_result(
            types.GetToolAsyncResultRequest(
                method="tools/async/get",
                params=types.GetToolAsyncResultRequestParams(
                    token=async_call_ref.token
                ),
            )
        )

        assert result.isError
        assert not result.isPending
        assert len(result.content) == 1
        assert type(result.content[0]) is types.TextContent
        assert result.content[0].text == "cancelled"


@pytest.mark.anyio
async def test_async_call_keep_alive():
    """Tests async call keep alive"""

    async def test_call(call: types.CallToolRequest) -> types.ServerResult:
        return types.ServerResult(
            types.CallToolResult(content=[types.TextContent(type="text", text="test")])
        )

    async_call = types.CallToolAsyncRequest(
        method="tools/async/call", params=types.CallToolAsyncRequestParams(name="test")
    )

    mock_session_1 = AsyncMock()
    mock_context_1 = Mock()
    mock_context_1.session = mock_session_1

    mock_session_2 = AsyncMock()
    mock_context_2 = Mock()

    mock_context_2.session = mock_session_2

    result_cache = ResultCache(max_size=1, max_keep_alive=10)
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(result_cache)
        async_call_ref = await result_cache.start_call(
            test_call, async_call, mock_context_1
        )
        assert async_call_ref.token is not None

        await result_cache.session_close_hook(mock_session_1)

        await result_cache.join_call(
            req=types.JoinCallToolAsyncRequest(
                method="tools/async/join",
                params=types.JoinCallToolRequestParams(
                    token=async_call_ref.token,
                    _meta=types.RequestParams.Meta(progressToken="test"),
                ),
            ),
            ctx=mock_context_2,
        )
        assert async_call_ref.token is not None
        await result_cache.notification_hook(
            session=mock_session_1,
            notification=types.ServerNotification(
                types.ProgressNotification(
                    method="notifications/progress",
                    params=types.ProgressNotificationParams(
                        progressToken="test", progress=1
                    ),
                )
            ),
        )

        result = await result_cache.get_result(
            types.GetToolAsyncResultRequest(
                method="tools/async/get",
                params=types.GetToolAsyncResultRequestParams(
                    token=async_call_ref.token
                ),
            )
        )

        assert not result.isError, str(result)
        assert not result.isPending
        assert len(result.content) == 1
        assert type(result.content[0]) is types.TextContent
        assert result.content[0].text == "test"


@pytest.mark.anyio
async def test_async_call_keep_alive_expired():
    """Tests async call keep alive expiry"""

    async def test_call(call: types.CallToolRequest) -> types.ServerResult:
        return types.ServerResult(
            types.CallToolResult(content=[types.TextContent(type="text", text="test")])
        )

    async_call = types.CallToolAsyncRequest(
        method="tools/async/call", params=types.CallToolAsyncRequestParams(name="test")
    )

    mock_session_1 = AsyncMock()
    mock_context_1 = Mock()
    mock_context_1.session = mock_session_1

    mock_session_2 = AsyncMock()
    mock_context_2 = Mock()
    mock_context_2.session = mock_session_2

    mock_session_3 = AsyncMock()
    mock_context_3 = Mock()
    mock_context_3.session = mock_session_3

    time = 0.0

    def test_timer():
        return time

    result_cache = ResultCache(max_size=1, max_keep_alive=1, timer=test_timer)
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(result_cache)
        async_call_ref = await result_cache.start_call(
            test_call, async_call, mock_context_1
        )
        assert async_call_ref.token is not None

        # lose the connection
        await result_cache.session_close_hook(mock_session_1)

        # reconnect before keep_alive_timeout
        time = 0.5
        await result_cache.join_call(
            req=types.JoinCallToolAsyncRequest(
                method="tools/async/join",
                params=types.JoinCallToolRequestParams(
                    token=async_call_ref.token,
                    _meta=types.RequestParams.Meta(progressToken="test"),
                ),
            ),
            ctx=mock_context_2,
        )

        result = await result_cache.get_result(
            types.GetToolAsyncResultRequest(
                method="tools/async/get",
                params=types.GetToolAsyncResultRequestParams(
                    token=async_call_ref.token
                ),
            )
        )

        # should successfully read data
        assert not result.isError, str(result)
        assert len(result.content) == 1
        assert type(result.content[0]) is types.TextContent
        assert result.content[0].text == "test"

        # lose connection a second time

        await result_cache.session_close_hook(mock_session_2)

        time = 2

        # reconnect after the keep_alive_timeout

        await result_cache.join_call(
            req=types.JoinCallToolAsyncRequest(
                method="tools/async/join",
                params=types.JoinCallToolRequestParams(
                    token=async_call_ref.token,
                    _meta=types.RequestParams.Meta(progressToken="test"),
                ),
            ),
            ctx=mock_context_3,
        )

        result = await result_cache.get_result(
            types.GetToolAsyncResultRequest(
                method="tools/async/get",
                params=types.GetToolAsyncResultRequestParams(
                    token=async_call_ref.token
                ),
            )
        )

        # now token should be expired
        assert result.isError, str(result)
        assert len(result.content) == 1
        assert type(result.content[0]) is types.TextContent
        assert result.content[0].text == "Unknown async token"
