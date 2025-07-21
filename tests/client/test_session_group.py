import contextlib
from unittest import mock

import pytest

import mcp
from mcp import types
from mcp.client.session_group import ClientSessionGroup, SseServerParameters, StreamableHttpParameters
from mcp.client.stdio import StdioServerParameters
from mcp.shared.exceptions import McpError


@pytest.fixture
def mock_exit_stack():
    """Fixture for a mocked AsyncExitStack."""
    # Use unittest.mock.Mock directly if needed, or just a plain object
    # if only attribute access/existence is needed.
    # For AsyncExitStack, Mock or MagicMock is usually fine.
    return mock.MagicMock(spec=contextlib.AsyncExitStack)


@pytest.mark.anyio
class TestClientSessionGroup:
    def test_init(self):
        mcp_session_group = ClientSessionGroup()
        assert not mcp_session_group._tools
        assert not mcp_session_group._resources
        assert not mcp_session_group._prompts
        assert not mcp_session_group._tool_to_session

    def test_component_properties(self):
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

    async def test_call_tool(self):
        # --- Mock Dependencies ---
        mock_session = mock.AsyncMock()

        # --- Prepare Session Group ---
        def hook(name: str, server_info: types.Implementation) -> str:
            return f"{(server_info.name)}-{name}"

        mcp_session_group = ClientSessionGroup(component_name_hook=hook)
        mcp_session_group._tools = {"server1-my_tool": types.Tool(name="my_tool", inputSchema={})}
        mcp_session_group._tool_to_session = {"server1-my_tool": mock_session}
        text_content = types.TextContent(type="text", text="OK")
        mock_session.call_tool.return_value = types.CallToolResult(content=[text_content])

        # --- Test Execution ---
        result = await mcp_session_group.call_tool(
            name="server1-my_tool",
            args={
                "name": "value1",
                "args": {},
            },
        )

        # --- Assertions ---
        assert result.content == [text_content]
        mock_session.call_tool.assert_called_once_with(
            "my_tool",
            {"name": "value1", "args": {}},
        )

    async def test_connect_to_server(self, mock_exit_stack: contextlib.AsyncExitStack):
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

    async def test_connect_to_server_with_name_hook(self, mock_exit_stack: contextlib.AsyncExitStack):
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

    async def test_disconnect_from_server(self):  # No mock arguments needed
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

    async def test_connect_to_server_duplicate_tool_raises_error(self, mock_exit_stack: contextlib.AsyncExitStack):
        """Test McpError raised when connecting a server with a dup name."""
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
        with pytest.raises(McpError) as excinfo:
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

    # No patching needed here
    async def test_disconnect_non_existent_server(self):
        """Test disconnecting a server that isn't connected."""
        session = mock.Mock(spec=mcp.ClientSession)
        group = ClientSessionGroup()
        with pytest.raises(McpError):
            await group.disconnect_from_server(session)

    @pytest.mark.parametrize(
        "server_params_instance, client_type_name, patch_target_for_client_func",
        [
            (
                StdioServerParameters(command="test_stdio_cmd"),
                "stdio",
                "mcp.client.session_group.mcp.stdio_client",
            ),
            (
                SseServerParameters(url="http://test.com/sse", timeout=10),
                "sse",
                "mcp.client.session_group.sse_client",
            ),  # url, headers, timeout, sse_read_timeout
            (
                StreamableHttpParameters(url="http://test.com/stream", terminate_on_close=False),
                "streamablehttp",
                "mcp.client.session_group.streamable_http_client",
            ),  # url, headers, timeout, sse_read_timeout, terminate_on_close
        ],
    )
    async def test_establish_session_parameterized(
        self,
        server_params_instance: StdioServerParameters | SseServerParameters | StreamableHttpParameters,
        client_type_name: str,  # Just for clarity or conditional logic if needed
        patch_target_for_client_func: str,
    ):
        with mock.patch("mcp.client.session_group.mcp.ClientSession") as mock_ClientSession_class:
            with mock.patch(patch_target_for_client_func) as mock_specific_client_func:
                mock_client_cm_instance = mock.AsyncMock(name=f"{client_type_name}ClientCM")
                mock_read_stream = mock.AsyncMock(name=f"{client_type_name}Read")
                mock_write_stream = mock.AsyncMock(name=f"{client_type_name}Write")

                # streamable_http_client's __aenter__ returns three values
                if client_type_name == "streamablehttp":
                    mock_extra_stream_val = mock.AsyncMock(name="StreamableExtra")
                    mock_client_cm_instance.__aenter__.return_value = (
                        mock_read_stream,
                        mock_write_stream,
                        mock_extra_stream_val,
                    )
                else:
                    mock_client_cm_instance.__aenter__.return_value = (
                        mock_read_stream,
                        mock_write_stream,
                    )

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
                mock_initialize_result.serverInfo = types.Implementation(name="foo", version="1")
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
                    ) = await group._establish_session(server_params_instance)

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
                elif client_type_name == "streamablehttp":
                    assert isinstance(server_params_instance, StreamableHttpParameters)
                    mock_specific_client_func.assert_called_once_with(
                        url=server_params_instance.url,
                        headers=server_params_instance.headers,
                        timeout=server_params_instance.timeout,
                        sse_read_timeout=server_params_instance.sse_read_timeout,
                        terminate_on_close=server_params_instance.terminate_on_close,
                    )

                mock_client_cm_instance.__aenter__.assert_awaited_once()

                # 2. Assert ClientSession was called correctly
                mock_ClientSession_class.assert_called_once_with(mock_read_stream, mock_write_stream)
                mock_raw_session_cm.__aenter__.assert_awaited_once()
                mock_entered_session.initialize.assert_awaited_once()

                # 3. Assert returned values
                assert returned_server_info is mock_initialize_result.serverInfo
                assert returned_session is mock_entered_session
