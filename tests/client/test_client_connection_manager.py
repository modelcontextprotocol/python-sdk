import asyncio
from unittest.mock import AsyncMock, patch

import pytest

import mcp
from mcp import types
from mcp.client.client_connection_manager import ClientConnectionManager, ClientSessionState
from mcp.client.exceptions import ConnectTimeOut
from mcp.shared.exceptions import McpError
from mcp.types import StreamalbeHttpClientParams


@pytest.fixture
def manager():
    return ClientConnectionManager()


@pytest.fixture
def mock_mcp_client_session():
    mock_session = AsyncMock(spec=mcp.ClientSession)
    mock_session.initialize.return_value = types.InitializeResult(
        capabilities=types.ServerCapabilities(),
        serverInfo=types.Implementation(name="1", version="2"),
        protocolVersion="1",
    )
    mock_session.send_ping.return_value = types.EmptyResult()
    mock_session.set_logging_level.return_value = types.EmptyResult()
    mock_session.list_resources.return_value = types.ListResourcesResult(resources=[])
    mock_session.read_resource.return_value = types.ReadResourceResult(contents=[])
    mock_session.call_tool.return_value = types.CallToolResult(content=[])
    mock_session.list_tools.return_value = types.ListToolsResult(tools=[])
    mock_session.list_prompts.return_value = types.ListPromptsResult(prompts=[])
    mock_session.get_prompt.return_value = types.GetPromptResult(messages=[])
    mock_session.send_roots_list_changed.return_value = None
    mock_session.subscribe_resource.return_value = types.EmptyResult()
    mock_session.unsubscribe_resource.return_value = types.EmptyResult()
    mock_session.send_progress_notification.return_value = None
    mock_session.__aenter__.return_value = mock_session
    mock_session.__aexit__.return_value = None

    return mock_session


@pytest.fixture
def mock_streamable_http_client():
    mock_read_stream = AsyncMock()
    mock_write_stream = AsyncMock()
    get_session_id_callback = AsyncMock()
    mock_streams = (mock_read_stream, mock_write_stream, get_session_id_callback)

    mock_client_context = AsyncMock()
    mock_client_context.__aenter__.return_value = mock_streams
    mock_client_context.__aexit__.return_value = None

    with patch(
        "mcp.client.client_connection_manager.streamablehttp_client", return_value=mock_client_context
    ) as mock_streamable_http_client:
        yield mock_streamable_http_client


@pytest.mark.anyio
async def test_connect_success(manager, mock_streamable_http_client, mock_mcp_client_session):
    session_name = "test_session_1"
    url = "http://mock1:8000/mcp/"

    param = StreamalbeHttpClientParams(name=session_name, url=url)

    with patch("mcp.client.client_connection_manager.mcp.ClientSession", return_value=mock_mcp_client_session):
        await manager.connect(param)

    assert session_name in manager._session

    state = manager._session[session_name]
    assert state.session is mock_mcp_client_session
    assert state.lifespan_task is not None
    assert not state.running_event.is_set()
    assert state.error is None

    mock_streamable_http_client.assert_called_once_with(param.url)

    await manager.disconnect(session_name)
    assert manager._session[session_name].session is None
    assert manager._session[session_name].lifespan_task is None


@pytest.mark.anyio
async def test_connect_duplicate_session_fails(manager, mock_streamable_http_client):
    session_name = "test_session_duplicate"

    param = StreamalbeHttpClientParams(name=session_name, url="http://localhost:8080")

    manager._session[session_name] = ClientSessionState()

    with pytest.raises(McpError) as excinfo:
        await manager.connect(param)

    assert "already exists" in str(excinfo.value)

    mock_streamable_http_client.assert_not_called()


