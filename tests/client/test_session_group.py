import contextlib
from collections.abc import Generator
from typing import Any
from unittest import mock

import anyio
import httpx2
import mcp_types as types
import pytest
from starlette.types import ASGIApp, Receive, Scope, Send

import mcp
import mcp.shared._httpx_utils as httpx_utils
from mcp.client.session_group import (
    ClientSessionGroup,
    ClientSessionParameters,
    SseServerParameters,
    StreamableHttpParameters,
)
from mcp.client.stdio import StdioServerParameters
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError
from tests.interaction._connect import BASE_URL, build_sse_app
from tests.interaction.transports import StreamingASGITransport


@pytest.fixture
def mock_exit_stack():
    """Fixture for a mocked AsyncExitStack."""
    # Use unittest.mock.Mock directly if needed, or just a plain object
    # if only attribute access/existence is needed.
    # For AsyncExitStack, Mock or MagicMock is usually fine.
    return mock.MagicMock(spec=contextlib.AsyncExitStack)


def test_client_session_group_init():
    mcp_session_group = ClientSessionGroup()
    assert not mcp_session_group._tools
    assert not mcp_session_group._resources
    assert not mcp_session_group._prompts
    assert not mcp_session_group._tool_to_session


def test_client_session_group_component_properties():
    # --- Mock Dependencies ---
    mock_prompt = mock.Mock()
    mock_resource = mock.Mock()
    mock_tool = mock.Mock()

    # --- Prepare Session Group ---
    mcp_session_group = ClientSessionGroup()
    mcp_session_group._prompts = {"my_prompt": mock_prompt}
    mcp_session_group._resources = {"my_resource": mock_resource}
    mcp_session_group._tools = {"my_tool": mock_tool}

    # --- Assertions ---
    assert mcp_session_group.prompts == {"my_prompt": mock_prompt}
    assert mcp_session_group.resources == {"my_resource": mock_resource}
    assert mcp_session_group.tools == {"my_tool": mock_tool}


@pytest.mark.anyio
async def test_client_session_group_call_tool():
    # --- Mock Dependencies ---
    mock_session = mock.AsyncMock()

    # --- Prepare Session Group ---
    def hook(name: str, server_info: types.Implementation) -> str:  # pragma: no cover
        return f"{(server_info.name)}-{name}"

    mcp_session_group = ClientSessionGroup(component_name_hook=hook)
    mcp_session_group._tools = {"server1-my_tool": types.Tool(name="my_tool", input_schema={})}
    mcp_session_group._tool_to_session = {"server1-my_tool": mock_session}
    text_content = types.TextContent(type="text", text="OK")
    mock_session.call_tool.return_value = types.CallToolResult(content=[text_content])

    # --- Test Execution ---
    result = await mcp_session_group.call_tool(
        name="server1-my_tool",
        arguments={
            "name": "value1",
            "args": {},
        },
    )

    # --- Assertions ---
    assert result.content == [text_content]
    mock_session.call_tool.assert_called_once_with(
        "my_tool",
        arguments={"name": "value1", "args": {}},
        read_timeout_seconds=None,
        progress_callback=None,
        input_responses=None,
        request_state=None,
        meta=None,
        allow_input_required=False,
    )


@pytest.mark.anyio
async def test_client_session_group_call_tool_forwards_allow_input_required():
    mock_session = mock.AsyncMock()
    mcp_session_group = ClientSessionGroup()
    mcp_session_group._tools = {"my_tool": types.Tool(name="my_tool", input_schema={})}
    mcp_session_group._tool_to_session = {"my_tool": mock_session}
    mock_session.call_tool.return_value = types.InputRequiredResult(request_state="s")

    result = await mcp_session_group.call_tool(name="my_tool", arguments={}, allow_input_required=True)
    assert isinstance(result, types.InputRequiredResult)
    assert result.request_state == "s"
    assert mock_session.call_tool.call_args.kwargs["allow_input_required"] is True


