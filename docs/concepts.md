# Concepts

!!! warning "Under Construction"

    This page is currently being written. Check back soon for complete documentation.

<!--
  - Server vs Client
  - Three primitives (tools, resources, prompts)
  - Transports (stdio, SSE, streamable HTTP)
  - Context and sessions
  - Lifecycle and state
 -->

## Transport Security

MCP servers that use HTTP transports (SSE or Streamable HTTP) include DNS rebinding
protection via `TransportSecuritySettings`. This guards against attacks where a malicious
page tricks a browser into making requests to a locally running MCP server by spoofing the
`Host` header.

### Default behavior

- **Streamable HTTP** (`streamable_http_app()`) enables protection by default.
- **SSE** (`sse_app()`) disables protection by default for backwards compatibility.
- **stdio** transport is unaffected — it has no network surface.

### Configuring allowed hosts

Set `allowed_hosts` to the hostname(s) your server is reachable at:

```python
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

mcp = MCPServer("My Server")

security = TransportSecuritySettings(
    allowed_hosts=["myserver.example.com"],
)

app = mcp.streamable_http_app(transport_security=security)
```

If `allowed_hosts` is empty while protection is enabled, **all requests will be rejected
with HTTP 421**. A warning is logged at startup to make this misconfiguration visible.

### Wildcard port matching

The `Host` header includes a port when the client connects on a non-default port
(e.g., `myserver.example.com:8080`). Use a `:*` suffix to allow any port for a given
hostname:

```python
security = TransportSecuritySettings(
    allowed_hosts=["localhost:*", "myserver.example.com:*"],
)
```

### TLS termination and reverse proxies

Behind a reverse proxy (nginx, Caddy, an AWS load balancer, etc.), the port that appears
in the `Host` header depends on how the proxy is configured. Common variants:

| Proxy configuration | `Host` header seen by MCP server |
|---|---|
| Proxy strips port (default for HTTPS) | `myserver.example.com` |
| Proxy preserves port | `myserver.example.com:443` |
| Local development | `localhost:8000` |

Because the behavior varies, the safest production setting is the `:*` wildcard:

```python
security = TransportSecuritySettings(
    allowed_hosts=["myserver.example.com:*", "myserver.example.com"],
)
```

Or, if you only need to match any port:

```python
security = TransportSecuritySettings(
    allowed_hosts=["myserver.example.com:*"],
    # "myserver.example.com" (no port) won't match "myserver.example.com:*"
    # Add the bare hostname too if your proxy strips the port
)
```

### Restricting origins

For browser-based MCP clients, you can also restrict which origins are allowed to connect.
Requests without an `Origin` header (e.g., from non-browser clients) are always allowed:

```python
security = TransportSecuritySettings(
    allowed_hosts=["myserver.example.com:*"],
    allowed_origins=["https://myapp.example.com:*"],
)
```

### Disabling protection

Protection can be turned off entirely, for example during local development with a client
that sends unusual headers:

```python
security = TransportSecuritySettings(enable_dns_rebinding_protection=False)
```
