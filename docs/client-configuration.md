# MCP Client Configuration (NEW)

This guide, for client application developers, covers a new API for client
configuration. Client applications can use this API to get info about configured
MCP servers from configuration files 

## Why should my application use this API?

- Eliminate the need to write and maintain code to parse configuration files
- Your application can easily benefit from bug fixes and new features related to configuration
- Allows your application to support features that other applications may have
  and which your application does not. E.g.,

  - Allow specifying the entire command in the `command` field (not having to
    specify an `args` list), which makes it easier for users to manage
  - Allow comments in JSON configuration files
  - Input variables (as supported by VS Code), plus validation of required inputs
    and interpolation of input values
  - YAML configuration files, which are more readable and easier to write than JSON

- If every application that uses MCP supported this API, it would lead to
  greater consistency in how MCP servers are configured and used, which is a
  tremendous win for users and a benefit to the MCP ecosystem.

## Loading Configuration Files

```python
from mcp.client.config.mcp_servers_config import MCPServersConfig

# Load JSON
config = MCPServersConfig.from_file("~/.cursor/mcp.json")
config = MCPServersConfig.from_file("~/Library/Application\ Support/Claude/claude_desktop_config.json")

# Load YAML (auto-detected by extension)
config = MCPServersConfig.from_file("~/.cursor/mcp.yaml")  # Not yet support in Cursor but maybe soon...?!
config = MCPServersConfig.from_file("~/Library/Application\ Support/Claude/claude_desktop_config.yaml")  # Maybe someday...?!

# Load with input substitution
config = MCPServersConfig.from_file(
    ".vscode/mcp.json",
    inputs={"api-key": "secret"}
)

mcp_server = config.servers["time"]
print(mcp_server.command)
print(mcp_server.args)
print(mcp_server.env)
print(mcp_server.headers)
print(mcp_server.inputs)
print(mcp_server.isActive)
print(mcp_server.effective_command)
print(mcp_server.effective_args)
```

## Configuration File Formats

MCP supports multiple configuration file formats for maximum flexibility.

### JSON Configuration

```json
{
  "mcpServers": {
    "time": {
      "command": "uvx",
      "args": ["mcp-server-time"]
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/Users/username/Desktop"]
    }
  }
}
```

This is a typical JSON configuration file for an MCP server in that it has
`command` and `args` (as a list) fields.

Users can also specify the entire command in the `command` field, which
makes it easier to read and write. Internally, the library splits the command
into `command` and `args` fields, so the result is a nicer user experience and
no application code needs to change.

```json
{
  "mcpServers": {
    "time": {
      "command": "uvx mcp-server-time"
    },
    "filesystem": {
      "command": "npx -y @modelcontextprotocol/server-filesystem /Users/username/Desktop"
    }
  }
}
```

JSON is the most commonly used format for MCP servers, but it has some
limitations, which is why subsequent sections cover other formats, such as JSONC
and YAML.

### JSON with Comments (JSONC)

The API supports JSON files with `//` comments (JSONC), which is very commonly
used in the VS Code ecosystem:

```jsonc
{
  "mcpServers": {
    // Can get current time in various timezones
    "time": {
      "command": "uvx mcp-server-time"
    },

    // Can get the contents of the user's desktop
    "filesystem": {
      "command": "npx -y @modelcontextprotocol/server-filesystem /Users/username/Desktop"
    }
  }
}
```

### YAML Configuration

The API supports YAML configuration files, which offer improved readability,
comments, and the ability to completely sidestep issues with commas, that are
common when working with JSON.

```yaml
mcpServers:
  # Can get current time in various timezones
  time:
    command: uvx mcp-server-time

  # Can get the contents of the user's desktop
  filesystem:
    command: npx -y @modelcontextprotocol/server-filesystem /Users/username/Desktop
```

**Installation**: YAML support requires the optional dependency:

```bash
pip install "mcp[yaml]"
```

## Server Types and Auto-Detection

MCP automatically infers server types based on configuration fields when the
`type` field is omitted:

### Stdio Servers

Servers with a `command` field are automatically detected as `stdio` type:

```yaml
mcpServers:
  python-server:
    command: python -m my_server
    # type: stdio (auto-inferred)
```

### Streamable HTTP Servers

Servers with a `url` field (without SSE keywords) are detected as
`streamable_http` type:

