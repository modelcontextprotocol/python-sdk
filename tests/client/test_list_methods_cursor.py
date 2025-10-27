from collections.abc import Callable

import pytest

import mcp.types as types
from mcp.server import Server
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session as create_session
from mcp.types import ListToolsRequest, ListToolsResult

from .conftest import StreamSpyCollection

pytestmark = pytest.mark.anyio


@pytest.fixture
async def full_featured_server():
    """Create a server with tools, resources, prompts, and templates."""
    server = FastMCP("test")

    @server.tool(name="test_tool_1")
    async def test_tool_1() -> str:
        """First test tool"""
        return "Result 1"

    @server.tool(name="test_tool_2")
    async def test_tool_2() -> str:
        """Second test tool"""
        return "Result 2"

    @server.resource("resource://test/data")
    async def test_resource() -> str:
        """Test resource"""
        return "Test data"

    @server.prompt()
    async def test_prompt(name: str) -> str:
        """Test prompt"""
        return f"Hello, {name}!"

    @server.resource("resource://test/{name}")
    async def test_template(name: str) -> str:
        """Test resource template"""
        return f"Data for {name}"

    return server


@pytest.mark.parametrize(
    "method_name,request_method",
    [
        ("list_tools", "tools/list"),
        ("list_resources", "resources/list"),
        ("list_prompts", "prompts/list"),
        ("list_resource_templates", "resources/templates/list"),
    ],
)
@pytest.mark.filterwarnings("ignore::DeprecationWarning")
async def test_list_methods_cursor_parameter(
    stream_spy: Callable[[], StreamSpyCollection],
    full_featured_server: FastMCP,
    method_name: str,
    request_method: str,
):
    """Test that the cursor parameter is accepted and correctly passed to the server.

    Covers: list_tools, list_resources, list_prompts, list_resource_templates

    See: https://modelcontextprotocol.io/specification/2025-03-26/server/utilities/pagination#request-format
    """
    async with create_session(full_featured_server._mcp_server) as client_session:
        spies = stream_spy()

        # Test without cursor parameter (omitted)
        method = getattr(client_session, method_name)
        _ = await method()
        requests = spies.get_client_requests(method=request_method)
        assert len(requests) == 1
        assert requests[0].params is None

        spies.clear()

        # Test with cursor=None
        _ = await method(cursor=None)
        requests = spies.get_client_requests(method=request_method)
        assert len(requests) == 1
        assert requests[0].params is None

        spies.clear()

        # Test with cursor as string
        _ = await method(cursor="some_cursor_value")
        requests = spies.get_client_requests(method=request_method)
        assert len(requests) == 1
        assert requests[0].params is not None
        assert requests[0].params["cursor"] == "some_cursor_value"

        spies.clear()

        # Test with empty string cursor
        _ = await method(cursor="")
        requests = spies.get_client_requests(method=request_method)
        assert len(requests) == 1
        assert requests[0].params is not None
        assert requests[0].params["cursor"] == ""


@pytest.mark.parametrize(
    "method_name,request_method",
    [
        ("list_tools", "tools/list"),
        ("list_resources", "resources/list"),
        ("list_prompts", "prompts/list"),
        ("list_resource_templates", "resources/templates/list"),
    ],
)
async def test_list_methods_params_parameter(
    stream_spy: Callable[[], StreamSpyCollection],
    full_featured_server: FastMCP,
    method_name: str,
    request_method: str,
):
    """Test that the params parameter works correctly for list methods.

    Covers: list_tools, list_resources, list_prompts, list_resource_templates

    This tests the new params parameter API (non-deprecated) to ensure
    it correctly handles all parameter combinations.
    """
    async with create_session(full_featured_server._mcp_server) as client_session:
        spies = stream_spy()
        method = getattr(client_session, method_name)

        # Test without params parameter (omitted)
        _ = await method()
        requests = spies.get_client_requests(method=request_method)
        assert len(requests) == 1
        assert requests[0].params is None

        spies.clear()

        # Test with params=None
        _ = await method(params=None)
        requests = spies.get_client_requests(method=request_method)
        assert len(requests) == 1
        assert requests[0].params is None

        spies.clear()

        # Test with empty params (for strict servers)
        _ = await method(params=types.PaginatedRequestParams())
        requests = spies.get_client_requests(method=request_method)
        assert len(requests) == 1
        assert requests[0].params is not None
        assert requests[0].params.get("cursor") is None

        spies.clear()

        # Test with params containing cursor
        _ = await method(params=types.PaginatedRequestParams(cursor="some_cursor_value"))
        requests = spies.get_client_requests(method=request_method)
        assert len(requests) == 1
        assert requests[0].params is not None
        assert requests[0].params["cursor"] == "some_cursor_value"


@pytest.mark.parametrize(
    "method_name",
    [
        "list_tools",
        "list_resources",
        "list_prompts",
        "list_resource_templates",
    ],
)
async def test_list_methods_raises_error_when_both_cursor_and_params_provided(
    full_featured_server: FastMCP,
    method_name: str,
):
    """Test that providing both cursor and params raises ValueError.

    Covers: list_tools, list_resources, list_prompts, list_resource_templates

    When both cursor and params are provided, a ValueError should be raised
    to prevent ambiguity.
    """
    async with create_session(full_featured_server._mcp_server) as client_session:
        method = getattr(client_session, method_name)

        # Call with both cursor and params - should raise ValueError
        with pytest.raises(ValueError, match="Cannot specify both cursor and params"):
            await method(
                cursor="old_cursor",
                params=types.PaginatedRequestParams(cursor="new_cursor"),
            )


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
