# ETDI Integration Guide

This guide shows how to seamlessly integrate ETDI (Enhanced Tool Definition Interface) into your MCP applications.

## Quick Start

### 1. Installation

```bash
# Clone and setup
git clone <repository>
cd python-sdk
python3 setup_etdi.py
```

### 2. Configuration

```bash
# Initialize ETDI configuration
etdi init-config --provider auth0

# Edit configuration with your OAuth credentials
nano ~/.etdi/config/etdi-config.json
```

### 3. Basic Usage

```python
from mcp.etdi import ETDIClient

# Simple client usage
async with ETDIClient.from_config("~/.etdi/config/etdi-config.json") as client:
    tools = await client.discover_tools()
    for tool in tools:
        if tool.verification_status.value == "verified":
            await client.approve_tool(tool)
```

## Integration Patterns

### Client-Side Integration

#### Replace Standard MCP Client

```python
# Before (standard MCP)
from mcp.client import ClientSession

session = ClientSession()
tools = await session.list_tools()

# After (ETDI-enhanced)
from mcp.etdi import ETDISecureClientSession, ETDIClient

client = ETDIClient(config)
await client.initialize()

session = ETDISecureClientSession(
    verifier=client.verifier,
    approval_manager=client.approval_manager
)
tools = await session.list_tools()  # Now with security verification
```

#### Add Security to Existing Client

```python
from mcp.etdi import ETDIVerifier, ApprovalManager
from mcp.etdi.oauth import OAuthManager

# Add ETDI security to existing MCP client
oauth_manager = OAuthManager()
oauth_manager.register_provider_config("auth0", oauth_config)

verifier = ETDIVerifier(oauth_manager)
approval_manager = ApprovalManager()

# Verify tools before use
for tool in existing_tools:
    result = await verifier.verify_tool(tool)
    if result.valid:
        await approval_manager.approve_tool_with_etdi(tool)
```

### Server-Side Integration

#### Secure Existing MCP Server

```python
# Before (standard MCP server)
from mcp.server.fastmcp import FastMCP

app = FastMCP()

@app.tool()
async def my_tool(param: str) -> str:
    return f"Result: {param}"

# After (ETDI-secured)
from mcp.etdi import ETDISecureServer

app = ETDISecureServer(oauth_configs=[oauth_config])

@app.secure_tool(permissions=["read:data", "execute:tools"])
async def my_tool(param: str) -> str:
    return f"Secure result: {param}"
```

#### Add OAuth to Existing Tools

```python
from mcp.etdi.server import OAuthSecurityMiddleware

# Add security middleware to existing server
middleware = OAuthSecurityMiddleware([oauth_config])
await middleware.initialize()

# Enhance existing tool definitions
enhanced_tool = await middleware.enhance_tool_definition(
    existing_tool_definition,
    provider_name="auth0"
)
```

## OAuth Provider Setup

### Auth0 Setup

1. Create Auth0 Application:
   - Go to Auth0 Dashboard
   - Create new "Machine to Machine" application
   - Authorize for your API
   - Note Client ID, Client Secret, Domain

2. Configure ETDI:
```json
{
  "oauth_config": {
    "provider": "auth0",
    "client_id": "your-client-id",
    "client_secret": "your-client-secret",
    "domain": "your-domain.auth0.com",
    "audience": "https://your-api.example.com",
    "scopes": ["read:tools", "execute:tools"]
  }
}
```

### Okta Setup

1. Create Okta Application:
   - Go to Okta Admin Console
   - Create new "Service" application
   - Configure OAuth settings
   - Note Client ID, Client Secret, Domain

2. Configure ETDI:
```json
{
  "oauth_config": {
    "provider": "okta",
    "client_id": "your-client-id",
    "client_secret": "your-client-secret",
    "domain": "your-domain.okta.com",
    "scopes": ["etdi.tools.read", "etdi.tools.execute"]
  }
}
```

### Azure AD Setup

1. Create Azure AD Application:
   - Go to Azure Portal
   - Register new application
   - Create client secret
   - Configure API permissions

2. Configure ETDI:
```json
{
  "oauth_config": {
    "provider": "azure",
    "client_id": "your-client-id",
    "client_secret": "your-client-secret",
    "domain": "your-tenant-id",
    "scopes": ["https://graph.microsoft.com/.default"]
  }
}
```

## Security Levels

### Basic Security
- Simple cryptographic verification
- No OAuth requirements
- Suitable for development

```python
config = {
    "security_level": "basic",
    "allow_non_etdi_tools": True,
    "show_unverified_tools": True
}
```

### Enhanced Security (Recommended)
- OAuth 2.0 token verification
- Permission-based access control
- Tool change detection

```python
config = {
    "security_level": "enhanced",
    "oauth_config": oauth_config,
    "allow_non_etdi_tools": True,
    "show_unverified_tools": False
}
```

### Strict Security
- Full OAuth enforcement
- No unverified tools allowed
- Maximum security

```python
config = {
    "security_level": "strict",
    "oauth_config": oauth_config,
    "allow_non_etdi_tools": False,
    "show_unverified_tools": False
}
```

## CLI Usage

### Tool Discovery
```bash
# Discover tools with OAuth verification
etdi discover --provider auth0 --client-id <id> --client-secret <secret> --domain <domain>

# Use configuration file
etdi discover --config ~/.etdi/config/etdi-config.json
```

### Token Debugging
```bash
# Debug OAuth token
etdi debug-token <jwt-token>

# Save report to file
etdi debug-token <jwt-token> --format json --output token-report.json
```