@pytest.mark.anyio
async def test_client_session_group_connect_to_server(mock_exit_stack: contextlib.AsyncExitStack):
    """Test connecting to a server and aggregating components."""
    # --- Mock Dependencies ---
    mock_server_info = mock.Mock(spec=types.Implementation)
    mock_server_info.name = "TestServer1"
    mock_session = mock.AsyncMock(spec=mcp.ClientSession)
    mock_tool1 = mock.Mock(spec=types.Tool)
    mock_tool1.name = "tool_a"
    mock_resource1 = mock.Mock(spec=types.Resource)
    mock_resource1.name = "resource_b"
    mock_prompt1 = mock.Mock(spec=types.Prompt)
    mock_prompt1.name = "prompt_c"
    mock_session.list_tools.return_value = mock.AsyncMock(tools=[mock_tool1])
    mock_session.list_resources.return_value = mock.AsyncMock(resources=[mock_resource1])
    mock_session.list_prompts.return_value = mock.AsyncMock(prompts=[mock_prompt1])

    # --- Test Execution ---
    group = ClientSessionGroup(exit_stack=mock_exit_stack)
    with mock.patch.object(group, "_establish_session", return_value=(mock_server_info, mock_session)):
        await group.connect_to_server(StdioServerParameters(command="test"))

    # --- Assertions ---
    assert mock_session in group._sessions
    assert len(group.tools) == 1
    assert "tool_a" in group.tools
    assert group.tools["tool_a"] == mock_tool1
    assert group._tool_to_session["tool_a"] == mock_session
    assert len(group.resources) == 1
    assert "resource_b" in group.resources
    assert group.resources["resource_b"] == mock_resource1
    assert len(group.prompts) == 1
    assert "prompt_c" in group.prompts
    assert group.prompts["prompt_c"] == mock_prompt1
    mock_session.list_tools.assert_awaited_once()
    mock_session.list_resources.assert_awaited_once()
    mock_session.list_prompts.assert_awaited_once()


@pytest.mark.anyio
async def test_client_session_group_connect_to_server_with_name_hook(mock_exit_stack: contextlib.AsyncExitStack):
    """Test connecting with a component name hook."""
    # --- Mock Dependencies ---
    mock_server_info = mock.Mock(spec=types.Implementation)
    mock_server_info.name = "HookServer"
    mock_session = mock.AsyncMock(spec=mcp.ClientSession)
    mock_tool = mock.Mock(spec=types.Tool)
    mock_tool.name = "base_tool"
    mock_session.list_tools.return_value = mock.AsyncMock(tools=[mock_tool])
    mock_session.list_resources.return_value = mock.AsyncMock(resources=[])
    mock_session.list_prompts.return_value = mock.AsyncMock(prompts=[])

    # --- Test Setup ---
    def name_hook(name: str, server_info: types.Implementation) -> str:
        return f"{server_info.name}.{name}"

    # --- Test Execution ---
    group = ClientSessionGroup(exit_stack=mock_exit_stack, component_name_hook=name_hook)
    with mock.patch.object(group, "_establish_session", return_value=(mock_server_info, mock_session)):
        await group.connect_to_server(StdioServerParameters(command="test"))

    # --- Assertions ---
    assert mock_session in group._sessions
    assert len(group.tools) == 1
    expected_tool_name = "HookServer.base_tool"
    assert expected_tool_name in group.tools
    assert group.tools[expected_tool_name] == mock_tool
    assert group._tool_to_session[expected_tool_name] == mock_session


