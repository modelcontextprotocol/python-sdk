# stdlib imports
import json
import re
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


def strip_jsonc_comments(jsonc_content: str) -> str:
    """
    Simple function to strip comments from JSONC content.
    This handles basic line comments (//) and block comments (/* */).
    """
    # Remove single-line comments (// comment)
    lines = jsonc_content.split("\n")
    processed_lines = []

    for line in lines:
        # Find the position of // that's not inside a string
        in_string = False
        escaped = False
        comment_pos = -1

        for i, char in enumerate(line):
            if escaped:
                escaped = False
                continue

            if char == "\\":
                escaped = True
                continue

            if char == '"' and not escaped:
                in_string = not in_string
                continue

            if not in_string and char == "/" and i + 1 < len(line) and line[i + 1] == "/":
                comment_pos = i
                break

        if comment_pos >= 0:
            line = line[:comment_pos].rstrip()

        processed_lines.append(line)

    content = "\n".join(processed_lines)

    # Remove block comments (/* comment */)
    # This is a simplified approach - not perfect for all edge cases
    content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)

    return content


@pytest.fixture
def mcp_jsonc_config_file() -> Path:
    """Return path to the mcp.jsonc config file with comments"""
    return Path(__file__).parent / "mcp.jsonc"


def test_jsonc_file_exists(mcp_jsonc_config_file: Path):
    """Test that the JSONC configuration file exists."""
    assert mcp_jsonc_config_file.exists(), f"JSONC config file not found: {mcp_jsonc_config_file}"


def test_jsonc_content_can_be_parsed():
    """Test that JSONC content can be parsed after stripping comments."""
    jsonc_file = Path(__file__).parent / "mcp.jsonc"

    with open(jsonc_file) as f:
        jsonc_content = f.read()

    # Strip comments and parse as JSON
    json_content = strip_jsonc_comments(jsonc_content)
    parsed_data = json.loads(json_content)

    # Validate the structure
    assert "mcpServers" in parsed_data
    assert isinstance(parsed_data["mcpServers"], dict)

    # Check that some expected servers are present
    servers = parsed_data["mcpServers"]
    assert "stdio_server" in servers
    assert "streamable_http_server_with_headers" in servers
    assert "sse_server_with_explicit_type" in servers


def test_jsonc_config_can_be_loaded_as_mcp_config():
    """Test that JSONC content can be loaded into MCPServersConfig after processing."""
    jsonc_file = Path(__file__).parent / "mcp.jsonc"

    with open(jsonc_file) as f:
        jsonc_content = f.read()

    # Strip comments and create config
    json_content = strip_jsonc_comments(jsonc_content)
    parsed_data = json.loads(json_content)
    config = MCPServersConfig.model_validate(parsed_data)

    # Test that all expected servers are loaded correctly
    assert len(config.servers) == 7  # Should have 7 servers total

    # Test stdio server
    stdio_server = config.servers["stdio_server"]
    assert isinstance(stdio_server, StdioServerConfig)
    assert stdio_server.command == "python"
    assert stdio_server.type == "stdio"

    # Test streamable HTTP server
    http_server = config.servers["streamable_http_server_with_headers"]
    assert isinstance(http_server, StreamableHTTPServerConfig)
    assert http_server.url == "https://api.example.com/mcp"
    assert http_server.type == "streamable_http"

    # Test SSE server
    sse_server = config.servers["sse_server_with_explicit_type"]
    assert isinstance(sse_server, SSEServerConfig)
    assert sse_server.url == "https://api.example.com/sse"
    assert sse_server.type == "sse"


def test_jsonc_comments_are_properly_stripped():
    """Test that various comment types are properly stripped from JSONC."""
    test_jsonc = """
    {
      // This is a line comment
      "key1": "value1",
      "key2": "value with // not a comment inside string",
      /* This is a 
         block comment */
      "key3": "value3"  // Another line comment
    }
    """

    result = strip_jsonc_comments(test_jsonc)
    parsed = json.loads(result)

    assert parsed["key1"] == "value1"
    assert parsed["key2"] == "value with // not a comment inside string"
    assert parsed["key3"] == "value3"


def test_jsonc_and_json_configs_are_equivalent():
    """Test that the JSONC and JSON configs contain the same data after comment removal."""
    json_file = Path(__file__).parent / "mcp.json"
    jsonc_file = Path(__file__).parent / "mcp.jsonc"

    # Load JSON config
    with open(json_file) as f:
        json_data = json.load(f)

    # Load JSONC config and strip comments
    with open(jsonc_file) as f:
        jsonc_content = f.read()
    jsonc_data = json.loads(strip_jsonc_comments(jsonc_content))

    # They should be equivalent
    assert json_data == jsonc_data
