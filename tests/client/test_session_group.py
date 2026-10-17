import contextlib
from unittest import mock

import anyio
import httpx2
import mcp_types as types
import pytest

import mcp
from mcp.client.session_group import (
    ClientSessionGroup,
    ClientSessionParameters,
    SseServerParameters,
    StreamableHttpParameters,
)
from mcp.client.stdio import StdioServerParameters
from mcp.server import Server, ServerRequestContext
from mcp.shared.exceptions import MCPError


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


@pytest.mark.anyio
@pytest.mark.filterwarnings("ignore:Passing 'msg' argument.*:DeprecationWarning")
async def test_disconnect_removes_all_tools_after_same_session_reregistration() -> None:
    """Reproduce the SDK cleanup gap after a caller re-registers a session with changed tools."""
    catalog = [types.Tool(name="old", input_schema={"type": "object"})]

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=list(catalog))

    async def list_resources(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=[])

    async def list_prompts(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListPromptsResult:
        return types.ListPromptsResult(prompts=[])

    server = Server(
        "mutable-catalog",
        on_list_tools=list_tools,
        on_list_resources=list_resources,
        on_list_prompts=list_prompts,
    )
    group = ClientSessionGroup()
    with anyio.fail_after(5):
        async with mcp.Client(server) as client:
            server_info = types.Implementation(name="mutable-catalog", version="1")
            await group.connect_with_session(server_info, client.session)

            catalog[:] = [types.Tool(name="new", input_schema={"type": "object"})]
            await group.connect_with_session(server_info, client.session)

            await group.disconnect_from_server(client.session)

    assert group.sessions == []
    assert group.tools == {}


@pytest.mark.anyio
async def test_disconnect_removes_all_tools_after_same_session_reregistration_mock() -> None:
    """Verify disconnecting after re-registering a session removes all tools (mock-based)."""
    server_info = types.Implementation(name="TestServer", version="1.0")
    mock_session = mock.AsyncMock(spec=mcp.ClientSession)

    old_tool = types.Tool(name="old", input_schema={})
    new_tool = types.Tool(name="new", input_schema={})

    mock_session.list_tools.return_value = types.ListToolsResult(tools=[old_tool])
    mock_session.list_resources.return_value = types.ListResourcesResult(resources=[])
    mock_session.list_prompts.return_value = types.ListPromptsResult(prompts=[])

    group = ClientSessionGroup()
    await group.connect_with_session(server_info, mock_session)
    assert group.tools == {"old": old_tool}
    assert group._tool_to_session == {"old": mock_session}
    assert group._sessions[mock_session].tools == {"old"}
    assert group.sessions == [mock_session]

    # Re-register same session with changed catalog (disjoint tools)
    mock_session.list_tools.return_value = types.ListToolsResult(tools=[new_tool])
    await group.connect_with_session(server_info, mock_session)
    assert group.tools == {"new": new_tool}
    assert "old" not in group.tools
    assert group._tool_to_session == {"new": mock_session}
    assert "old" not in group._tool_to_session
    assert group._sessions[mock_session].tools == {"new"}
    assert group.sessions == [mock_session]

    # Disconnect removes all tools belonging to the session
    await group.disconnect_from_server(mock_session)
    assert group.sessions == []
    assert group.tools == {}
    assert group._tool_to_session == {}
    assert mock_session not in group._sessions


@pytest.mark.anyio
async def test_connect_with_session_collision_with_other_session_raises() -> None:
    """Verify that re-registering raises MCPError if a component collides with another session."""
    server_info_1 = types.Implementation(name="Server1", version="1.0")
    session_1 = mock.AsyncMock(spec=mcp.ClientSession)
    tool_shared = types.Tool(name="shared_tool", input_schema={})
    session_1.list_tools.return_value = types.ListToolsResult(tools=[tool_shared])
    session_1.list_resources.return_value = types.ListResourcesResult(resources=[])
    session_1.list_prompts.return_value = types.ListPromptsResult(prompts=[])

    server_info_2 = types.Implementation(name="Server2", version="1.0")
    session_2 = mock.AsyncMock(spec=mcp.ClientSession)
    tool_other = types.Tool(name="other_tool", input_schema={})
    session_2.list_tools.return_value = types.ListToolsResult(tools=[tool_other])
    session_2.list_resources.return_value = types.ListResourcesResult(resources=[])
    session_2.list_prompts.return_value = types.ListPromptsResult(prompts=[])

    group = ClientSessionGroup()
    await group.connect_with_session(server_info_1, session_1)
    await group.connect_with_session(server_info_2, session_2)

    # Initial invariant checks
    assert group.tools == {"shared_tool": tool_shared, "other_tool": tool_other}
    assert group._tool_to_session == {"shared_tool": session_1, "other_tool": session_2}
    assert group._sessions[session_1].tools == {"shared_tool"}
    assert group._sessions[session_2].tools == {"other_tool"}

    # Attempt to re-register session 2 with a tool that collides with session 1
    session_2.list_tools.return_value = types.ListToolsResult(tools=[tool_shared])
    with pytest.raises(MCPError) as excinfo:
        await group.connect_with_session(server_info_2, session_2)

    assert excinfo.value.error.code == types.INVALID_PARAMS
    assert "shared_tool" in excinfo.value.error.message

    # Assert full invariant: session 2's previous state must be completely preserved
    assert group.tools == {"shared_tool": tool_shared, "other_tool": tool_other}
    assert group._tool_to_session == {"shared_tool": session_1, "other_tool": session_2}
    assert group._sessions[session_1].tools == {"shared_tool"}
    assert group._sessions[session_2].tools == {"other_tool"}

    # Ensure colliding tool was NOT re-routed to session 2
    session_1.call_tool.return_value = types.CallToolResult(
        content=[types.TextContent(type="text", text="server_1_ok")]
    )
    call_result = await group.call_tool("shared_tool", {})
    assert isinstance(call_result.content[0], types.TextContent)
    assert call_result.content[0].text == "server_1_ok"
    session_1.call_tool.assert_awaited_once_with(
        "shared_tool",
        arguments={},
        read_timeout_seconds=None,
        progress_callback=None,
        input_responses=None,
        request_state=None,
        meta=None,
        allow_input_required=False,
    )
    session_2.call_tool.assert_not_called()


@pytest.mark.anyio
async def test_connect_with_session_reregister_refreshes_all_components() -> None:
    """Verify that re-registering refreshes prompts, resources, and tools without false collision."""
    server_info = types.Implementation(name="TestServer", version="1.0")
    session = mock.AsyncMock(spec=mcp.ClientSession)

    tool_1 = types.Tool(name="tool_1", input_schema={})
    res_1 = types.Resource(uri="file:///res1", name="res_1")
    prompt_1 = types.Prompt(name="prompt_1")

    session.list_tools.return_value = types.ListToolsResult(tools=[tool_1])
    session.list_resources.return_value = types.ListResourcesResult(resources=[res_1])
    session.list_prompts.return_value = types.ListPromptsResult(prompts=[prompt_1])

    group = ClientSessionGroup()
    await group.connect_with_session(server_info, session)

    # Invariant checks for initial state
    assert group.tools == {"tool_1": tool_1}
    assert group.resources == {"res_1": res_1}
    assert group.prompts == {"prompt_1": prompt_1}
    assert group._tool_to_session == {"tool_1": session}
    assert group._sessions[session].tools == {"tool_1"}
    assert group._sessions[session].resources == {"res_1"}
    assert group._sessions[session].prompts == {"prompt_1"}

    # Re-register with updated components
    tool_2 = types.Tool(name="tool_2", input_schema={})
    res_2 = types.Resource(uri="file:///res2", name="res_2")
    prompt_2 = types.Prompt(name="prompt_2")

    session.list_tools.return_value = types.ListToolsResult(tools=[tool_2])
    session.list_resources.return_value = types.ListResourcesResult(resources=[res_2])
    session.list_prompts.return_value = types.ListPromptsResult(prompts=[prompt_2])

    await group.connect_with_session(server_info, session)

    # Invariant checks after refresh
    assert group.tools == {"tool_2": tool_2}
    assert group.resources == {"res_2": res_2}
    assert group.prompts == {"prompt_2": prompt_2}
    assert "tool_1" not in group.tools
    assert "res_1" not in group.resources
    assert "prompt_1" not in group.prompts
    assert group._tool_to_session == {"tool_2": session}
    assert "tool_1" not in group._tool_to_session
    assert group._sessions[session].tools == {"tool_2"}
    assert group._sessions[session].resources == {"res_2"}
    assert group._sessions[session].prompts == {"prompt_2"}

    # Verify call_tool routing via _tool_to_session
    session.call_tool.return_value = types.CallToolResult(content=[types.TextContent(type="text", text="tool_2_ok")])
    call_res = await group.call_tool("tool_2", {"arg": "val"})
    assert isinstance(call_res.content[0], types.TextContent)
    assert call_res.content[0].text == "tool_2_ok"
    session.call_tool.assert_awaited_once_with(
        "tool_2",
        arguments={"arg": "val"},
        read_timeout_seconds=None,
        progress_callback=None,
        input_responses=None,
        request_state=None,
        meta=None,
        allow_input_required=False,
    )

    # Calling evicted tool fails
    with pytest.raises(KeyError):
        await group.call_tool("tool_1", {})


@pytest.mark.anyio
async def test_connect_with_session_reregister_with_name_hook() -> None:
    """Verify re-registration respects component_name_hook and cleans up hooked names."""

    def name_hook(name: str, server_info: types.Implementation) -> str:
        return f"{server_info.name}.{name}"

    server_info = types.Implementation(name="MyServer", version="1.0")
    session = mock.AsyncMock(spec=mcp.ClientSession)

    tool_a = types.Tool(name="alpha", input_schema={})
    session.list_tools.return_value = types.ListToolsResult(tools=[tool_a])
    session.list_resources.return_value = types.ListResourcesResult(resources=[])
    session.list_prompts.return_value = types.ListPromptsResult(prompts=[])

    group = ClientSessionGroup(component_name_hook=name_hook)
    await group.connect_with_session(server_info, session)
    assert group.tools == {"MyServer.alpha": tool_a}
    assert group._tool_to_session == {"MyServer.alpha": session}
    assert group._sessions[session].tools == {"MyServer.alpha"}

    tool_b = types.Tool(name="beta", input_schema={})
    session.list_tools.return_value = types.ListToolsResult(tools=[tool_b])

    await group.connect_with_session(server_info, session)
    assert group.tools == {"MyServer.beta": tool_b}
    assert "MyServer.alpha" not in group.tools
    assert group._tool_to_session == {"MyServer.beta": session}
    assert "MyServer.alpha" not in group._tool_to_session
    assert group._sessions[session].tools == {"MyServer.beta"}

    session.call_tool.return_value = types.CallToolResult(content=[types.TextContent(type="text", text="beta_ok")])
    call_res = await group.call_tool("MyServer.beta", {})
    assert isinstance(call_res.content[0], types.TextContent)
    assert call_res.content[0].text == "beta_ok"
    session.call_tool.assert_awaited_once_with(
        "beta",
        arguments={},
        read_timeout_seconds=None,
        progress_callback=None,
        input_responses=None,
        request_state=None,
        meta=None,
        allow_input_required=False,
    )

    with pytest.raises(KeyError):
        await group.call_tool("MyServer.alpha", {})

    await group.disconnect_from_server(session)
    assert group.tools == {}
    assert group._tool_to_session == {}
    assert group.sessions == []


@pytest.mark.anyio
async def test_connect_with_session_empty_catalog() -> None:
    """Verify caller-owned session with empty catalog registers and refreshes without KeyError."""
    server_info = types.Implementation(name="EmptyServer", version="1.0")
    session = mock.AsyncMock(spec=mcp.ClientSession)
    session.list_tools.return_value = types.ListToolsResult(tools=[])
    session.list_resources.return_value = types.ListResourcesResult(resources=[])
    session.list_prompts.return_value = types.ListPromptsResult(prompts=[])

    group = ClientSessionGroup()
    # Connect with empty catalog — must not raise KeyError (:422-423 guard)
    await group.connect_with_session(server_info, session)
    assert group.tools == {}
    assert group.resources == {}
    assert group.prompts == {}
    assert group.sessions == [session]
    assert session not in group._session_exit_stacks

    # Refresh with a tool added
    sample_tool = types.Tool(name="sample", input_schema={})
    session.list_tools.return_value = types.ListToolsResult(tools=[sample_tool])
    await group.connect_with_session(server_info, session)
    assert group.tools == {"sample": sample_tool}

    # Refresh back to empty catalog — must not raise KeyError
    session.list_tools.return_value = types.ListToolsResult(tools=[])
    await group.connect_with_session(server_info, session)
    assert group.tools == {}
    assert "sample" not in group.tools
    assert group.sessions == [session]

    await group.disconnect_from_server(session)
    assert group.sessions == []


@pytest.mark.anyio
async def test_connect_to_server_empty_catalog(mock_exit_stack: contextlib.AsyncExitStack) -> None:
    """Verify group-owned connect_to_server with empty catalog retains exit stack and cleans up on disconnect."""
    mock_server_info = mock.Mock(spec=types.Implementation)
    mock_server_info.name = "EmptyServer"
    mock_session = mock.AsyncMock(spec=mcp.ClientSession)
    mock_session.list_tools.return_value = types.ListToolsResult(tools=[])
    mock_session.list_resources.return_value = types.ListResourcesResult(resources=[])
    mock_session.list_prompts.return_value = types.ListPromptsResult(prompts=[])

    session_stack = mock.AsyncMock(spec=contextlib.AsyncExitStack)

    async def fake_establish(*args: object, **kwargs: object) -> tuple[types.Implementation, mock.AsyncMock]:
        group._session_exit_stacks[mock_session] = session_stack
        return mock_server_info, mock_session

    group = ClientSessionGroup(exit_stack=mock_exit_stack)
    with mock.patch.object(group, "_establish_session", side_effect=fake_establish):
        await group.connect_to_server(StdioServerParameters(command="test"))

    assert mock_session in group._session_exit_stacks
    assert group.tools == {}
    assert group.sessions == [mock_session]

    await group.disconnect_from_server(mock_session)
    session_stack.aclose.assert_awaited_once()
    assert mock_session not in group._session_exit_stacks
    assert group.sessions == []


@pytest.mark.anyio
async def test_group_owned_session_refreshed_to_empty_and_disconnected_cleans_up(
    mock_exit_stack: contextlib.AsyncExitStack,
) -> None:
    """Verify group-owned session refreshed to empty catalog retains exit stack and closes it on disconnect."""
    mock_server_info = mock.Mock(spec=types.Implementation)
    mock_server_info.name = "TestServer"
    mock_session = mock.AsyncMock(spec=mcp.ClientSession)
    initial_tool = types.Tool(name="initial_tool", input_schema={})
    mock_session.list_tools.return_value = types.ListToolsResult(tools=[initial_tool])
    mock_session.list_resources.return_value = types.ListResourcesResult(resources=[])
    mock_session.list_prompts.return_value = types.ListPromptsResult(prompts=[])

    session_stack = mock.AsyncMock(spec=contextlib.AsyncExitStack)

    async def fake_establish(*args: object, **kwargs: object) -> tuple[types.Implementation, mock.AsyncMock]:
        group._session_exit_stacks[mock_session] = session_stack
        return mock_server_info, mock_session

    group = ClientSessionGroup(exit_stack=mock_exit_stack)
    with mock.patch.object(group, "_establish_session", side_effect=fake_establish):
        await group.connect_to_server(StdioServerParameters(command="test"))

    assert mock_session in group._session_exit_stacks
    assert group.tools == {"initial_tool": initial_tool}
    assert group.sessions == [mock_session]

    # Refresh to empty catalog
    mock_session.list_tools.return_value = types.ListToolsResult(tools=[])
    await group.connect_with_session(mock_server_info, mock_session)

    assert group.tools == {}
    assert group.sessions == [mock_session]
    # Exit stack must NOT be deleted without closing
    assert mock_session in group._session_exit_stacks
    session_stack.aclose.assert_not_called()

    # Disconnect must close the exit stack
    await group.disconnect_from_server(mock_session)
    session_stack.aclose.assert_awaited_once()
    assert mock_session not in group._session_exit_stacks
    assert group.sessions == []


@pytest.mark.anyio
async def test_connect_with_session_failed_refresh_preserves_existing_components() -> None:
    """Verify that MCPError when fetching components during refresh preserves existing registrations."""
    server_info = types.Implementation(name="TestServer", version="1.0")
    session = mock.AsyncMock(spec=mcp.ClientSession)

    initial_prompt = types.Prompt(name="orig_prompt")
    initial_resource = types.Resource(uri="file:///orig_resource", name="orig_res")
    initial_tool = types.Tool(name="orig_tool", input_schema={})

    session.list_prompts.return_value = types.ListPromptsResult(prompts=[initial_prompt])
    session.list_resources.return_value = types.ListResourcesResult(resources=[initial_resource])
    session.list_tools.return_value = types.ListToolsResult(tools=[initial_tool])

    group = ClientSessionGroup()
    await group.connect_with_session(server_info, session)

    assert group.prompts == {"orig_prompt": initial_prompt}
    assert group.resources == {"orig_res": initial_resource}
    assert group.tools == {"orig_tool": initial_tool}
    assert group._tool_to_session == {"orig_tool": session}
    assert group.sessions == [session]

    # Simulate MCPError on all component listings during refresh
    session.list_prompts.side_effect = MCPError(code=types.INTERNAL_ERROR, message="prompts failed")
    session.list_resources.side_effect = MCPError(code=types.INTERNAL_ERROR, message="resources failed")
    session.list_tools.side_effect = MCPError(code=types.INTERNAL_ERROR, message="tools failed")

    await group.connect_with_session(server_info, session)

    # Invariants: existing components are preserved, not evicted
    assert group.prompts == {"orig_prompt": initial_prompt}
    assert group.resources == {"orig_res": initial_resource}
    assert group.tools == {"orig_tool": initial_tool}
    assert group._tool_to_session == {"orig_tool": session}
    assert group._sessions[session].prompts == {"orig_prompt"}
    assert group._sessions[session].resources == {"orig_res"}
    assert group._sessions[session].tools == {"orig_tool"}
    assert group.sessions == [session]

    # Preserved tools remain callable and routed
    session.call_tool.return_value = types.CallToolResult(content=[types.TextContent(type="text", text="ok")])
    call_res = await group.call_tool("orig_tool", {})
    assert isinstance(call_res.content[0], types.TextContent)
    assert call_res.content[0].text == "ok"

    # Disconnect cleans up preserved components completely
    await group.disconnect_from_server(session)
    assert group.prompts == {}
    assert group.resources == {}
    assert group.tools == {}
    assert group._tool_to_session == {}
    assert group.sessions == []


@pytest.mark.anyio
async def test_connect_with_session_initial_fetch_mcperror_handled() -> None:
    """Verify that MCPError on initial component queries is handled gracefully without error."""
    server_info = types.Implementation(name="ErrorServer", version="1.0")
    session = mock.AsyncMock(spec=mcp.ClientSession)

    session.list_prompts.side_effect = MCPError(code=types.INTERNAL_ERROR, message="no prompts")
    session.list_resources.side_effect = MCPError(code=types.INTERNAL_ERROR, message="no resources")
    session.list_tools.side_effect = MCPError(code=types.INTERNAL_ERROR, message="no tools")

    group = ClientSessionGroup()
    await group.connect_with_session(server_info, session)

    assert group.prompts == {}
    assert group.resources == {}
    assert group.tools == {}
    assert group._tool_to_session == {}
    assert group.sessions == [session]

    await group.disconnect_from_server(session)
    assert group.sessions == []
