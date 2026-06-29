from collections.abc import Callable

import mcp_types as types
import pytest
from mcp_types import ListToolsResult

from mcp import Client
from mcp.server import Server, ServerRequestContext
from mcp.server.mcpserver import MCPServer

from .conftest import StreamSpyCollection

pytestmark = pytest.mark.anyio


@pytest.fixture
async def full_featured_server():
    server = MCPServer("test")

    # The no-cover handlers exist only so list_* methods return results; these tests never invoke them.
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
    full_featured_server: MCPServer,
    method_name: str,
    request_method: str,
):
    """See https://modelcontextprotocol.io/specification/2025-03-26/server/utilities/pagination#request-format"""
    async with Client(full_featured_server, mode="legacy") as client:
        spies = stream_spy()

        method = getattr(client, method_name)
        _ = await method()
        requests = spies.get_client_requests(method=request_method)
        assert len(requests) == 1
        assert requests[0].params is None or "cursor" not in requests[0].params

        spies.clear()

        _ = await method(cursor="from_params")
        requests = spies.get_client_requests(method=request_method)
        assert len(requests) == 1
        assert requests[0].params is not None
        assert requests[0].params["cursor"] == "from_params"

        spies.clear()

        # A plain call after a cursor call must again omit the cursor
        _ = await method()
        requests = spies.get_client_requests(method=request_method)
        assert len(requests) == 1
        assert requests[0].params is None or "cursor" not in requests[0].params


async def test_list_tools_with_strict_server_validation(
    full_featured_server: MCPServer,
):
    async with Client(full_featured_server) as client:
        result = await client.list_tools()
        assert isinstance(result, ListToolsResult)
        assert len(result.tools) > 0


async def test_list_tools_with_lowlevel_server():
    async def handle_list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> ListToolsResult:
        # Echo the received cursor through the tool description so the client side can assert on it
        cursor = params.cursor if params else None
        return ListToolsResult(
            tools=[types.Tool(name="test_tool", description=f"cursor={cursor}", input_schema={"type": "object"})]
        )

    server = Server("test-lowlevel", on_list_tools=handle_list_tools)

    async with Client(server) as client:
        result = await client.list_tools()
        assert result.tools[0].description == "cursor=None"

        result = await client.list_tools(cursor="page2")
        assert result.tools[0].description == "cursor=page2"
