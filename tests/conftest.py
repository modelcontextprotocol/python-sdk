from pydantic import AnyUrl
import pytest

from mcp_python.server import Server
from mcp_python.server.types import InitializationOptions
from mcp_python.types import Resource, ServerCapabilities

TEST_INITIALIZATION_OPTIONS = InitializationOptions(
    server_name="my_mcp_server",
    server_version="0.1.0",
    capabilities=ServerCapabilities(),
)

@pytest.fixture
def mcp_server() -> Server:
    server = Server(name="test_server")

    # Add a simple resource for testing
    @server.list_resources()
    async def handle_list_resources():
        return [
            Resource(
                uri=AnyUrl("memory://test"),
                name="Test Resource",
                description="A test resource"
            )
        ]

    return server
