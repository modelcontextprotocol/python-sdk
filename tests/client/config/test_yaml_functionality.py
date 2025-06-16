# stdlib imports
from pathlib import Path

# third party imports
import pytest

# local imports
from mcp.client.config.mcp_servers_config import MCPServersConfig, StdioServerConfig, StreamableHTTPServerConfig


@pytest.fixture
def mcp_yaml_config_file() -> Path:
    """Return path to the mcp.yaml config file."""
    return Path(__file__).parent / "mcp.yaml"


def test_yaml_extension_auto_detection(mcp_yaml_config_file: Path):
    """Test that .yaml files are automatically parsed with PyYAML."""
    config = MCPServersConfig.from_file(mcp_yaml_config_file)

    # Should successfully load the YAML file with all 9 servers
    assert "stdio_server" in config.servers
    assert "streamable_http_server_with_headers" in config.servers
    assert "sse_server_with_explicit_type" in config.servers

    # Verify a specific server
    stdio_server = config.servers["stdio_server"]
    assert isinstance(stdio_server, StdioServerConfig)
    assert stdio_server.command == "python"
    assert stdio_server.args == ["-m", "my_server"]
    assert stdio_server.env == {"DEBUG": "true"}


def test_use_pyyaml_parameter_with_json_file():
    """Test that use_pyyaml=True forces PyYAML parsing even for JSON files."""
    json_file = Path(__file__).parent / "mcp.json"

    # Load with PyYAML explicitly
    config = MCPServersConfig.from_file(json_file, use_pyyaml=True)

    # Should work fine - PyYAML can parse JSON
    assert len(config.servers) == 7
    assert "stdio_server" in config.servers

    # Verify it produces the same result as normal JSON parsing
    config_json = MCPServersConfig.from_file(json_file, use_pyyaml=False)
    assert len(config.servers) == len(config_json.servers)
    assert list(config.servers.keys()) == list(config_json.servers.keys())


def test_uvx_time_server(mcp_yaml_config_file: Path):
    """Test the time server configuration with uvx command."""
    config = MCPServersConfig.from_file(mcp_yaml_config_file)

    # Should have the time server
    assert "time" in config.servers

    # Verify the server configuration
    time_server = config.servers["time"]
    assert isinstance(time_server, StdioServerConfig)
    assert time_server.type == "stdio"  # Should be auto-inferred from command field
    assert time_server.command == "uvx mcp-server-time"
    assert time_server.args is None  # No explicit args
    assert time_server.env is None  # No environment variables

    # Test the effective command parsing
    assert time_server.effective_command == "uvx"
    assert time_server.effective_args == ["mcp-server-time"]


def test_streamable_http_server(mcp_yaml_config_file: Path):
    """Test the new streamable HTTP server configuration without headers."""
    config = MCPServersConfig.from_file(mcp_yaml_config_file)

    # Should have the new streamable_http_server
    assert "streamable_http_server" in config.servers

    # Verify the server configuration
    http_server = config.servers["streamable_http_server"]
    assert isinstance(http_server, StreamableHTTPServerConfig)
    assert http_server.type == "streamable_http"  # Should be auto-inferred
    assert http_server.url == "https://api.example.com/mcp"
    assert http_server.headers is None  # No headers specified


def test_npx_filesystem_server(mcp_yaml_config_file: Path):
    """Test the filesystem server configuration with full command string and multiple arguments."""
    config = MCPServersConfig.from_file(mcp_yaml_config_file)

    # Should have the filesystem server
    assert "filesystem" in config.servers

    # Verify the server configuration
    filesystem_server = config.servers["filesystem"]
    assert isinstance(filesystem_server, StdioServerConfig)
    assert filesystem_server.type == "stdio"  # Should be auto-inferred from command field
    assert (
        filesystem_server.command
        == "npx -y @modelcontextprotocol/server-filesystem /Users/username/Desktop /path/to/other/allowed/dir"
    )
    assert filesystem_server.args is None  # No explicit args
    assert filesystem_server.env is None  # No environment variables

    # Test the effective command and args parsing
    assert filesystem_server.effective_command == "npx"
    assert filesystem_server.effective_args == [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/Users/username/Desktop",
        "/path/to/other/allowed/dir",
    ]