```yaml
mcpServers:
  api-server:
    url: https://api.example.com/mcp
    # type: streamable_http (auto-inferred)
```

### SSE Servers

Servers with a `url` field containing "sse" in the URL, name, or description are
detected as `sse` type:

```yaml
mcpServers:
  sse-server:
    url: https://api.example.com/sse
    # type: sse (auto-inferred due to "sse" in URL)
    
  event-server:
    url: https://api.example.com/events
    description: "SSE-based event server"
    # type: sse (auto-inferred due to "SSE" in description)
```

## Input Variables and Substitution

MCP supports dynamic configuration using input variables, which is a feature
that VS Code supports. This works in both JSON and YAML configurations.

### Declaring Inputs (JSON)

```json
{
  "inputs": [
    {
      "id": "api-key",
      "type": "promptString",
      "description": "Your API key",
      "password": true
    },
    {
      "id": "server-host",
      "type": "promptString",
      "description": "Server hostname"
    }
  ],
  "servers": {
    "dynamic-server": {
      "url": "https://${input:server-host}/mcp",
      "headers": {
        "Authorization": "Bearer ${input:api-key}"
      }
    }
  }
}
```

### Declaring Inputs (YAML)

```yaml
inputs:
  - id: api-key
    type: promptString
    description: "Your API key"
    password: true
  - id: server-host
    type: promptString
    description: "Server hostname"

servers:
  dynamic-server:
    url: https://${input:server-host}/mcp
    headers:
      Authorization: Bearer ${input:api-key}
```

### Getting DeclaredInputs

The application can use the `inputs` field to get the declared inputs and
prompt the user for the values or otherwise allow them to be specified.

The application gets the declared inputs by doing:

```python
config = MCPServersConfig.from_file(".vscode/mcp.json")
for input in config.inputs:
    # Prompt the user for the value
    ...
```

### Using Inputs

When loading the configuration, provide input values:

```python
from mcp.client.config.mcp_servers_config import MCPServersConfig

# Load with input substitution
config = MCPServersConfig.from_file(
    "config.yaml",
    inputs={
        "api-key": "secret-key-123",
        "server-host": "api.example.com"
    }
)
```

### Input Validation

MCP validates that all required inputs are provided:

```python
# Check required inputs
required_inputs = config.get_required_inputs()
print(f"Required inputs: {required_inputs}")

# Validate provided inputs
missing_inputs = config.validate_inputs(provided_inputs)
if missing_inputs:
    print(f"Missing required inputs: {missing_inputs}")
```

## Configuration Schema

### Server Configuration Base Fields

All server types support these common optionalfields:

- `name` (string, optional): Display name for the server
- `description` (string, optional): Server description
- `isActive` (boolean, default: true): Whether the server is active

### Stdio Server Configuration

```yaml
mcpServers:
  stdio-server:
    type: stdio  # Optional if 'command' is present
    command: python -m my_server
    args:  # Optional additional arguments
      - --debug
      - --port=8080
    env:  # Optional environment variables
      DEBUG: "true"
      API_KEY: secret123
```

### Streamable HTTP Server Configuration

```yaml
mcpServers:
  http-server:
    type: streamable_http  # Optional if 'url' is present
    url: https://api.example.com/mcp
    headers:  # Optional HTTP headers
      Authorization: Bearer token123
      X-Custom-Header: value
```

### SSE Server Configuration

```yaml
mcpServers:
  sse-server:
    type: sse
    url: https://api.example.com/sse
    headers:  # Optional HTTP headers
      Authorization: Bearer token123
```

## Field Aliases

MCP supports both traditional and modern field names:

- `mcpServers` (most common) or `servers` (VS Code)

```yaml
# More common format
mcpServers:
  my-server:
    command: python -m server

# VS Code format (equivalent)
servers:
  my-server:
    command: python -m server
```

## Error Handling

### Missing YAML Dependency

```python
try:
    config = MCPServersConfig.from_file("config.yaml")
except ImportError as e:
    print("Install YAML support: pip install 'mcp[yaml]'")
```

### Missing Input Values

```python
try:
    config = MCPServersConfig.from_file("config.yaml", inputs={})
except ValueError as e:
    print(f"Configuration error: {e}")
    # Error: Missing required input values:
    #   - api-key: Your API key
    #   - server-host: Server hostname
```
