# stdlib imports
import json
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


def test_from_file_with_inputs(tmp_path: Path):
    """Test loading config from file with input substitution."""
    # Create test config file
    config_content = {
        "inputs": [
            {"id": "host", "description": "Server hostname"},
            {"id": "token", "description": "API token"},
        ],
        "servers": {
            "dynamic_server": {
                "type": "streamable_http",
                "url": "https://${input:host}/mcp/api",
                "headers": {"Authorization": "Bearer ${input:token}"},
            }
        },
    }

    config_file = tmp_path / "test_config.json"
    with open(config_file, "w") as f:
        json.dump(config_content, f)

    config = MCPServersConfig.from_file(config_file)

    assert config.get_required_inputs() == ["host", "token"]
    assert config.inputs is not None
    assert config.inputs[0].id == "host"
    assert config.inputs[1].id == "token"
    assert config.inputs[0].description == "Server hostname"
    assert config.inputs[1].description == "API token"

    input_values = {"host": "api.example.com", "token": "test-token-123"}
    server = config.server("dynamic_server", input_values=input_values)

    assert isinstance(server, StreamableHTTPServerConfig)
    assert server.url == "https://api.example.com/mcp/api"
    assert server.headers == {"Authorization": "Bearer test-token-123"}


def test_from_file_without_inputs(tmp_path: Path):
    """Test loading config from file without input substitution."""
    # Create test config file with placeholders
    config_content = {
        "servers": {
            "static_server": {"type": "sse", "url": "https://static.example.com/mcp/sse"},
            "placeholder_server": {"type": "sse", "url": "https://${input:host}/mcp/sse"},
        }
    }

    config_file = tmp_path / "test_config.json"
    with open(config_file, "w") as f:
        json.dump(config_content, f)

    # Load without input substitution - placeholders should remain
    config = MCPServersConfig.from_file(config_file)

    static_server = config.servers["static_server"]
    assert isinstance(static_server, SSEServerConfig)
    assert static_server.url == "https://static.example.com/mcp/sse"

    placeholder_server = config.servers["placeholder_server"]
    assert isinstance(placeholder_server, SSEServerConfig)
    assert placeholder_server.url == "https://${input:host}/mcp/sse"  # Unchanged


def test_input_substitution_yaml_file(tmp_path: Path):
    """Test input substitution with YAML files."""
    yaml_content = """
inputs:
  - type: promptString
    id: module
    description: Python module to run
  - type: promptString
    id: port
    description: Port to run the server on
  - type: promptString
    id: debug
    description: Debug mode
servers:
  yaml_server:
    type: stdio
    command: python -m ${input:module}
    args:
      - --port
      - "${input:port}"
    env:
      DEBUG: "${input:debug}"
"""

    config_file = tmp_path / "test_config.yaml"
    assert config_file.write_text(yaml_content)

    config = MCPServersConfig.from_file(config_file)

    assert config.get_required_inputs() == ["module", "port", "debug"]
    assert config.inputs is not None
    assert len(config.inputs) == 3
    assert config.inputs[0].id == "module"
    assert config.inputs[0].description == "Python module to run"
    assert config.inputs[1].id == "port"
    assert config.inputs[1].description == "Port to run the server on"
    assert config.inputs[2].id == "debug"
    assert config.inputs[2].description == "Debug mode"

    input_values = {"module": "test_server", "port": "8080", "debug": "true"}
    server = config.server("yaml_server", input_values=input_values)

    assert isinstance(server, StdioServerConfig)
    assert server.command == "python -m test_server"
    assert server.args == ["--port", "8080"]
    assert server.env == {"DEBUG": "true"}


def test_input_definitions_parsing():
    """Test parsing of input definitions from config."""
    config_data = {
        "inputs": [
            {"type": "promptString", "id": "functionapp-name", "description": "Azure Functions App Name"},
            {
                "type": "promptString",
                "id": "api-token",
                "description": "API Token for authentication",
                "password": True,
            },
        ],
        "servers": {
            "azure_server": {
                "type": "sse",
                "url": "https://${input:functionapp-name}.azurewebsites.net/mcp/sse",
                "headers": {"Authorization": "Bearer ${input:api-token}"},
            }
        },
    }

    config = MCPServersConfig.model_validate(config_data)

    # Test input definitions are parsed correctly
    assert config.get_required_inputs() == ["functionapp-name", "api-token"]
    assert config.inputs is not None
    assert len(config.inputs) == 2
    app_name_input = config.inputs[0]
    assert app_name_input.id == "functionapp-name"
    assert app_name_input.description == "Azure Functions App Name"
    assert app_name_input.password is False
    assert app_name_input.type == "promptString"
    api_token_input = config.inputs[1]
    assert api_token_input.id == "api-token"
    assert api_token_input.description == "API Token for authentication"
    assert api_token_input.password is True
    assert api_token_input.type == "promptString"


