from collections.abc import Callable

import pytest

import mcp.types as types
from mcp import Client
from mcp.server import Server
from mcp.server.fastmcp import FastMCP
from mcp.types import ListToolsRequest, ListToolsResult

from .conftest import StreamSpyCollection

pytestmark = pytest.mark.anyio


@pytest.fixture
async def full_featured_server():
    """Create a server with tools, resources, prompts, and templates."""
    server = FastMCP("test")

    # pragma: no cover on handlers below - these exist only to register items with the
    # server so list_* methods return results. The handlers themselves are never called
    # because these tests only verify pagination/cursor behavior, not tool/resource invocation.
    @server.tool()
    def greet(name: str) -> str:  # pragma: no cover
        """Greet someone by name."""
        return f"Hello, {name}!"

    @server.resource("test://resource")
    def test_resource() -> str:  # pragma: no cover
        """A test resource."""
        return "Test content"

    @server.resource("test://template/{id}")
    def test_template(id: str) -> str:  # pragma: no cover
        """A test resource template."""
        return f"Template content for {id}"

    @server.prompt()
    def greeting_prompt(name: str) -> str:  # pragma: no cover
        """A greeting prompt."""
        return f"Please greet {name}."

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
async def test_list_methods_params_parameter(
    stream_spy: Callable[[], StreamSpyCollection],
    full_featured_server: FastMCP,
    method_name: str,
    request_method: str,
):
    """Test that the params parameter is accepted and correctly passed to the server.

    Covers: list_tools, list_resources, list_prompts, list_resource_templates

    See: https://modelcontextprotocol.io/specification/2025-03-26/server/utilities/pagination#request-format
    """
    async with Client(full_featured_server) as client:
        spies = stream_spy()

        # Test without params (omitted)
        method = getattr(client, method_name)
        _ = await method()
        requests = spies.get_client_requests(method=request_method)
        assert len(requests) == 1
        assert requests[0].params is None or "cursor" not in requests[0].params

        spies.clear()

        # Test with params containing cursor
        _ = await method(cursor="from_params")
        requests = spies.get_client_requests(method=request_method)
        assert len(requests) == 1
        assert requests[0].params is not None
        assert requests[0].params["cursor"] == "from_params"

        spies.clear()

        # Test with empty params
        _ = await method()
        requests = spies.get_client_requests(method=request_method)
        assert len(requests) == 1
        # Empty params means no cursor
        assert requests[0].params is None or "cursor" not in requests[0].params


async def test_list_tools_with_strict_server_validation(
    full_featured_server: FastMCP,
):
    """Test pagination with a server that validates request format strictly."""
    async with Client(full_featured_server) as client:
        result = await client.list_tools()
        assert isinstance(result, ListToolsResult)
        assert len(result.tools) > 0


async def test_list_tools_with_lowlevel_server():
    """Test that list_tools works with a lowlevel Server using params."""
    server = Server("test-lowlevel")

    @server.list_tools()
    async def handle_list_tools(request: ListToolsRequest) -> ListToolsResult:
        # Echo back what cursor we received in the tool description
        cursor = request.params.cursor if request.params else None
        return ListToolsResult(tools=[types.Tool(name="test_tool", description=f"cursor={cursor}", input_schema={})])

    async with Client(server) as client:
        result = await client.list_tools()
        assert result.tools[0].description == "cursor=None"

        result = await client.list_tools(cursor="page2")
        assert result.tools[0].description == "cursor=page2"
