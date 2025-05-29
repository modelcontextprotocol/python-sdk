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
pip install mcp[etdi]
```

For development:
```bash
pip install mcp[etdi,dev]
```

## Quick Start

### ETDI Client

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
azure_config = OAuthConfig(
    provider="azure",
    client_id="your-azure-client-id",
    client_secret="your-azure-client-secret",
    domain="your-tenant-id",
    scopes=["https://graph.microsoft.com/.default"]
)
```

## Security Inspector Tools

ETDI includes built-in security analysis and debugging tools:

### Security Analyzer

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
from mcp.etdi.client import ETDIClient
from mcp.etdi.types import SecurityLevel

# Enable automatic request signing
client = ETDIClient(ETDIClientConfig(
    security_level=SecurityLevel.STRICT,
    enable_request_signing=True
))

await client.initialize()

# All tool invocations to tools requiring signatures will be automatically signed
result = await client.invoke_tool("secure-tool", {"data": "sensitive"})
```

### **Server-Side Request Verification**
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

See the `examples/etdi/` directory for comprehensive examples:

- `basic_usage.py`: Basic ETDI client usage
- `oauth_providers.py`: OAuth provider configurations
- `secure_server_example.py`: Secure server implementation
- `inspector_example.py`: Security analysis tools
- `call_stack_example.py`: Call stack verification
- `caller_callee_authorization_example.py`: Authorization between tools
- `protocol_call_stack_example.py`: Protocol-level call stack analysis
- `e2e_secure_client.py`: End-to-end secure client
- `e2e_secure_server.py`: End-to-end secure server
- `comprehensive_request_signing_example.py`: Complete request signing demo
- `request_signing_example.py`: Request signing implementation details
- `request_signing_server_example.py`: Server-side request verification
- `clean_api_example.py`: Clean API usage patterns
- `test_complete_security.py`: Complete security testing

## Testing

Run the test suite:

```bash
pytest tests/etdi/
```

Run with coverage:

```bash
pytest tests/etdi/ --cov=src/mcp/etdi --cov-report=html
```

Run specific test categories:

```bash
# OAuth provider tests
pytest tests/etdi/test_oauth_providers.py

# Security inspector tests
pytest tests/etdi/test_inspector.py

# Integration tests
pytest tests/etdi/test_integration.py

# Request signing tests
pytest tests/etdi/test_request_signing.py

# Request signing fix tests (protocol extension)
pytest tests/etdi/test_request_signing_fix.py

# ETDI client tests
pytest tests/etdi/test_etdi_client.py

# ETDI implementation tests
pytest tests/etdi/test_etdi_implementation.py

# ETDI-only functionality tests
pytest tests/etdi/test_etdi_only.py
```

## Deployment

### Docker Deployment

```bash
# Build ETDI-enabled container
docker build -f deployment/docker/Dockerfile -t my-etdi-server .

# Run with configuration
docker run -v $(pwd)/deployment/config:/config my-etdi-server
```

### Docker Compose

```bash
# Start complete ETDI environment
docker-compose -f deployment/docker/docker-compose.yml up
```

## Security Considerations

### Tool Verification
- Always verify tools before approval
- Monitor for version and permission changes
- Use appropriate security levels for your environment
- Implement proper call stack depth limits

### OAuth Configuration
- Store OAuth credentials securely
- Use appropriate scopes for your tools
- Implement proper token rotation
- Validate OAuth provider configurations

### Permission Management
- Follow principle of least privilege
- Regularly audit tool permissions
- Monitor approval and usage patterns
- Use fine-grained permission scopes

### Request Signing
- Use strong cryptographic algorithms (RS256, ES256)
- Implement proper key rotation
- Validate signatures on all requests
- Monitor for signature validation failures

## Troubleshooting

### Common Issues

1. **OAuth Token Validation Failures**
   ```bash
   python -m mcp.etdi.cli debug-token --token "your-token"
   ```

2. **Provider Configuration Issues**
   ```bash
   python -m mcp.etdi.cli validate-oauth --config etdi-config.json
   ```

3. **Tool Security Analysis**
   ```bash
   python -m mcp.etdi.cli analyze-tool --tool-id "problematic-tool"
   ```

### Debug Mode

Enable debug logging for detailed troubleshooting:

```python
import logging
logging.getLogger('mcp.etdi').setLevel(logging.DEBUG)
```

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

- [Integration Guide](INTEGRATION_GUIDE.md)
- [API Reference](docs/api.md)
- [Security Best Practices](docs/security.md)

## Support

- [GitHub Issues](https://github.com/modelcontextprotocol/python-sdk/issues)
- [Documentation](https://modelcontextprotocol.io/python)
- [Community Forum](https://community.modelcontextprotocol.io)