def test_get_required_inputs():
    """Test getting list of required input IDs."""
    config_data = {
        "inputs": [
            {"id": "input1", "description": "First input"},
            {"id": "input2", "description": "Second input"},
            {"id": "input3", "description": "Third input"},
        ],
        "servers": {"test_server": {"type": "stdio", "command": "python test.py"}},
    }

    config = MCPServersConfig.model_validate(config_data)

    assert config.get_required_inputs() == ["input1", "input2", "input3"]


def test_get_required_inputs_no_inputs_defined():
    """Test getting required inputs when no inputs are defined."""
    config_data = {"servers": {"test_server": {"type": "stdio", "command": "python test.py"}}}

    config = MCPServersConfig.model_validate(config_data)

    assert config.get_required_inputs() == []


def test_get_required_inputs_empty_inputs_list():
    """Test getting required inputs when inputs is explicitly set to an empty list."""
    config_data = {
        "inputs": [],  # Explicitly empty list
        "servers": {"test_server": {"type": "stdio", "command": "python test.py"}},
    }

    config = MCPServersConfig.model_validate(config_data)

    assert config.validate_inputs({}) == []
    assert config.get_required_inputs() == []
    assert config.inputs == []  # Verify inputs is actually an empty list, not None


def test_validate_inputs_all_provided():
    """Test input validation when all required inputs are provided."""
    config_data = {
        "inputs": [
            {"id": "username", "description": "Username"},
            {"id": "password", "description": "Password", "password": True},
        ],
        "servers": {"test_server": {"type": "stdio", "command": "python test.py"}},
    }

    config = MCPServersConfig.model_validate(config_data)
    provided_inputs = {"username": "testuser", "password": "secret123"}

    missing_inputs = config.validate_inputs(provided_inputs)
    assert missing_inputs == []


def test_validate_inputs_some_missing():
    """Test input validation when some required inputs are missing."""
    config_data = {
        "inputs": [
            {"id": "required1", "description": "First required input"},
            {"id": "required2", "description": "Second required input"},
            {"id": "required3", "description": "Third required input"},
        ],
        "servers": {"test_server": {"type": "stdio", "command": "python test.py"}},
    }

    config = MCPServersConfig.model_validate(config_data)
    provided_inputs = {
        "required1": "value1",
        # required2 and required3 are missing
    }

    missing_inputs = config.validate_inputs(provided_inputs)
    assert set(missing_inputs) == {"required2", "required3"}


def test_get_input_description():
    """Test getting input descriptions."""
    config_data = {
        "inputs": [
            {"id": "api-key", "description": "API Key for authentication"},
            {"id": "host", "description": "Server hostname"},
        ],
        "servers": {"test_server": {"type": "stdio", "command": "python test.py"}},
    }

    config = MCPServersConfig.model_validate(config_data)

    assert config.get_input_description("api-key") == "API Key for authentication"
    assert config.get_input_description("host") == "Server hostname"
    assert config.get_input_description("nonexistent") is None


def test_get_input_description_no_inputs():
    """Test getting input description when no inputs are defined."""
    config_data = {"servers": {"test_server": {"type": "stdio", "command": "python test.py"}}}

    config = MCPServersConfig.model_validate(config_data)
    assert config.get_input_description("any-key") is None


def test_from_file_with_input_validation_success(tmp_path: Path):
    """Test loading file with input definitions and successful validation."""
    config_content = {
        "inputs": [
            {"id": "app-name", "description": "Application name"},
            {"id": "env", "description": "Environment (dev/prod)"},
        ],
        "servers": {
            "app_server": {
                "type": "streamable_http",
                "url": "https://${input:app-name}-${input:env}.example.com/mcp/api",
            }
        },
    }

    config_file = tmp_path / "test_config.json"
    with open(config_file, "w") as f:
        json.dump(config_content, f)

    config = MCPServersConfig.from_file(config_file)

    assert config.get_required_inputs() == ["app-name", "env"]
    assert config.inputs is not None
    assert len(config.inputs) == 2
    assert config.inputs[0].id == "app-name"
    assert config.inputs[0].description == "Application name"
    assert config.inputs[1].id == "env"
    assert config.inputs[1].description == "Environment (dev/prod)"

    input_values = {"app-name": "myapp", "env": "prod"}
    server = config.server("app_server", input_values=input_values)

    assert isinstance(server, StreamableHTTPServerConfig)
    assert server.url == "https://myapp-prod.example.com/mcp/api"


