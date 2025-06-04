# Model Context Protocol Python SDK with ETDI Security

A Python implementation of the Model Context Protocol (MCP) with Enhanced Tool Definition Interface (ETDI) security extensions that **seamlessly integrates** with existing MCP infrastructure.

## Overview

This SDK provides a secure implementation of MCP with OAuth 2.0-based security enhancements to prevent Tool Poisoning and Rug Pull attacks. ETDI adds cryptographic verification, immutable versioned definitions, and explicit permission management to the MCP ecosystem **while maintaining full compatibility** with existing MCP servers and clients.

## 🔄 **Seamless MCP Integration**

ETDI is designed for **zero-friction adoption** with existing MCP infrastructure:

### **✅ Backward Compatibility**
- **Existing MCP servers work unchanged** - ETDI clients can discover and use any MCP server
- **Existing MCP clients work unchanged** - ETDI servers are fully MCP-compatible
- **Gradual migration path** - Add security incrementally without breaking existing workflows
- **Optional security** - ETDI features are opt-in, not mandatory

### **🔌 Drop-in Integration**
```python
# Existing FastMCP server becomes ETDI-secured with decorator
from mcp.server.fastmcp import FastMCP

app = FastMCP("My Server")

# Standard tool (no security)
@app.tool()
def standard_tool(data: str) -> str:
    return f"Processed: {data}"

# ETDI-secured tool with OAuth + Request Signing
@app.tool(
    etdi=True,
    etdi_permissions=["data:read", "data:write"],
    etdi_oauth_scopes=["tools:execute"],
    etdi_require_request_signing=True
)
def secure_tool(sensitive_data: str) -> str:
    return f"Securely processed: {sensitive_data}"
```

### **🌐 Universal Discovery**
```python
# ETDI client discovers ALL MCP servers (ETDI and non-ETDI)
from mcp.etdi.client import ETDIClient

client = ETDIClient(config)
await client.connect_to_server(["python", "-m", "any_mcp_server"], "server-name")
tools = await client.discover_tools()  # Works with any MCP server!
```

## Features

### Core MCP Functionality
- **Client/Server Architecture**: Full MCP client and server implementations
- **Tool Management**: Register, discover, and invoke tools
- **Resource Access**: Secure access to external resources
- **Prompt Templates**: Reusable prompt templates for LLM interactions
- **🔄 Full MCP Compatibility**: Works with any existing MCP server or client

### ETDI Security Enhancements
- **OAuth 2.0 Integration**: Support for Auth0, Okta, Azure AD, and custom providers
- **Tool Verification**: Cryptographic verification of tool authenticity
- **Permission Management**: Fine-grained permission control with OAuth scopes
- **Version Control**: Automatic detection of tool changes requiring re-approval
- **Approval Management**: Encrypted storage of user tool approvals
- **Request Signing**: RSA/ECDSA cryptographic signing for enhanced security
- **Security Inspector Tools**: Built-in tools for security analysis and debugging

### Security Features
- **Tool Poisoning Prevention**: Cryptographic verification prevents malicious tool impersonation
- **Rug Pull Protection**: Version and permission change detection prevents unauthorized modifications
- **Multiple Security Levels**: Basic, Enhanced, and Strict security modes
- **Audit Logging**: Comprehensive security event logging
- **Call Stack Verification**: Prevents unauthorized nested tool calls
- **🛡️ Non-Breaking Security**: Security features don't break existing MCP workflows

## Installation

```bash
mcp dev server.py
```

## What is MCP?

