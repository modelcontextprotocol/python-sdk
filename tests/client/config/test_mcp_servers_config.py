# stdlib imports
import json
from pathlib import Path

# third party imports
import pytest

# local imports
from mcp.client.config.mcp_servers_config import (
    MCPServersConfig,
    StdioServerConfig,
    StreamableHttpConfig,
)


@pytest.fixture
def mcp_config_file(tmp_path: Path) -> Path:
    """Create temporary JSON config file with mixed server types"""

    config_data = {
        "mcpServers": {
            "stdio_server": {
                "command": "python",
                "args": ["-m", "my_server"],
                "env": {"DEBUG": "true"},
            },
            "http_streamable": {
                "url": "https://api.example.com/mcp",
                "headers": {"Authorization": "Bearer token123"},
            },
        }
    }

    # Write to temporary file
    config_file_path = tmp_path / "mcp.json"
    with open(config_file_path, "w") as config_file:
        json.dump(config_data, config_file)

    return config_file_path


def test_stdio_server(mcp_config_file: Path):
    config = MCPServersConfig.from_file(mcp_config_file)

    stdio_server = config.servers["stdio_server"]
    assert isinstance(stdio_server, StdioServerConfig)

    assert stdio_server.command == "python"
    assert stdio_server.args == ["-m", "my_server"]
    assert stdio_server.env == {"DEBUG": "true"}
    assert stdio_server.type == "stdio"  # Should be automatically inferred
    

def test_streamable_http_server(mcp_config_file: Path):
    config = MCPServersConfig.from_file(mcp_config_file)

    http_server = config.servers["http_streamable"]
    assert isinstance(http_server, StreamableHttpConfig)

    assert http_server.url == "https://api.example.com/mcp"
    assert http_server.headers == {"Authorization": "Bearer token123"}
    assert http_server.type == "streamable_http"  # Should be automatically inferred
