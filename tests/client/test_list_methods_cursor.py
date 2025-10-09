from collections.abc import Callable

import pytest

import mcp.types as types
from mcp.server import Server
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session as create_session
from mcp.types import ListToolsRequest, ListToolsResult

from .conftest import StreamSpyCollection

pytestmark = pytest.mark.anyio


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
async def test_list_tools_cursor_parameter(stream_spy: Callable[[], StreamSpyCollection]):
    """Test that the cursor parameter is accepted for list_tools
    and that it is correctly passed to the server.

    See: https://modelcontextprotocol.io/specification/2025-03-26/server/utilities/pagination#request-format
    """
    server = FastMCP("test")

    # Create a couple of test tools
    @server.tool(name="test_tool_1")
    async def test_tool_1() -> str:
        """First test tool"""
        return "Result 1"

    @server.tool(name="test_tool_2")
    async def test_tool_2() -> str:
        """Second test tool"""
        return "Result 2"

    async with create_session(server._mcp_server) as client_session:
        spies = stream_spy()

        # Test without cursor parameter (omitted)
        _ = await client_session.list_tools()
        list_tools_requests = spies.get_client_requests(method="tools/list")
        assert len(list_tools_requests) == 1
        assert list_tools_requests[0].params is None

        spies.clear()

        # Test with cursor=None
        _ = await client_session.list_tools(cursor=None)
        list_tools_requests = spies.get_client_requests(method="tools/list")
        assert len(list_tools_requests) == 1
        assert list_tools_requests[0].params is None

        spies.clear()

        # Test with cursor as string
        _ = await client_session.list_tools(cursor="some_cursor_value")
        list_tools_requests = spies.get_client_requests(method="tools/list")
        assert len(list_tools_requests) == 1
        assert list_tools_requests[0].params is not None
        assert list_tools_requests[0].params["cursor"] == "some_cursor_value"

        spies.clear()

        # Test with empty string cursor
        _ = await client_session.list_tools(cursor="")
        list_tools_requests = spies.get_client_requests(method="tools/list")
        assert len(list_tools_requests) == 1
        assert list_tools_requests[0].params is not None
        assert list_tools_requests[0].params["cursor"] == ""


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
async def test_list_resources_cursor_parameter(stream_spy: Callable[[], StreamSpyCollection]):
    """Test that the cursor parameter is accepted for list_resources
    and that it is correctly passed to the server.

    See: https://modelcontextprotocol.io/specification/2025-03-26/server/utilities/pagination#request-format
    """
    server = FastMCP("test")

    # Create a test resource
    @server.resource("resource://test/data")
    async def test_resource() -> str:
        """Test resource"""
        return "Test data"

    async with create_session(server._mcp_server) as client_session:
        spies = stream_spy()

        # Test without cursor parameter (omitted)
        _ = await client_session.list_resources()
        list_resources_requests = spies.get_client_requests(method="resources/list")
        assert len(list_resources_requests) == 1
        assert list_resources_requests[0].params is None

        spies.clear()

        # Test with cursor=None
        _ = await client_session.list_resources(cursor=None)
        list_resources_requests = spies.get_client_requests(method="resources/list")
        assert len(list_resources_requests) == 1
        assert list_resources_requests[0].params is None

        spies.clear()

        # Test with cursor as string
        _ = await client_session.list_resources(cursor="some_cursor")
        list_resources_requests = spies.get_client_requests(method="resources/list")
        assert len(list_resources_requests) == 1
        assert list_resources_requests[0].params is not None
        assert list_resources_requests[0].params["cursor"] == "some_cursor"

        spies.clear()

        # Test with empty string cursor
        _ = await client_session.list_resources(cursor="")
        list_resources_requests = spies.get_client_requests(method="resources/list")
        assert len(list_resources_requests) == 1
        assert list_resources_requests[0].params is not None
        assert list_resources_requests[0].params["cursor"] == ""


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
async def test_list_prompts_cursor_parameter(stream_spy: Callable[[], StreamSpyCollection]):
    """Test that the cursor parameter is accepted for list_prompts
    and that it is correctly passed to the server.
    See: https://modelcontextprotocol.io/specification/2025-03-26/server/utilities/pagination#request-format
    """
    server = FastMCP("test")

    # Create a test prompt
    @server.prompt()
    async def test_prompt(name: str) -> str:
        """Test prompt"""
        return f"Hello, {name}!"

    async with create_session(server._mcp_server) as client_session:
        spies = stream_spy()

        # Test without cursor parameter (omitted)
        _ = await client_session.list_prompts()
        list_prompts_requests = spies.get_client_requests(method="prompts/list")
        assert len(list_prompts_requests) == 1
        assert list_prompts_requests[0].params is None

        spies.clear()

        # Test with cursor=None
        _ = await client_session.list_prompts(cursor=None)
        list_prompts_requests = spies.get_client_requests(method="prompts/list")
        assert len(list_prompts_requests) == 1
        assert list_prompts_requests[0].params is None

        spies.clear()

        # Test with cursor as string
        _ = await client_session.list_prompts(cursor="some_cursor")
        list_prompts_requests = spies.get_client_requests(method="prompts/list")
        assert len(list_prompts_requests) == 1
        assert list_prompts_requests[0].params is not None
        assert list_prompts_requests[0].params["cursor"] == "some_cursor"

        spies.clear()

        # Test with empty string cursor
        _ = await client_session.list_prompts(cursor="")
        list_prompts_requests = spies.get_client_requests(method="prompts/list")
        assert len(list_prompts_requests) == 1
        assert list_prompts_requests[0].params is not None
        assert list_prompts_requests[0].params["cursor"] == ""


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
async def test_list_resource_templates_cursor_parameter(stream_spy: Callable[[], StreamSpyCollection]):
    """Test that the cursor parameter is accepted for list_resource_templates
    and that it is correctly passed to the server.

    See: https://modelcontextprotocol.io/specification/2025-03-26/server/utilities/pagination#request-format
    """
    server = FastMCP("test")

    # Create a test resource template
    @server.resource("resource://test/{name}")
    async def test_template(name: str) -> str:
        """Test resource template"""
        return f"Data for {name}"

    async with create_session(server._mcp_server) as client_session:
        spies = stream_spy()

        # Test without cursor parameter (omitted)
        _ = await client_session.list_resource_templates()
        list_templates_requests = spies.get_client_requests(method="resources/templates/list")
        assert len(list_templates_requests) == 1
        assert list_templates_requests[0].params is None

        spies.clear()

        # Test with cursor=None
        _ = await client_session.list_resource_templates(cursor=None)
        list_templates_requests = spies.get_client_requests(method="resources/templates/list")
        assert len(list_templates_requests) == 1
        assert list_templates_requests[0].params is None

        spies.clear()

        # Test with cursor as string
        _ = await client_session.list_resource_templates(cursor="some_cursor")
        list_templates_requests = spies.get_client_requests(method="resources/templates/list")
        assert len(list_templates_requests) == 1
        assert list_templates_requests[0].params is not None
        assert list_templates_requests[0].params["cursor"] == "some_cursor"

        spies.clear()

        # Test with empty string cursor
        _ = await client_session.list_resource_templates(cursor="")
        list_templates_requests = spies.get_client_requests(method="resources/templates/list")
        assert len(list_templates_requests) == 1
        assert list_templates_requests[0].params is not None
        assert list_templates_requests[0].params["cursor"] == ""


async def test_list_tools_with_strict_server_validation():
    """Test that list_tools works with strict servers require a params field,
    even if it is empty.

    Some MCP servers may implement strict JSON-RPC validation that requires
    the params field to always be present in requests, even if empty {}.

    This test ensures such servers are supported by the client SDK for list_resources
    requests without a cursor.
    """

    server = Server("strict_server")

    @server.list_tools()
    async def handle_list_tools(request: ListToolsRequest) -> ListToolsResult:
        """Strict handler that validates params field exists"""

        # Simulate strict server validation
        if request.params is None:
            raise ValueError(
                "Strict server validation failed: params field must be present. "
                "Expected params: {} for requests without cursor."
            )

        # Return empty tools list
        return ListToolsResult(tools=[])

    async with create_session(server) as client_session:
        # Use params to explicitly send params: {} for strict server compatibility
        result = await client_session.list_tools(params=types.PaginatedRequestParams())
        assert result is not None
