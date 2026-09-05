# OpenTelemetry

Your server is already traced. You don't have to add anything.

Every server you create emits an [OpenTelemetry](https://opentelemetry.io/) span for every
message it handles. You didn't write that, and you don't import it. It is there the moment you
call `MCPServer(...)`.

```python title="server.py"
--8<-- "docs_src/opentelemetry/tutorial001.py"
```

That is a complete, traced server. Call `search_books` and a span is created for it. The same is
true when a client reads `catalog://featured` or renders `reading_prompt`. The low-level `Server`
is traced too.

## What you get

Every inbound message becomes a `SERVER` span named after the method, plus a target for named
operations. So a `tools/call` for `search_books` is the span `tools/call search_books`,
a `prompts/get` for `reading_prompt` is `prompts/get reading_prompt`, and a bare `tools/list`
is just `tools/list`.

Each span carries a few attributes:

* `mcp.method.name` and `mcp.protocol.version`, on every span.
* `jsonrpc.request.id`, on a request (a notification has none).
* A handler that raises sets the span status to error. So does a tool result with `is_error=True`.

And because tracing a tool call is such a common thing to want, `tools/call` spans speak
OpenTelemetry's [GenAI semantic conventions](https://opentelemetry.io/docs/specs/semconv/gen-ai/):

* `gen_ai.operation.name`, set to `"execute_tool"`.
* `gen_ai.tool.name`, set to the tool being called.

A `prompts/get` span gets `gen_ai.prompt.name` in the same spirit. `resources/read` spans are
created by the same middleware and carry the common `mcp.*` attributes; the SDK does not add the
resource URI to the span name or to a `gen_ai.*` attribute today. The list methods carry no
`gen_ai.*` keys, because there is nothing to name.

!!! tip
    Those GenAI attributes are the reason a tracing UI groups your tool calls the way it groups
    any other agent's. You get that grouping for free, with no extra code.

## Adding your own detail

The SDK span wraps the request handler. That means a tool, resource, or prompt function runs with
the SDK-created span already current.

If you need more detail than the default attributes provide, create child spans inside your handler
or in your own middleware. For example, a resource handler can add a child span for a database read,
and a prompt handler can add one for template assembly. Those spans nest under `resources/read` or
`prompts/get`, so a tracing backend still shows one connected request.

## It costs nothing until you want it

Here is the part that makes "on by default" a comfortable default.

The SDK depends only on `opentelemetry-api`, the lightweight half of OpenTelemetry. With no SDK
and no exporter installed, creating a span is a no-op. So the spans your server is emitting right
now cost you almost nothing, and nobody is collecting them.

The day you want to *see* them, you install the other half and point it somewhere:

```console
uv add opentelemetry-sdk opentelemetry-exporter-otlp
```

Configure an exporter the usual OpenTelemetry way, and every span the SDK has been quietly
creating lights up. Your server code does not change. Not one line.

!!! info
    [Pydantic Logfire](https://logfire.pydantic.dev/) is one such backend, and it does the
    configuration for you: `pip install logfire`, `logfire.configure()`, and your MCP spans show
    up in the live view. It is built on OpenTelemetry, so anything below applies to it too.

## Traces that cross the wire

A trace is most useful when it follows a request from the client into the server, in one
connected picture.

When the client and the server both run the SDK, that connection is automatic. The client injects
the [W3C trace context](https://www.w3.org/TR/trace-context/) into the request, and the server
reads it back out, so the server span nests under the client span in the same trace. This is
[SEP-414](https://github.com/modelcontextprotocol/modelcontextprotocol/pull/414), and you get it without
asking.

If the inbound message carries no trace context, for example a request from a client that is not
the SDK, the server span simply parents to whatever span is already current on the server, rather
than starting a brand-new orphan trace.

## Turning it off

Tracing is a middleware, the first one on your server's list. If you really want a server that
emits no spans, take it off:

```python
from mcp.server._otel import OpenTelemetryMiddleware

mcp._lowlevel_server.middleware[:] = [
    m for m in mcp._lowlevel_server.middleware if not isinstance(m, OpenTelemetryMiddleware)
]
```

!!! warning
    That import has a leading underscore, and that is on purpose. The class is provisional, the
    same way [`Server.middleware`](../advanced/middleware.md) is provisional, so the import path is something
    you should expect to change. You almost never need this: with no exporter installed the spans
    are free, so the usual answer is to leave them on and not install an exporter.

## Recap

* Every `MCPServer` and every low-level `Server` emits one `SERVER` span per inbound message, out
  of the box. You write nothing.
* Spans carry `mcp.method.name` and `mcp.protocol.version`; `tools/call` and `prompts/get` also
  carry GenAI attributes so your tool calls group like any other agent's.
* It costs nothing until you install an OpenTelemetry SDK and an exporter, and then it lights up
  with no change to your server.
* Client-to-server trace context propagates automatically when both sides run the SDK.

The thing that decides whether a request runs at all is **[Authorization](authorization.md)**.