def test_from_file_with_input_validation_failure(tmp_path: Path):
    """Test loading file with input definitions and validation failure."""
    config_content = {
        "inputs": [
            {"id": "required-key", "description": "A required API key"},
            {"id": "optional-host", "description": "Optional hostname"},
        ],
        "servers": {"test_server": {"type": "sse", "url": "https://${input:optional-host}/api"}},
    }

    config_file = tmp_path / "test_config.json"
    with open(config_file, "w") as f:
        json.dump(config_content, f)

    inputs: dict[str, str] = {
        # Missing 'required-key' and 'optional-host'
    }

    # Should raise ValueError with helpful error message
    with pytest.raises(ValueError, match="Missing required input values"):
        config = MCPServersConfig.from_file(config_file)
        server = config.server("test_server", input_values=inputs)
        assert server


def test_from_file_without_input_definitions_no_validation(tmp_path: Path):
    """Test that configs without input definitions don't perform validation."""
    config_content = {
        "servers": {"test_server": {"type": "stdio", "command": "python -m server --token ${input:token}"}}
    }

    config_file = tmp_path / "test_config.json"
    with open(config_file, "w") as f:
        json.dump(config_content, f)

    config = MCPServersConfig.from_file(config_file)

    # Even with empty inputs, should load fine since no input definitions exist
    server = config.server("test_server", input_values={})

    assert isinstance(server, StdioServerConfig)
    # Placeholder should remain unchanged
    assert server.command == "python -m server --token ${input:token}"


def test_input_definition_with_yaml_file(tmp_path: Path):
    """Test input definitions work with YAML files."""
    yaml_content = """
inputs:
  - type: promptString
    id: module-name
    description: Python module to run
  - type: promptString
    id: config-path
    description: Path to configuration file
    
servers:
  yaml_server:
    type: stdio
    command: python -m ${input:module-name}
    args:
      - --config
      - ${input:config-path}
"""

    config_file = tmp_path / "test_config.yaml"
    assert config_file.write_text(yaml_content)

    config = MCPServersConfig.from_file(config_file)

    # Verify input definitions were parsed
    assert config.get_required_inputs() == ["module-name", "config-path"]
    assert config.inputs is not None
    assert len(config.inputs) == 2
    assert config.inputs[0].id == "module-name"
    assert config.inputs[1].id == "config-path"

    input_values = {"module-name": "test_module", "config-path": "/etc/config.json"}
    server = config.server("yaml_server", input_values=input_values)

    assert isinstance(server, StdioServerConfig)
    assert server.command == "python -m test_module"
    assert server.args == ["--config", "/etc/config.json"]


def test_jsonc_comment_stripping():
    """Test stripping of // comments from JSONC content."""
    # Test basic comment stripping
    content_with_comments = """
{
    // This is a comment
    "servers": {
        "test_server": {
            "type": "stdio",
            "command": "python test.py" // End of line comment
        }
    },
    // Another comment
    "inputs": [] // Final comment
}
"""

    stripped = MCPServersConfig._strip_json_comments(content_with_comments)
    config = MCPServersConfig.model_validate(json.loads(stripped))

    assert "test_server" in config.servers
    server = config.servers["test_server"]
    assert isinstance(server, StdioServerConfig)
    assert server.command == "python test.py"


def test_jsonc_comments_inside_strings_preserved():
    """Test that // inside strings are not treated as comments."""
    content_with_urls = """
{
    "servers": {
        "web_server": {
            "type": "sse",
            "url": "https://example.com/api/endpoint" // This is a comment
        },
        "protocol_server": {
            "type": "stdio",
            "command": "node server.js --url=http://localhost:3000"
        }
    }
}
"""

    stripped = MCPServersConfig._strip_json_comments(content_with_urls)
    config = MCPServersConfig.model_validate(json.loads(stripped))

    web_server = config.servers["web_server"]
    assert isinstance(web_server, SSEServerConfig)
    assert web_server.url == "https://example.com/api/endpoint"

    protocol_server = config.servers["protocol_server"]
    assert isinstance(protocol_server, StdioServerConfig)
    # The // in the URL should be preserved
    assert "http://localhost:3000" in protocol_server.command


def test_jsonc_escaped_quotes_handling():
    """Test that escaped quotes in strings are handled correctly."""
    content_with_escaped = """
{
    "servers": {
        "test_server": {
            "type": "stdio",
            "command": "python -c \\"print('Hello // World')\\"", // Comment after escaped quotes
            "description": "Server with \\"escaped quotes\\" and // in string"
        }
    }
}
"""

    stripped = MCPServersConfig._strip_json_comments(content_with_escaped)
    config = MCPServersConfig.model_validate(json.loads(stripped))

    server = config.servers["test_server"]
    assert isinstance(server, StdioServerConfig)
    # The command should preserve the escaped quotes and // inside the string
    assert server.command == "python -c \"print('Hello // World')\""