@pytest.mark.anyio
async def test_client_session_group_disconnect_from_server():
    """Test disconnecting from a server."""
    # --- Test Setup ---
    group = ClientSessionGroup()
    server_name = "ServerToDisconnect"

    # Manually populate state using standard mocks
    mock_session1 = mock.MagicMock(spec=mcp.ClientSession)
    mock_session2 = mock.MagicMock(spec=mcp.ClientSession)
    mock_tool1 = mock.Mock(spec=types.Tool)
    mock_tool1.name = "tool1"
    mock_resource1 = mock.Mock(spec=types.Resource)
    mock_resource1.name = "res1"
    mock_prompt1 = mock.Mock(spec=types.Prompt)
    mock_prompt1.name = "prm1"
    mock_tool2 = mock.Mock(spec=types.Tool)
    mock_tool2.name = "tool2"
    mock_component_named_like_server = mock.Mock()
    mock_session = mock.Mock(spec=mcp.ClientSession)

    group._tools = {
        "tool1": mock_tool1,
        "tool2": mock_tool2,
        server_name: mock_component_named_like_server,
    }
    group._tool_to_session = {
        "tool1": mock_session1,
        "tool2": mock_session2,
        server_name: mock_session1,
    }
    group._resources = {
        "res1": mock_resource1,
        server_name: mock_component_named_like_server,
    }
    group._prompts = {
        "prm1": mock_prompt1,
        server_name: mock_component_named_like_server,
    }
    group._sessions = {
        mock_session: ClientSessionGroup._ComponentNames(
            prompts=set({"prm1"}),
            resources=set({"res1"}),
            tools=set({"tool1", "tool2"}),
        )
    }

    # --- Assertions ---
    assert mock_session in group._sessions
    assert "tool1" in group._tools
    assert "tool2" in group._tools
    assert "res1" in group._resources
    assert "prm1" in group._prompts

    # --- Test Execution ---
    await group.disconnect_from_server(mock_session)

    # --- Assertions ---
    assert mock_session not in group._sessions
    assert "tool1" not in group._tools
    assert "tool2" not in group._tools
    assert "res1" not in group._resources
    assert "prm1" not in group._prompts


@pytest.mark.anyio
async def test_client_session_group_connect_to_server_duplicate_tool_raises_error(
    mock_exit_stack: contextlib.AsyncExitStack,
):
    """Test MCPError raised when connecting a server with a dup name."""
    # --- Setup Pre-existing State ---
    group = ClientSessionGroup(exit_stack=mock_exit_stack)
    existing_tool_name = "shared_tool"
    # Manually add a tool to simulate a previous connection
    group._tools[existing_tool_name] = mock.Mock(spec=types.Tool)
    group._tools[existing_tool_name].name = existing_tool_name
    # Need a dummy session associated with the existing tool
    mock_session = mock.MagicMock(spec=mcp.ClientSession)
    group._tool_to_session[existing_tool_name] = mock_session
    group._session_exit_stacks[mock_session] = mock.Mock(spec=contextlib.AsyncExitStack)

    # --- Mock New Connection Attempt ---
    mock_server_info_new = mock.Mock(spec=types.Implementation)
    mock_server_info_new.name = "ServerWithDuplicate"
    mock_session_new = mock.AsyncMock(spec=mcp.ClientSession)

    # Configure the new session to return a tool with the *same name*
    duplicate_tool = mock.Mock(spec=types.Tool)
    duplicate_tool.name = existing_tool_name
    mock_session_new.list_tools.return_value = mock.AsyncMock(tools=[duplicate_tool])
    # Keep other lists empty for simplicity
    mock_session_new.list_resources.return_value = mock.AsyncMock(resources=[])
    mock_session_new.list_prompts.return_value = mock.AsyncMock(prompts=[])

    # --- Test Execution and Assertion ---
    with pytest.raises(MCPError) as excinfo:
        with mock.patch.object(
            group,
            "_establish_session",
            return_value=(mock_server_info_new, mock_session_new),
        ):
            await group.connect_to_server(StdioServerParameters(command="test"))

    # Assert details about the raised error
    assert excinfo.value.error.code == types.INVALID_PARAMS
    assert existing_tool_name in excinfo.value.error.message
    assert "already exist " in excinfo.value.error.message

    # Verify the duplicate tool was *not* added again (state should be unchanged)
    assert len(group._tools) == 1  # Should still only have the original
    assert group._tools[existing_tool_name] is not duplicate_tool  # Ensure it's the original mock


