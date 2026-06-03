# Transport Security

HTTP-based MCP transports include optional DNS rebinding protection. This protects local servers from browser-based requests that try to reach a local MCP endpoint through an unexpected `Host` or `Origin` header.

## When protection is enabled automatically

For Streamable HTTP and SSE apps, the SDK enables DNS rebinding protection automatically when the app is created for a loopback host:

- `127.0.0.1`
- `localhost`
- `::1`

In that mode, the SDK allows loopback hosts and origins with any port, such as `localhost:*` and `127.0.0.1:*`.

## Understanding `421 Invalid Host header`

A `421 Invalid Host header` response means DNS rebinding protection is enabled and the incoming `Host` header is not in `allowed_hosts`.

This commonly happens when a local server is reached through a different hostname, for example:

- a reverse proxy
- a tunnel
- a container or Kubernetes ingress
- a custom development domain

Configure the expected external host instead of disabling protection by default.

```python
from mcp.server.transport_security import TransportSecuritySettings

transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=["mcp.example.com"],
    allowed_origins=["https://mcp.example.com"],
)

app = server.streamable_http_app(
    host="0.0.0.0",
    transport_security=transport_security,
)
```

## Allowing development ports

Use a `:*` suffix when the port changes between runs:

```python
from mcp.server.transport_security import TransportSecuritySettings

transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=True,
    allowed_hosts=["localhost:*", "127.0.0.1:*"],
    allowed_origins=["http://localhost:*", "http://127.0.0.1:*"],
)
```

The wildcard only matches the port portion. For example, `localhost:*` allows `localhost:8000`, not arbitrary hostnames.

## Origin handling

Requests without an `Origin` header are allowed because same-origin and non-browser clients may omit it.

If an `Origin` header is present and not allowed, the SDK returns `403 Invalid Origin header`.

## Disabling protection

Only disable DNS rebinding protection when another trusted layer already validates requests, such as a reverse proxy or gateway that enforces the expected host and origin.

```python
from mcp.server.transport_security import TransportSecuritySettings

transport_security = TransportSecuritySettings(
    enable_dns_rebinding_protection=False,
)
```

Prefer configuring `allowed_hosts` and `allowed_origins` whenever possible.
