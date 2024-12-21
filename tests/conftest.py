import pytest
from pydantic import AnyUrl

from mcp.server.lowlevel import Server
from mcp.server.models import InitializationOptions
from mcp.types import Resource, ServerCapabilities

TEST_INITIALIZATION_OPTIONS = InitializationOptions(
    server_name="my_mcp_server",
    server_version="0.1.0",
    capabilities=ServerCapabilities(),
)


@pytest.fixture
def mcp_server() -> Server:
    server = Server(name="test_server")

    @server.list_resources()
    async def handle_list_resources():
        return [
            Resource(
                uri=AnyUrl("memory://test"),
                name="Test Resource",
                description="A test resource",
            )
        ]

    return server


@pytest.fixture
def anyio_backend():
    return "asyncio"
