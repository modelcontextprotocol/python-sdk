# stdlib imports
from pathlib import Path

# third party imports
import pytest

# local imports
from mcp.client.config.mcp_servers_config import (
    MCPServersConfig,
    SSEServerConfig,
    StdioServerConfig,
    StreamableHTTPServerConfig,
)


@pytest.fixture
def mcp_config_file() -> Path:
    """Return path to the mcp.json config file with mixed server types"""
    return Path(__file__).parent / "mcp.json"


def test_stdio_server(mcp_config_file: Path):
    config = MCPServersConfig.from_file(mcp_config_file)

    stdio_server = config.servers["stdio_server"]
    assert isinstance(stdio_server, StdioServerConfig)

    assert stdio_server.command == "python"
    assert stdio_server.args == ["-m", "my_server"]
    assert stdio_server.env == {"DEBUG": "true"}
    assert stdio_server.type == "stdio"  # Should be automatically inferred

    # In this case, effective_command and effective_args are the same as command
    # and args.
    # But later on, we will see a test where the command is specified as a
    # single string, and we expect the command to be split into command and args
    assert stdio_server.effective_command == "python"
    assert stdio_server.effective_args == ["-m", "my_server"]


def test_stdio_server_with_explicit_type(mcp_config_file: Path):
    """Test that stdio server with explicit 'type' field is respected and works correctly."""
    config = MCPServersConfig.from_file(mcp_config_file)

    stdio_server = config.servers["stdio_server_with_explicit_type"]
    assert isinstance(stdio_server, StdioServerConfig)
    assert stdio_server.type == "stdio"


def test_streamable_http_server_with_explicit_type(mcp_config_file: Path):
    """Test that streamable HTTP server with explicit 'type' field is respected and works correctly."""
    config = MCPServersConfig.from_file(mcp_config_file)

    http_server = config.servers["streamable_http_server_with_explicit_type"]
    assert isinstance(http_server, StreamableHTTPServerConfig)
    assert http_server.type == "streamable_http"


def test_sse_server_with_explicit_type(mcp_config_file: Path):
    """Test that SSE server with explicit 'type' field is respected and works correctly."""
    config = MCPServersConfig.from_file(mcp_config_file)

    sse_server = config.servers["sse_server_with_explicit_type"]
    assert isinstance(sse_server, SSEServerConfig)
    assert sse_server.type == "sse"


def test_stdio_server_with_full_command_should_be_split(mcp_config_file: Path):
    """This test should fail - it expects the command to be split into command and args."""
    config = MCPServersConfig.from_file(mcp_config_file)

    stdio_server = config.servers["stdio_server_with_full_command"]
    assert isinstance(stdio_server, StdioServerConfig)

    # This is how the command was specified
    assert stdio_server.command == "python -m my_server"

    # This is how the command is split into command and args
    assert stdio_server.effective_command == "python"
    assert stdio_server.effective_args == ["-m", "my_server"]


def test_stdio_server_with_full_command_and_explicit_args(mcp_config_file: Path):
    """Test that effective_args combines parsed command args with explicit args."""
    config = MCPServersConfig.from_file(mcp_config_file)

    stdio_server = config.servers["stdio_server_with_full_command_and_explicit_args"]
    assert isinstance(stdio_server, StdioServerConfig)

    # Test original values
    assert stdio_server.command == "python -m my_server"
    assert stdio_server.args == ["--debug"]

    # Test effective values - should combine parsed command args with explicit args
    assert stdio_server.effective_command == "python"
    assert stdio_server.effective_args == ["-m", "my_server", "--debug"]


def test_streamable_http_server_with_headers(mcp_config_file: Path):
    config = MCPServersConfig.from_file(mcp_config_file)

    http_server = config.servers["streamable_http_server_with_headers"]
    assert isinstance(http_server, StreamableHTTPServerConfig)

    assert http_server.url == "https://api.example.com/mcp"
    assert http_server.headers == {"Authorization": "Bearer token123"}
    assert http_server.type == "streamable_http"  # Should be automatically inferred


def test_stdio_server_with_quoted_arguments():
    """Test that stdio servers handle quoted arguments with spaces correctly."""
    # Test with double quotes
    config_data = {
        "mcpServers": {
            "server_with_double_quotes": {"command": 'python -m my_server --config "path with spaces/config.json"'},
            "server_with_single_quotes": {
                "command": "python -m my_server --config 'another path with spaces/config.json'"
            },
            "server_with_mixed_quotes": {
                "command": "python -m my_server --name \"My Server\" --path '/home/user/my path'"
            },
        }
    }

    config = MCPServersConfig.model_validate(config_data)

    # Test double quotes
    double_quote_server = config.servers["server_with_double_quotes"]
    assert isinstance(double_quote_server, StdioServerConfig)
    assert double_quote_server.effective_command == "python"
    expected_args_double = ["-m", "my_server", "--config", "path with spaces/config.json"]
    assert double_quote_server.effective_args == expected_args_double

    # Test single quotes
    single_quote_server = config.servers["server_with_single_quotes"]
    assert isinstance(single_quote_server, StdioServerConfig)
    assert single_quote_server.effective_command == "python"
    expected_args_single = ["-m", "my_server", "--config", "another path with spaces/config.json"]
    assert single_quote_server.effective_args == expected_args_single

    # Test mixed quotes
    mixed_quote_server = config.servers["server_with_mixed_quotes"]
    assert isinstance(mixed_quote_server, StdioServerConfig)
    assert mixed_quote_server.effective_command == "python"
    expected_args_mixed = ["-m", "my_server", "--name", "My Server", "--path", "/home/user/my path"]
    assert mixed_quote_server.effective_args == expected_args_mixed


def test_both_field_names_supported():
    """Test that both 'servers' and 'mcpServers' field names are supported."""
    # Test with 'mcpServers' field name (traditional format)
    config_with_mcp_servers = MCPServersConfig.model_validate(
        {"mcpServers": {"test_server": {"command": "python -m test_server", "type": "stdio"}}}
    )

    # Test with 'servers' field name (new format)
    config_with_servers = MCPServersConfig.model_validate(
        {"servers": {"test_server": {"command": "python -m test_server", "type": "stdio"}}}
    )

    # Both should produce identical results
    assert config_with_mcp_servers.servers == config_with_servers.servers
    assert "test_server" in config_with_mcp_servers.servers
    assert "test_server" in config_with_servers.servers

    # Verify the server configurations are correct
    server1 = config_with_mcp_servers.servers["test_server"]
    server2 = config_with_servers.servers["test_server"]

    assert isinstance(server1, StdioServerConfig)
    assert isinstance(server2, StdioServerConfig)
    assert server1.command == server2.command == "python -m test_server"


def test_servers_field_takes_precedence():
    """Test that 'servers' field takes precedence when both are present."""
    config_data = {
        "mcpServers": {"old_server": {"command": "python -m old_server", "type": "stdio"}},
        "servers": {"new_server": {"command": "python -m new_server", "type": "stdio"}},
    }

    config = MCPServersConfig.model_validate(config_data)

    # Should only have the 'servers' content, not 'mcpServers'
    assert "new_server" in config.servers
    assert "old_server" not in config.servers
    assert len(config.servers) == 1