### Provider Validation
```bash
# Test OAuth provider connectivity
etdi validate-provider --config ~/.etdi/config/etdi-config.json

# Test specific provider
etdi validate-provider --provider auth0 --client-id <id> --domain <domain>
```

### Security Analysis
```bash
# Analyze tool security
etdi analyze-tool tool-definition.json

# Generate JSON report
etdi analyze-tool tool-definition.json --format json --output security-report.json
```

## Deployment

### Docker Deployment

```bash
# Build and run with Docker Compose
cd deployment/docker
docker-compose up -d

# Check status
docker-compose ps
docker-compose logs etdi-server
```

### Environment Variables

```bash
# Set OAuth credentials
export ETDI_CLIENT_ID="your-client-id"
export ETDI_CLIENT_SECRET="your-client-secret"
export ETDI_DOMAIN="your-domain.auth0.com"
export ETDI_AUDIENCE="https://your-api.example.com"

# Run ETDI server
python -m mcp.etdi.server
```

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: etdi-server
spec:
  replicas: 3
  selector:
    matchLabels:
      app: etdi-server
  template:
    metadata:
      labels:
        app: etdi-server
    spec:
      containers:
      - name: etdi-server
        image: etdi-server:latest
        ports:
        - containerPort: 8000
        env:
        - name: ETDI_CLIENT_ID
          valueFrom:
            secretKeyRef:
              name: etdi-oauth
              key: client-id
        - name: ETDI_CLIENT_SECRET
          valueFrom:
            secretKeyRef:
              name: etdi-oauth
              key: client-secret
```

## Monitoring and Debugging

### Inspector Tools

```python
from mcp.etdi.inspector import SecurityAnalyzer, TokenDebugger, OAuthValidator

# Analyze tool security
analyzer = SecurityAnalyzer()
result = await analyzer.analyze_tool(tool)
print(f"Security Score: {result.overall_security_score}/100")

# Debug OAuth tokens
debugger = TokenDebugger()
debug_info = debugger.debug_token(token)
print(debugger.format_debug_report(debug_info))

# Validate OAuth providers
validator = OAuthValidator()
validation_result = await validator.validate_provider("auth0", oauth_config)
```

### Health Checks

```python
# Check ETDI client health
async with ETDIClient(config) as client:
    stats = await client.get_stats()
    print(f"Healthy providers: {stats['oauth_providers']}")
    print(f"Verification cache: {stats['verification']['cache_size']}")
```

### Logging

```python
import logging

# Enable ETDI logging
logging.getLogger('mcp.etdi').setLevel(logging.INFO)

# Custom log handler
handler = logging.FileHandler('/var/log/etdi.log')
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
logging.getLogger('mcp.etdi').addHandler(handler)
```

## Best Practices

### Security
1. **Use Enhanced or Strict security levels** in production
2. **Rotate OAuth credentials** regularly
3. **Monitor token expiration** and refresh proactively
4. **Audit tool approvals** and permissions regularly
5. **Use HTTPS** for all OAuth communications

### Performance
1. **Enable verification caching** for better performance
2. **Use batch operations** for multiple tools
3. **Monitor cache hit rates** and adjust TTL as needed
4. **Implement connection pooling** for OAuth providers

### Monitoring
1. **Track security events** and approval changes
2. **Monitor OAuth provider health** and response times
3. **Set up alerts** for security violations
4. **Log all tool invocations** for audit trails

### Development
1. **Use Basic security level** for development
2. **Test with multiple OAuth providers** for compatibility
3. **Validate tool definitions** before deployment
4. **Use inspector tools** for debugging

## Troubleshooting

### Common Issues

#### OAuth Token Validation Fails
```bash
# Debug the token
etdi debug-token <token>

# Check provider connectivity
etdi validate-provider --config <config>

# Verify configuration
python -c "from mcp.etdi import OAuthConfig; print(OAuthConfig.from_file('<config>').validate())"
```

#### Tool Discovery Returns Empty
```bash
# Check security level
etdi discover --config <config> --security-level basic

# Verify MCP server connectivity
curl -X POST <mcp-server>/tools

# Check logs
tail -f ~/.etdi/logs/etdi.log
```

#### Permission Denied Errors
```bash
# Check tool approvals
python -c "from mcp.etdi import ApprovalManager; am = ApprovalManager(); print(am.list_approvals())"

# Re-approve tool
etdi approve-tool <tool-id>

# Check permission scopes
etdi analyze-tool <tool-definition>
```

### Getting Help

1. **Check logs**: `~/.etdi/logs/etdi.log`
2. **Run diagnostics**: `etdi --help`
3. **Validate configuration**: `etdi validate-provider`
4. **Test components**: `python -m mcp.etdi.test`
5. **Review examples**: `examples/etdi/`

## Migration Guide

### From Standard MCP

1. **Install ETDI**: Run `python3 setup_etdi.py`
2. **Configure OAuth**: Set up OAuth provider
3. **Update client code**: Replace `ClientSession` with `ETDISecureClientSession`
4. **Update server code**: Replace `FastMCP` with `ETDISecureServer`
5. **Test integration**: Run examples and verify functionality
6. **Deploy gradually**: Start with Basic security, move to Enhanced/Strict

### Backward Compatibility

ETDI maintains backward compatibility with standard MCP:
- Standard MCP tools work with ETDI clients (with warnings)
- ETDI tools work with standard MCP clients (without security)
- Gradual migration is supported through security levels

This integration guide provides everything needed to seamlessly adopt ETDI in your MCP applications.