The [Model Context Protocol (MCP)](https://modelcontextprotocol.io) lets you build servers that expose data and functionality to LLM applications in a secure, standardized way. Think of it like a web API, but specifically designed for LLM interactions. MCP servers can:

- Expose data through **Resources** (think of these sort of like GET endpoints; they are used to load information into the LLM's context)
- Provide functionality through **Tools** (sort of like POST endpoints; they are used to execute code or otherwise produce a side effect)
- Define interaction patterns through **Prompts** (reusable templates for LLM interactions)
- And more!

## Core Concepts

### Server

The FastMCP server is your core interface to the MCP protocol. It handles connection management, protocol compliance, and message routing:

```python
# Add lifespan support for startup/shutdown with strong typing
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass

from fake_database import Database  # Replace with your actual DB type

from mcp.server.fastmcp import FastMCP

# Create a named server
mcp = FastMCP("My App")

# Specify dependencies for deployment and development
mcp = FastMCP("My App", dependencies=["pandas", "numpy"])


@dataclass
class AppContext:
    db: Database


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    """Manage application lifecycle with type-safe context"""
    # Initialize on startup
    db = await Database.connect()
    try:
        yield AppContext(db=db)
    finally:
        # Cleanup on shutdown
        await db.disconnect()


# Pass lifespan to server
mcp = FastMCP("My App", lifespan=app_lifespan)


# Access type-safe lifespan context in tools
@mcp.tool()
def query_db() -> str:
    """Tool that uses initialized resources"""
    ctx = mcp.get_context()
    db = ctx.request_context.lifespan_context["db"]
    return db.query()
```

### Resources

Resources are how you expose data to LLMs. They're similar to GET endpoints in a REST API - they provide data but shouldn't perform significant computation or have side effects:

```python
import asyncio
from mcp.etdi import ETDIClient, OAuthConfig, SecurityLevel

async def main():
    # Configure OAuth provider
    oauth_config = OAuthConfig(
        provider="auth0",
        client_id="your-client-id",
        client_secret="your-client-secret",
        domain="your-domain.auth0.com",
        audience="https://your-api.example.com",
        scopes=["read:tools", "execute:tools"]
    )
    
    # Initialize ETDI client
    async with ETDIClient({
        "security_level": SecurityLevel.ENHANCED,
        "oauth_config": oauth_config.to_dict(),
        "allow_non_etdi_tools": True,
        "show_unverified_tools": False
    }) as client:
        
        # Connect to MCP servers
        await client.connect_to_server(["python", "-m", "my_server"], "my-server")
        
        # Discover and verify tools
        tools = await client.discover_tools()
        
        for tool in tools:
            if tool.verification_status.value == "verified":
                # Approve tool for usage
                await client.approve_tool(tool)
                
                # Invoke tool
                result = await client.invoke_tool(tool.id, {"param": "value"})
                print(f"Result: {result}")

asyncio.run(main())
```

### ETDI Secure Server

```python
import asyncio
from mcp.etdi.server import ETDISecureServer
from mcp.etdi import OAuthConfig

async def main():
    # Configure OAuth
    oauth_configs = [
        OAuthConfig(
            provider="auth0",
            client_id="your-client-id",
            client_secret="your-client-secret",
            domain="your-domain.auth0.com",
            audience="https://your-api.example.com",
            scopes=["read:tools", "execute:tools"]
        )
    ]
    
    # Create secure server
    server = ETDISecureServer(oauth_configs)
    
    # Register secure tool
    @server.secure_tool(permissions=["read:data", "write:data"])
    async def secure_calculator(operation: str, a: float, b: float) -> float:
        """A secure calculator with OAuth protection"""
        if operation == "add":
            return a + b
        elif operation == "multiply":
            return a * b
        else:
            raise ValueError(f"Unknown operation: {operation}")
    
    await server.initialize()
    print("Secure server running with OAuth protection")

asyncio.run(main())
```

## OAuth Provider Configuration

### Auth0

```python
from mcp.etdi import OAuthConfig

auth0_config = OAuthConfig(
    provider="auth0",
    client_id="your-auth0-client-id",
    client_secret="your-auth0-client-secret",
    domain="your-domain.auth0.com",
    audience="https://your-api.example.com",
    scopes=["read:tools", "execute:tools"]
)
```

### Okta

```python
okta_config = OAuthConfig(
    provider="okta",
    client_id="your-okta-client-id",
    client_secret="your-okta-client-secret",
    domain="your-domain.okta.com",
    scopes=["etdi.tools.read", "etdi.tools.execute"]
)
```

### Azure AD

```python
from mcp.server.fastmcp import FastMCP, Context

mcp = FastMCP("My App")


@mcp.tool()
async def long_task(files: list[str], ctx: Context) -> str:
    """Process multiple files with progress tracking"""
    for i, file in enumerate(files):
        ctx.info(f"Processing {file}")
        await ctx.report_progress(i, len(files))
        data, mime_type = await ctx.read_resource(f"file://{file}")
    return "Processing complete"
```

### Authentication

Authentication can be used by servers that want to expose tools accessing protected resources.

`mcp.server.auth` implements an OAuth 2.0 server interface, which servers can use by
providing an implementation of the `OAuthAuthorizationServerProvider` protocol.

```python
from mcp import FastMCP
from mcp.server.auth.provider import OAuthAuthorizationServerProvider
from mcp.server.auth.settings import (
    AuthSettings,
    ClientRegistrationOptions,
    RevocationOptions,
)


class MyOAuthServerProvider(OAuthAuthorizationServerProvider):
    # See an example on how to implement at `examples/servers/simple-auth`
    ...


mcp = FastMCP(
    "My App",
    auth_server_provider=MyOAuthServerProvider(),
    auth=AuthSettings(
        issuer_url="https://myapp.com",
        revocation_options=RevocationOptions(
            enabled=True,
        ),
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["myscope", "myotherscope"],
            default_scopes=["myscope"],
        ),
        required_scopes=["myscope"],
    ),
)
```

See [OAuthAuthorizationServerProvider](src/mcp/server/auth/provider.py) for more details.

## Running Your Server

### Development Mode

The fastest way to test and debug your server is with the MCP Inspector:

```bash
mcp dev server.py

# Add dependencies
mcp dev server.py --with pandas --with numpy

# Mount local code
mcp dev server.py --with-editable .
```

### Claude Desktop Integration

Once your server is ready, install it in Claude Desktop:

```bash
mcp install server.py

# Custom name
mcp install server.py --name "My Analytics Server"

# Environment variables
mcp install server.py -v API_KEY=abc123 -v DB_URL=postgres://...
mcp install server.py -f .env
```

### Direct Execution

For advanced scenarios like custom deployments:

```python
from mcp.etdi.inspector import SecurityAnalyzer

analyzer = SecurityAnalyzer()

# Analyze tool security
result = await analyzer.analyze_tool(tool_definition)
print(f"Security Score: {result.security_score}")
print(f"Vulnerabilities: {result.vulnerabilities}")
```

### Token Debugger

```python
from mcp.etdi.inspector import TokenDebugger

debugger = TokenDebugger()

# Debug JWT tokens
debug_info = await debugger.debug_token(jwt_token)
print(f"Token valid: {debug_info.valid}")
print(f"Claims: {debug_info.claims}")
print(f"Issues: {debug_info.issues}")
```

### OAuth Validator

```python
from mcp.etdi.inspector import OAuthValidator

validator = OAuthValidator()

# Validate OAuth configuration
result = await validator.validate_provider("auth0", oauth_config)
print(f"Configuration valid: {result.configuration_valid}")
print(f"Provider reachable: {result.is_reachable}")
```

## CLI Tools

ETDI provides command-line tools for configuration and debugging:

```bash
# Initialize ETDI configuration
python -m mcp.etdi.cli init --provider auth0

# Validate OAuth configuration
python -m mcp.etdi.cli validate-oauth --config etdi-config.json

# Debug JWT tokens
python -m mcp.etdi.cli debug-token --token "eyJ..."

# Analyze tool security
python -m mcp.etdi.cli analyze-tool --tool-id "my-tool"
```

## Security Levels

### Basic
- Simple cryptographic verification
- No OAuth requirements
- Suitable for development and testing

### Enhanced (Recommended)
- OAuth 2.0 token verification
- Permission-based access control
- Tool change detection
- Suitable for production use

### Strict
- Full OAuth enforcement
- Request signing required
- No unverified tools allowed
- Maximum security for sensitive environments

## Architecture

### Client-Side Components
- **ETDIClient**: Main client interface with security verification
- **ETDIVerifier**: OAuth token verification and change detection
- **ApprovalManager**: Encrypted storage of user approvals
- **SecureSession**: Enhanced MCP client session with security

### Server-Side Components
- **ETDISecureServer**: OAuth-protected MCP server
- **SecurityMiddleware**: Security middleware for tool protection
- **TokenManager**: OAuth token lifecycle management
- **ToolProvider**: Secure tool registration and management

### OAuth Providers
- **Auth0Provider**: Auth0 integration with JWKS validation
- **OktaProvider**: Okta integration with custom scopes
- **AzureADProvider**: Azure AD integration with tenant support
- **OAuthManager**: Multi-provider management and failover

### Inspector Tools
- **SecurityAnalyzer**: Tool security analysis and scoring
- **TokenDebugger**: JWT token debugging and validation
- **OAuthValidator**: OAuth configuration validation
- **CallStackVerifier**: Call stack verification and analysis

## Request Signing

ETDI supports cryptographic request signing with RSA-SHA256 signatures embedded directly in MCP protocol messages:

### **Client-Side Request Signing**
```python
# main.py
import contextlib
from fastapi import FastAPI
from mcp.echo import echo
from mcp.math import math


# Create a combined lifespan to manage both session managers
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(echo.mcp.session_manager.run())
        await stack.enter_async_context(math.mcp.session_manager.run())
        yield


app = FastAPI(lifespan=lifespan)
app.mount("/echo", echo.mcp.streamable_http_app())
app.mount("/math", math.mcp.streamable_http_app())
```

For low level server with Streamable HTTP implementations, see:
- Stateful server: [`examples/servers/simple-streamablehttp/`](examples/servers/simple-streamablehttp/)
- Stateless server: [`examples/servers/simple-streamablehttp-stateless/`](examples/servers/simple-streamablehttp-stateless/)

The streamable HTTP transport supports:
- Stateful and stateless operation modes
- Resumability with event stores
- JSON or SSE response formats
- Better scalability for multi-node deployments

### Mounting to an Existing ASGI Server

> **Note**: SSE transport is being superseded by [Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http).

By default, SSE servers are mounted at `/sse` and Streamable HTTP servers are mounted at `/mcp`. You can customize these paths using the methods described below.

You can mount the SSE server to an existing ASGI server using the `sse_app` method. This allows you to integrate the SSE server with other ASGI applications.

```python
from mcp.server.fastmcp import FastMCP

app = FastMCP("Secure Server")

# Tool requiring cryptographic request signatures
@app.tool(
    etdi=True,
    etdi_require_request_signing=True,
    etdi_permissions=["banking:transfer"]
)
def transfer_funds(amount: float, to_account: str) -> str:
    """High-security tool requiring signed requests"""
    return f"Transferred ${amount} to {to_account}"

# Initialize request signing verification
app.initialize_request_signing()
```

### **How It Works**
1. **Client generates RSA key pair** automatically
2. **Signs tool invocation** with private key
3. **Embeds signature in MCP request parameters** (not transport headers)
4. **Server extracts signature** from MCP request
5. **Verifies signature** using client's public key
6. **Enforces in STRICT mode** only

### **Protocol Integration**
Request signing extends the MCP protocol itself using the `extra="allow"` feature:

```python
# Standard MCP request
{
  "method": "tools/call",
  "params": {
    "name": "my_tool",
    "arguments": {"param": "value"}
  }
}

# ETDI signed request (backward compatible)
{
  "method": "tools/call",
  "params": {
    "name": "my_tool",
    "arguments": {"param": "value"},
    "etdi_signature": "base64-encoded-signature",
    "etdi_timestamp": "2024-01-01T12:00:00Z",
    "etdi_key_id": "client-key-id",
    "etdi_algorithm": "RS256"
  }
}
```

This approach ensures **full compatibility** with all MCP transports (stdio, websocket, SSE) without requiring transport-layer modifications.

## Examples

### Echo Server

A simple server demonstrating resources, tools, and prompts:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("Echo")


@mcp.resource("echo://{message}")
def echo_resource(message: str) -> str:
    """Echo a message as a resource"""
    return f"Resource echo: {message}"


@mcp.tool()
def echo_tool(message: str) -> str:
    """Echo a message as a tool"""
    return f"Tool echo: {message}"


@mcp.prompt()
def echo_prompt(message: str) -> str:
    """Create an echo prompt"""
    return f"Please process this message: {message}"
```

### SQLite Explorer

A more complex example showing database integration:

```python
import sqlite3

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("SQLite Explorer")


@mcp.resource("schema://main")
def get_schema() -> str:
    """Provide the database schema as a resource"""
    conn = sqlite3.connect("database.db")
    schema = conn.execute("SELECT sql FROM sqlite_master WHERE type='table'").fetchall()
    return "\n".join(sql[0] for sql in schema if sql[0])


@mcp.tool()
def query_data(sql: str) -> str:
    """Execute SQL queries safely"""
    conn = sqlite3.connect("database.db")
    try:
        result = conn.execute(sql).fetchall()
        return "\n".join(str(row) for row in result)
    except Exception as e:
        return f"Error: {str(e)}"
```

## Advanced Usage

### Low-Level Server

For more control, you can use the low-level server implementation directly. This gives you full access to the protocol and allows you to customize every aspect of your server, including lifecycle management through the lifespan API:

```python
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fake_database import Database  # Replace with your actual DB type

from mcp.server import Server


@asynccontextmanager
async def server_lifespan(server: Server) -> AsyncIterator[dict]:
    """Manage server startup and shutdown lifecycle."""
    # Initialize resources on startup
    db = await Database.connect()
    try:
        yield {"db": db}
    finally:
        # Clean up on shutdown
        await db.disconnect()


# Pass lifespan to server
server = Server("example-server", lifespan=server_lifespan)


# Access lifespan context in handlers
@server.call_tool()
async def query_db(name: str, arguments: dict) -> list:
    ctx = server.request_context
    db = ctx.lifespan_context["db"]
    return await db.query(arguments["query"])
```

The lifespan API provides:
- A way to initialize resources when the server starts and clean them up when it stops
- Access to initialized resources through the request context in handlers
- Type-safe context passing between lifespan and request handlers

```python
import mcp.server.stdio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions

# Create a server instance
server = Server("example-server")


@server.list_prompts()
async def handle_list_prompts() -> list[types.Prompt]:
    return [
        types.Prompt(
            name="example-prompt",
            description="An example prompt template",
            arguments=[
                types.PromptArgument(
                    name="arg1", description="Example argument", required=True
                )
            ],
        )
    ]


@server.get_prompt()
async def handle_get_prompt(
    name: str, arguments: dict[str, str] | None
) -> types.GetPromptResult:
    if name != "example-prompt":
        raise ValueError(f"Unknown prompt: {name}")

    return types.GetPromptResult(
        description="Example prompt",
        messages=[
            types.PromptMessage(
                role="user",
                content=types.TextContent(type="text", text="Example prompt text"),
            )
        ],
    )


async def run():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="example",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
```

Caution: The `mcp run` and `mcp dev` tool doesn't support low-level server.

### Writing MCP Clients

The SDK provides a high-level client interface for connecting to MCP servers using various [transports](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports):

```python
from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client

# Create server parameters for stdio connection
server_params = StdioServerParameters(
    command="python",  # Executable
    args=["example_server.py"],  # Optional command line arguments
    env=None,  # Optional environment variables
)


# Optional: create a sampling callback
async def handle_sampling_message(
    message: types.CreateMessageRequestParams,
) -> types.CreateMessageResult:
    return types.CreateMessageResult(
        role="assistant",
        content=types.TextContent(
            type="text",
            text="Hello, world! from model",
        ),
        model="gpt-3.5-turbo",
        stopReason="endTurn",
    )


async def run():
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(
            read, write, sampling_callback=handle_sampling_message
        ) as session:
            # Initialize the connection
            await session.initialize()

            # List available prompts
            prompts = await session.list_prompts()

            # Get a prompt
            prompt = await session.get_prompt(
                "example-prompt", arguments={"arg1": "value"}
            )

            # List available resources
            resources = await session.list_resources()

            # List available tools
            tools = await session.list_tools()

            # Read a resource
            content, mime_type = await session.read_resource("file://some/path")

            # Call a tool
            result = await session.call_tool("tool-name", arguments={"arg1": "value"})


if __name__ == "__main__":
    import asyncio

    asyncio.run(run())
```

Clients can also connect using [Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-03-26/basic/transports#streamable-http):

```python
from mcp.client.streamable_http import streamablehttp_client
from mcp import ClientSession


async def main():
    # Connect to a streamable HTTP server
    async with streamablehttp_client("example/mcp") as (
        read_stream,
        write_stream,
        _,
    ):
        # Create a session using the client streams
        async with ClientSession(read_stream, write_stream) as session:
            # Initialize the connection
            await session.initialize()
            # Call a tool
            tool_result = await session.call_tool("echo", {"message": "hello"})
```

### OAuth Authentication for Clients

The SDK includes [authorization support](https://modelcontextprotocol.io/specification/2025-03-26/basic/authorization) for connecting to protected MCP servers:

```python
from mcp.client.auth import OAuthClientProvider, TokenStorage
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken


class CustomTokenStorage(TokenStorage):
    """Simple in-memory token storage implementation."""

    async def get_tokens(self) -> OAuthToken | None:
        pass

    async def set_tokens(self, tokens: OAuthToken) -> None:
        pass

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        pass

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        pass


async def main():
    # Set up OAuth authentication
    oauth_auth = OAuthClientProvider(
        server_url="https://api.example.com",
        client_metadata=OAuthClientMetadata(
            client_name="My Client",
            redirect_uris=["http://localhost:3000/callback"],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        ),
        storage=CustomTokenStorage(),
        redirect_handler=lambda url: print(f"Visit: {url}"),
        callback_handler=lambda: ("auth_code", None),
    )

    # Use with streamable HTTP client
    async with streamablehttp_client(
        "https://api.example.com/mcp", auth=oauth_auth
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            # Authenticated session ready
```

For a complete working example, see [`examples/clients/simple-auth-client/`](examples/clients/simple-auth-client/).


### MCP Primitives

The MCP protocol defines three core primitives that servers can implement:

| Primitive | Control               | Description                                         | Example Use                  |
|-----------|-----------------------|-----------------------------------------------------|------------------------------|
| Prompts   | User-controlled       | Interactive templates invoked by user choice        | Slash commands, menu options |
| Resources | Application-controlled| Contextual data managed by the client application   | File contents, API responses |
| Tools     | Model-controlled      | Functions exposed to the LLM to take actions        | API calls, data updates      |

### Server Capabilities

MCP servers declare capabilities during initialization:

| Capability  | Feature Flag                 | Description                        |
|-------------|------------------------------|------------------------------------|
| `prompts`   | `listChanged`                | Prompt template management         |
| `resources` | `subscribe`<br/>`listChanged`| Resource exposure and updates      |
| `tools`     | `listChanged`                | Tool discovery and execution       |
| `logging`   | -                            | Server logging configuration       |
| `completion`| -                            | Argument completion suggestions    |

## Documentation

- [Model Context Protocol documentation](https://modelcontextprotocol.io)
- [Model Context Protocol specification](https://spec.modelcontextprotocol.io)
- [Officially supported servers](https://github.com/modelcontextprotocol/servers)

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Run the test suite
6. Submit a pull request

## License

MIT License - see LICENSE file for details.

## Documentation

- [Integration Guide](https://github.com/vineethsai/python-sdk/blob/main/INTEGRATION_GUIDE.md)
- [API Reference](https://github.com/vineethsai/python-sdk/blob/main/docs/api.md)
- [Security Best Practices](https://github.com/vineethsai/python-sdk/blob/main/docs/security-features.md)

## Support

- [GitHub Issues](https://github.com/modelcontextprotocol/python-sdk/issues)
- [Documentation](https://modelcontextprotocol.io/python)
- [Community Forum](https://community.modelcontextprotocol.io)