@pytest.mark.anyio
async def test_client_session_group_disconnect_non_existent_server():
    """Test disconnecting a server that isn't connected."""
    session = mock.Mock(spec=mcp.ClientSession)
    group = ClientSessionGroup()
    with pytest.raises(MCPError):
        await group.disconnect_from_server(session)


# TODO(Marcelo): This is horrible. We should drop this test.
@pytest.mark.anyio
@pytest.mark.parametrize(
    "server_params_instance, client_type_name, patch_target_for_client_func",
    [
        (
            StdioServerParameters(command="test_stdio_cmd"),
            "stdio",
            "mcp.client.session_group.mcp.stdio_client",
        ),
        (
            SseServerParameters(url="http://test.com/sse", timeout=10.0),
            "sse",
            "mcp.client.session_group.sse_client",
        ),  # url, headers, timeout, sse_read_timeout
        (
            StreamableHttpParameters(
                url="http://test.com/stream", terminate_on_close=False, max_sse_event_size=32 * 1024 * 1024
            ),
            "streamablehttp",
            "mcp.client.session_group.streamable_http_client",
        ),  # url, headers, timeout, sse_read_timeout, terminate_on_close
    ],
)
async def test_client_session_group_establish_session_parameterized(
    server_params_instance: StdioServerParameters | SseServerParameters | StreamableHttpParameters,
    client_type_name: str,  # Just for clarity or conditional logic if needed
    patch_target_for_client_func: str,
):
    with mock.patch("mcp.client.session_group.mcp.ClientSession") as mock_ClientSession_class:
        with mock.patch(patch_target_for_client_func) as mock_specific_client_func:
            mock_client_cm_instance = mock.AsyncMock(name=f"{client_type_name}ClientCM")
            mock_read_stream = mock.AsyncMock(name=f"{client_type_name}Read")
            mock_write_stream = mock.AsyncMock(name=f"{client_type_name}Write")

            # All client context managers return (read_stream, write_stream)
            mock_client_cm_instance.__aenter__.return_value = (mock_read_stream, mock_write_stream)

            mock_client_cm_instance.__aexit__ = mock.AsyncMock(return_value=None)
            mock_specific_client_func.return_value = mock_client_cm_instance

            # --- Mock mcp.ClientSession (class) ---
            # mock_ClientSession_class is already provided by the outer patch
            mock_raw_session_cm = mock.AsyncMock(name="RawSessionCM")
            mock_ClientSession_class.return_value = mock_raw_session_cm

            mock_entered_session = mock.AsyncMock(name="EnteredSessionInstance")
            mock_raw_session_cm.__aenter__.return_value = mock_entered_session
            mock_raw_session_cm.__aexit__ = mock.AsyncMock(return_value=None)

            # Mock session.initialize()
            mock_initialize_result = mock.AsyncMock(name="InitializeResult")
            mock_initialize_result.server_info = types.Implementation(name="foo", version="1")
            mock_entered_session.initialize.return_value = mock_initialize_result

            # --- Test Execution ---
            group = ClientSessionGroup()
            returned_server_info = None
            returned_session = None

            async with contextlib.AsyncExitStack() as stack:
                group._exit_stack = stack
                (
                    returned_server_info,
                    returned_session,
                ) = await group._establish_session(server_params_instance, ClientSessionParameters())

            # --- Assertions ---
            # 1. Assert the correct specific client function was called
            if client_type_name == "stdio":
                assert isinstance(server_params_instance, StdioServerParameters)
                mock_specific_client_func.assert_called_once_with(server_params_instance)
            elif client_type_name == "sse":
                assert isinstance(server_params_instance, SseServerParameters)
                mock_specific_client_func.assert_called_once_with(
                    url=server_params_instance.url,
                    headers=server_params_instance.headers,
                    timeout=server_params_instance.timeout,
                    sse_read_timeout=server_params_instance.sse_read_timeout,
                    auth=server_params_instance.auth,
                )
            elif client_type_name == "streamablehttp":  # pragma: no branch
                assert isinstance(server_params_instance, StreamableHttpParameters)
                # Verify streamable_http_client was called with url, httpx_client, and terminate_on_close
                # The http_client is created by the real create_mcp_http_client
                call_args = mock_specific_client_func.call_args
                assert call_args.kwargs["url"] == server_params_instance.url
                assert call_args.kwargs["terminate_on_close"] == server_params_instance.terminate_on_close
                assert call_args.kwargs["max_sse_event_size"] == server_params_instance.max_sse_event_size
                assert isinstance(call_args.kwargs["http_client"], httpx2.AsyncClient)

            mock_client_cm_instance.__aenter__.assert_awaited_once()

            # 2. Assert ClientSession was called correctly
            mock_ClientSession_class.assert_called_once_with(
                mock_read_stream,
                mock_write_stream,
                read_timeout_seconds=None,
                sampling_callback=None,
                elicitation_callback=None,
                list_roots_callback=None,
                logging_callback=None,
                message_handler=None,
                client_info=None,
            )
            mock_raw_session_cm.__aenter__.assert_awaited_once()
            mock_entered_session.initialize.assert_awaited_once()

            # 3. Assert returned values
            assert returned_server_info is mock_initialize_result.server_info
            assert returned_session is mock_entered_session


