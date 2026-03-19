# Troubleshooting

This guide helps you resolve common issues when using the MCP Python SDK.

## 421 Invalid Host Header (DNS Rebinding Protection)

A recent update introduced [DNS rebinding protection](./transports.md#dns-rebinding-protection) to the MCP Python SDK. While this improves security, it may cause existing setups to fail with a **421 Misdirected Request / Invalid Host Header** error if the host header doesn't match the allowed list (common when using proxies, gateways, or custom domains).

### Solutions

Depending on your security requirements, you can resolve this in two ways:

#### Option 1: Explicitly Allow Specific Hosts (Recommended)

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

#### Option 2: Disable DNS Rebinding Protection

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

### Reverse Proxy Configuration

If you are using a reverse proxy (like Nginx or Caddy), ensure your proxy is passing the correct `Host` header to the MCP server.

**Nginx example:**
```nginx
location / {
    proxy_pass http://localhost:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
}
```

**Caddy example:**
```caddy
reverse_proxy localhost:8000 {
    header_up Host {upstream_hostport}
}
```

## See Also

- [Transport Security](./transports.md#dns-rebinding-protection)
- [FastMCP Server Documentation](./servers.md)