@pytest.mark.anyio
async def test_connect_timeout_during_startup(manager, mock_streamable_http_client):
    session_name = "test_session_timeout"

    param = StreamalbeHttpClientParams(name=session_name, url="http://localhost:8080")

    async def never_set_result(*args, **kwargs):
        await asyncio.sleep(10)

    with patch.object(manager, "_maintain_session", AsyncMock(side_effect=never_set_result)):
        with pytest.raises(ConnectTimeOut):
            await manager.connect(param)

    assert session_name in manager._session

    assert manager._session[session_name].lifespan_task.done()
    assert str(manager._session[session_name].error) == f"Connection to {param.name} timed out"

    assert manager._session[session_name].lifespan_task.cancelled()


@pytest.mark.anyio
async def test_disconnect_success(manager, mock_streamable_http_client, mock_mcp_client_session):
    session_name = "test_session_disconnect"

    param = StreamalbeHttpClientParams(name=session_name, url="http://localhost:8080")

    with patch("mcp.client.client_connection_manager.mcp.ClientSession", return_value=mock_mcp_client_session):
        await manager.connect(param)

    assert session_name in manager._session

    assert manager._session[session_name].session is mock_mcp_client_session

    assert manager._session[session_name].lifespan_task is not None

    # disconnnect

    await manager.disconnect(session_name)
    assert manager._session[session_name].session is None
    assert manager._session[session_name].lifespan_task is None
    assert manager._session[session_name].running_event.is_set()

    mock_mcp_client_session.__aexit__.assert_called_once()
    mock_streamable_http_client.return_value.__aexit__.assert_called_once()


@pytest.mark.anyio
async def test_session_initialize_success(manager, mock_streamable_http_client, mock_mcp_client_session):
    session_name = "test_session_init"

    param = StreamalbeHttpClientParams(name=session_name, url="http://localhost:8080")

    with patch("mcp.client.client_connection_manager.mcp.ClientSession", return_value=mock_mcp_client_session):
        await manager.connect(param)
        await manager.session_initialize(session_name)

    mock_mcp_client_session.initialize.assert_called_once()


@pytest.mark.anyio
async def test_session_initialize_no_session(manager):
    with pytest.raises(McpError) as excinfo:
        await manager.session_initialize("non_existent_session")

    assert "does not exist" in str(excinfo.value)


@pytest.mark.anyio
async def test_session_initialize_with_error_state(manager, mock_streamable_http_client, mock_mcp_client_session):
    session_name = "test_session_error_state"

    param = StreamalbeHttpClientParams(name=session_name, url="http://localhost:8080")

    with patch("mcp.client.client_connection_manager.mcp.ClientSession", return_value=mock_mcp_client_session):
        await manager.connect(param)

    manager._session[session_name].error = RuntimeError("Simulated session error")

    with pytest.raises(McpError) as excinfo:
        await manager.session_initialize(session_name)

    assert "has error" in str(excinfo.value)

    mock_mcp_client_session.initialize.assert_not_called()


@pytest.mark.anyio
async def test_safe_run_task_propagates_session_error(manager, mock_streamable_http_client, mock_mcp_client_session):
    session_name = "test_safe_run_task_error"

    state = ClientSessionState()
    state.session = mock_mcp_client_session
    manager._session[session_name] = state

    async def mock_long_running_task():
        await asyncio.sleep(100)

    task_to_test = mock_long_running_task()

    safe_run_task_handle = asyncio.create_task(manager._safe_run_task(session_name, task_to_test))

    await asyncio.sleep(0.2)
    simulated_error = McpError(types.ErrorData(code=types.CONNECTION_CLOSED, message="Simulated network error"))
    manager._session[session_name].error = simulated_error

    with pytest.raises(McpError) as excinfo:
        await safe_run_task_handle

    assert excinfo.value == simulated_error
    assert safe_run_task_handle.done()
    assert manager._session[session_name].error is simulated_error
    print(manager._session[session_name].running_event.is_set())


@pytest.mark.anyio
async def test_maintain_session_handles_context_exception(manager):
    session_name = "test_session_error_state"

    param = StreamalbeHttpClientParams(name=session_name, url="http://localhost:8080")

    await manager.connect(param)

    with pytest.raises(Exception):
        await manager.session_initialize(session_name)

    assert manager._session[session_name].lifespan_task.done()