class _BearerAuth(httpx2.Auth):
    """Test auth handler. `__repr__` includes the token so a leak into `repr(params)` fails the test."""

    def __init__(self, token: str) -> None:
        self.token = token

    def __repr__(self) -> str:
        return f"_BearerAuth({self.token})"

    def auth_flow(self, request: httpx2.Request) -> Generator[httpx2.Request, httpx2.Response, None]:
        request.headers["Authorization"] = f"Bearer {self.token}"
        yield request


def _by_host(apps: dict[str, ASGIApp]) -> ASGIApp:
    """One ASGI app that forwards to the server for the request's host.

    Each HTTP client then owns a single streaming transport. One client entering several
    transports exits their cancel scopes from the wrong task.
    """

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return
        host = next(value.decode("latin-1") for name, value in scope["headers"] if name == b"host")
        await apps[host.split(":", 1)[0]](scope, receive, send)

    return app


def _recording_app(app: ASGIApp, authorizations: list[str | None], traces: list[str | None]) -> ASGIApp:
    async def wrapped(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = {name.decode("latin-1").lower(): value.decode("latin-1") for name, value in scope["headers"]}
            authorizations.append(headers.get("authorization"))
            traces.append(headers.get("x-trace-id"))
        await app(scope, receive, send)

    return wrapped


def _server(name: str, tool_name: str) -> MCPServer:
    server = MCPServer(name)

    @server.tool(name=tool_name)
    def _call() -> str:
        """Return the server name."""
        return name

    return server


def _streamable_app(server: MCPServer, authorizations: list[str | None], traces: list[str | None]) -> ASGIApp:
    app = server.streamable_http_app(
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )
    return _recording_app(app, authorizations, traces)


def _patch_in_process_clients(monkeypatch: pytest.MonkeyPatch, app: ASGIApp, *, cancel_on_close: bool) -> None:
    """Make `create_mcp_http_client` talk to `app`. The group builds that client itself."""

    class InProcessClient(httpx2.AsyncClient):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["transport"] = StreamingASGITransport(app, cancel_on_close=cancel_on_close)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx_utils.httpx2, "AsyncClient", InProcessClient)


def test_http_parameters_omit_auth_from_serialization() -> None:
    """`auth` stays on the object and off `model_dump`, `model_dump_json`, and `repr`.

    SDK-defined: the handler is not JSON and can hold a credential. `model_copy` keeps the same instance.
    """
    auth = _BearerAuth("secret-token")
    sse = SseServerParameters(url="http://example.test/sse", auth=auth)
    stream = StreamableHttpParameters(url="http://example.test/mcp", auth=auth)

    assert SseServerParameters(url="http://example.test/sse").auth is None
    assert StreamableHttpParameters(url="http://example.test/mcp").auth is None
    for params in (sse, stream):
        assert params.auth is auth
        assert params.model_copy().auth is auth
        assert "auth" not in params.model_dump()
        assert "secret-token" not in params.model_dump_json()
        assert "secret-token" not in repr(params)


