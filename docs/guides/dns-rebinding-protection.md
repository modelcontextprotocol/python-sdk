# DNS Rebinding Protection

The MCP Python SDK includes DNS rebinding protection to prevent DNS rebinding attacks. While this improves security, it may cause existing setups to fail with a **421 Misdirected Request / Invalid Host Header** error if the host header doesn't match the allowed list.

This commonly occurs when using:
- Reverse proxies (Nginx, Caddy, etc.)
- API gateways
- Custom domains
- Docker/Kubernetes networking

## Resolving the Error

Depending on your security requirements, you can resolve this in two ways:

### Option 1: Explicitly Allow Specific Hosts (Recommended for Production)

Use this approach if you are running in production or through a gateway. You can wildcard the ports using `*`.

```python
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

mcp = FastMCP(
    "MyServer",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        # Add your specific gateway or domain here
        allowed_hosts=["localhost:*", "127.0.0.1:*", "your-gateway-host:*"],
        allowed_origins=["http://localhost:*", "http://your-gateway-host:*"],
    )
)
```

### Option 2: Disable DNS Rebinding Protection (Development Only)

Use this approach for local development or if you are managing security at a different layer of your infrastructure.

```python
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

mcp = FastMCP(
    "MyServer",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    )
)
```

## Common Scenarios

### Using with Nginx

If you're using Nginx as a reverse proxy, ensure it's passing the correct headers:

```nginx
location / {
    proxy_pass http://localhost:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

And configure your MCP server to allow the Nginx host:

```python
allowed_hosts=["localhost:*", "your-domain.com:*"]
```

### Using with Docker

When running in Docker, you may need to allow the container hostname:

```python
allowed_hosts=["localhost:*", "127.0.0.1:*", "mcp-server:*"]
```

## Security Considerations

- **Production**: Always use Option 1 with explicit host allowlisting
- **Development**: Option 2 is acceptable for local testing
- **Never** disable DNS rebinding protection in production environments exposed to the internet

## Related Issues

- Original implementation: [#861](https://github.com/modelcontextprotocol/python-sdk/pull/861)
- Common errors: [#1797](https://github.com/modelcontextprotocol/python-sdk/issues/1797)