def test_from_file_with_jsonc_comments(tmp_path: Path):
    """Test loading JSONC file with comments via from_file method."""
    jsonc_content = """
{
    // Configuration for MCP servers
    "inputs": [
        {
            "type": "promptString",
            "id": "api-key", // Secret API key
            "description": "API Key for authentication"
        }
    ],
    "servers": {
        // Main server configuration
        "main_server": {
            "type": "sse",
            "url": "https://api.example.com/mcp/sse", // Production URL
            "headers": {
                "Authorization": "Bearer ${input:api-key}" // Dynamic token
            }
        }
    }
    // End of configuration
}
"""

    config_file = tmp_path / "test_config.json"
    assert config_file.write_text(jsonc_content)

    # Should load successfully despite comments
    config = MCPServersConfig.from_file(config_file)

    # Verify input definitions were parsed
    assert config.inputs is not None
    assert len(config.inputs) == 1
    assert config.inputs[0].id == "api-key"

    # Verify server configuration and input substitution
    server = config.server("main_server", input_values={"api-key": "secret123"})
    assert isinstance(server, SSEServerConfig)
    assert server.url == "https://api.example.com/mcp/sse"
    assert server.headers == {"Authorization": "Bearer secret123"}


def test_jsonc_multiline_strings_with_comments():
    """Test that comments in multiline scenarios are handled correctly."""
    content = """
{
    "servers": {
        "test1": {
            // Comment before
            "type": "stdio", // Comment after
            "command": "python server.py"
        }, // Comment after object
        "test2": { "type": "sse", "url": "https://example.com" } // Inline comment
    }
}
"""

    stripped = MCPServersConfig._strip_json_comments(content)
    config = MCPServersConfig.model_validate(json.loads(stripped))

    assert len(config.servers) == 2
    assert "test1" in config.servers
    assert "test2" in config.servers

    test1 = config.servers["test1"]
    assert isinstance(test1, StdioServerConfig)
    assert test1.command == "python server.py"

    test2 = config.servers["test2"]
    assert isinstance(test2, SSEServerConfig)
    assert test2.url == "https://example.com"


def test_sse_type_inference():
    """Test that servers with 'url' field (and SSE mention) are inferred as sse type."""
    config_data = {
        "servers": {
            "api_server": {
                "url": "https://api.example.com/sse"
                # No explicit type - should be inferred as sse
                # because "sse" is in the url
            },
            "webhook_server": {
                "url": "https://webhook.example.com/mcp/api",
                "description": "A simple SSE server",
                "headers": {"X-API-Key": "secret123"},
                # No explicit type - should be inferred as sse
                # because "SSE" is in the description
            },
        }
    }

    config = MCPServersConfig.model_validate(config_data)

    # Verify first server
    api_server = config.servers["api_server"]
    assert isinstance(api_server, SSEServerConfig)
    assert api_server.type == "sse"  # Should be auto-inferred
    assert api_server.url == "https://api.example.com/sse"
    assert api_server.headers is None

    # Verify second server
    webhook_server = config.servers["webhook_server"]
    assert isinstance(webhook_server, SSEServerConfig)
    assert webhook_server.type == "sse"  # Should be auto-inferred
    assert webhook_server.url == "https://webhook.example.com/mcp/api"
    assert webhook_server.headers == {"X-API-Key": "secret123"}


def test_streamable_http_type_inference():
    """Test that servers with 'url' field (but no SSE mention) are inferred as streamable_http type."""
    config_data = {
        "servers": {
            "api_server": {
                "url": "https://api.example.com/mcp"
                # No explicit type - should be inferred as streamable_http
                # No mention of 'sse' in url, name, or description
            },
            "webhook_server": {
                "url": "https://webhook.example.com/mcp/api",
                "headers": {"X-API-Key": "secret123"},
                # No explicit type - should be inferred as streamable_http
            },
        }
    }

    config = MCPServersConfig.model_validate(config_data)

    # Verify first server
    api_server = config.servers["api_server"]
    assert isinstance(api_server, StreamableHTTPServerConfig)
    assert api_server.type == "streamable_http"  # Should be auto-inferred
    assert api_server.url == "https://api.example.com/mcp"
    assert api_server.headers is None

    # Verify second server
    webhook_server = config.servers["webhook_server"]
    assert isinstance(webhook_server, StreamableHTTPServerConfig)
    assert webhook_server.type == "streamable_http"  # Should be auto-inferred
    assert webhook_server.url == "https://webhook.example.com/mcp/api"
    assert webhook_server.headers == {"X-API-Key": "secret123"}