@pytest.mark.anyio
async def test_streamable_http_group_sends_auth_and_keeps_other_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    """A streamable HTTP server sees the auth handler's bearer token, not a manual `Authorization` header.

    SDK-defined. `X-Trace-Id` from `headers=` is still sent. The group builds the HTTP client, so this
    test routes that client at an in-process app.
    """
    server = _server("Library", "search")
    authorizations: list[str | None] = []
    traces: list[str | None] = []
    app = _streamable_app(server, authorizations, traces)
    _patch_in_process_clients(monkeypatch, app, cancel_on_close=True)
    params = StreamableHttpParameters(
        url=f"{BASE_URL}/mcp",
        headers={"X-Trace-Id": "trace-1", "Authorization": "Bearer manual"},
        auth=_BearerAuth("from-auth"),
    )

    with anyio.fail_after(5):
        async with server.session_manager.run(), contextlib.AsyncExitStack() as stack:
            group = ClientSessionGroup(exit_stack=stack)
            await group.connect_to_server(params)
            result = await group.call_tool("search")

    assert result.structured_content == {"result": "Library"}
    assert authorizations
    assert set(authorizations) == {"Bearer from-auth"}
    assert set(traces) == {"trace-1"}


@pytest.mark.anyio
async def test_sse_group_sends_the_auth_handlers_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """An SSE server sees the bearer token from `SseServerParameters.auth`.

    SDK-defined. Same in-process route as the streamable HTTP test. `cancel_on_close` is false
    because the legacy SSE server only finishes the session after the GET observes a disconnect.
    """
    server = _server("Legacy", "search")
    app, _sse = build_sse_app(server)
    authorizations: list[str | None] = []
    traces: list[str | None] = []
    _patch_in_process_clients(monkeypatch, _recording_app(app, authorizations, traces), cancel_on_close=False)
    params = SseServerParameters(url=f"{BASE_URL}/sse", auth=_BearerAuth("sse-token"))

    with anyio.fail_after(5):
        async with contextlib.AsyncExitStack() as stack:
            group = ClientSessionGroup(exit_stack=stack)
            await group.connect_to_server(params)
            result = await group.call_tool("search")

    assert result.structured_content == {"result": "Legacy"}
    assert authorizations
    assert set(authorizations) == {"Bearer sse-token"}


@pytest.mark.anyio
async def test_each_server_in_a_group_uses_its_own_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two streamable HTTP servers in one group each see only the auth object they were given.

    SDK-defined. The handlers are distinct instances, so a token on one server is not the other's.
    """
    library = _server("Library", "library_search")
    web = _server("Web", "web_search")
    library_auth: list[str | None] = []
    web_auth: list[str | None] = []
    app = _by_host(
        {
            "library.example": _streamable_app(library, library_auth, []),
            "web.example": _streamable_app(web, web_auth, []),
        }
    )
    _patch_in_process_clients(monkeypatch, app, cancel_on_close=True)

    with anyio.fail_after(5):
        async with library.session_manager.run(), web.session_manager.run(), contextlib.AsyncExitStack() as stack:
            group = ClientSessionGroup(exit_stack=stack)
            await group.connect_to_server(
                StreamableHttpParameters(url="http://library.example/mcp", auth=_BearerAuth("library-token"))
            )
            await group.connect_to_server(
                StreamableHttpParameters(url="http://web.example/mcp", auth=_BearerAuth("web-token"))
            )
            library_result = await group.call_tool("library_search")
            web_result = await group.call_tool("web_search")

    assert library_result.structured_content == {"result": "Library"}
    assert web_result.structured_content == {"result": "Web"}
    assert set(library_auth) == {"Bearer library-token"}
    assert set(web_auth) == {"Bearer web-token"}
