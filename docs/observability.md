# Observability

MCP applications often need traces, metrics, or structured logs around tool,
resource, and prompt activity. Transport middleware is useful for HTTP-level
events, but MCP primitive activity is best observed at the MCP request layer
where the protocol method and request parameters are still visible.

## Where to Instrument

Use the narrowest layer that has the data you need:

| Layer | Use for | Notes |
| --- | --- | --- |
| ASGI middleware | HTTP status codes, headers, auth, reverse-proxy behavior | This sees transport requests, not every MCP primitive operation. Streamable HTTP and SSE can multiplex multiple MCP messages through a long-lived transport. |
| `Server.middleware` | Server-side MCP requests and notifications | Wraps `initialize`, unknown methods, validation failures, and registered handlers. This is the usual place for server spans around `tools/call`, `resources/read`, and `prompts/get`. |
| Client wrapper code | Client-side outgoing MCP requests | Wrap calls such as `client.call_tool()`, `client.read_resource()`, or `client.get_prompt()` when you want the caller-side span or metric. |
| Handler code | Domain-specific work inside a tool, resource, or prompt | Use this for application details such as database queries, external API calls, cache hits, or business identifiers. |

## Server-Side Middleware

`Server.middleware` runs around every inbound MCP request before params are
validated and before the registered handler is invoked. A middleware can record
duration, success or failure, the protocol method, and a safe target name.

```python title="server_observability.py"
import time
from collections.abc import Mapping
from typing import Any

from mcp.server import Server, ServerRequestContext
from mcp.server.context import CallNext, HandlerResult


async def observe_mcp_request(
    ctx: ServerRequestContext[Any, Any],
    method: str,
    params: Mapping[str, Any] | None,
    call_next: CallNext,
) -> HandlerResult:
    started = time.perf_counter()
    target = params.get("name") if isinstance(params, Mapping) else None

    try:
        result = await call_next()
    except Exception:
        duration_ms = (time.perf_counter() - started) * 1000
        print(
            "mcp.request failed",
            {
                "method": method,
                "target": target,
                "request_id": ctx.request_id,
                "duration_ms": round(duration_ms, 2),
            },
        )
        raise

    duration_ms = (time.perf_counter() - started) * 1000
    print(
        "mcp.request completed",
        {
            "method": method,
            "target": target,
            "request_id": ctx.request_id,
            "duration_ms": round(duration_ms, 2),
        },
    )
    return result


server = Server("observed-server", on_call_tool=...)
server.middleware.append(observe_mcp_request)
```

For OpenTelemetry, the same pattern can create a span around `await call_next()`
instead of printing. Keep exported attributes small and safe: method name,
request id, status, duration, and the prompt/resource/tool name are usually
enough. Avoid recording tool arguments, resource contents, prompt text, tokens,
or authentication data unless your application has explicitly classified them
as safe to export.

## Primitive Span Shape

A practical span and metric shape is:

| MCP method | Suggested span name | Useful attributes |
| --- | --- | --- |
| `tools/call` | `MCP tools/call <name>` | `mcp.method.name`, `mcp.tool.name`, `jsonrpc.request.id`, status |
| `resources/read` | `MCP resources/read <uri-template-or-scheme>` | `mcp.method.name`, a low-cardinality resource identifier, `jsonrpc.request.id`, status |
| `prompts/get` | `MCP prompts/get <name>` | `mcp.method.name`, `mcp.prompt.name`, `jsonrpc.request.id`, status |
| `*/list` | `MCP <method>` | `mcp.method.name`, result count when safe |

Prefer low-cardinality attributes. For example, use a resource scheme or
template name instead of the full resource URI if the URI may contain document
ids, user ids, or file paths.

## Request Tracing vs Primitive Tracing

Request-level tracing answers "which MCP message was handled?" Primitive-level
tracing answers "which tool, resource, or prompt did the application execute?"
Most production systems need both:

1. A request span around the MCP method, created in middleware.
2. Optional child spans inside handlers for application work such as model
   calls, database queries, network calls, or filesystem operations.

Do not rely only on HTTP middleware for primitive tracing. With streamable HTTP
or SSE, HTTP request boundaries do not always line up with MCP method
boundaries, and headers may only be present on the transport request rather
than each MCP message.

## Client-Side Calls

Client applications can use the same naming scheme around outgoing SDK calls:

```python title="client_observability.py"
import time


async def observed_call_tool(client, name: str, arguments: dict):
    started = time.perf_counter()
    try:
        return await client.call_tool(name, arguments)
    finally:
        duration_ms = (time.perf_counter() - started) * 1000
        print(
            "mcp.client.call_tool",
            {"tool": name, "duration_ms": round(duration_ms, 2)},
        )
```

If you propagate trace context between client and server, put it in the MCP
request metadata rather than assuming transport headers will be available for
each logical request.
