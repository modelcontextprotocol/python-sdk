# Startup cost

The SDK is arranged so a process pays only for what it actually uses, and pays for
each thing once. Two rules produce that; both are occasionally observable, so they
are written down here.

## What an import loads

`import mcp` loads the protocol types (`mcp_types`) and nothing else: no client, no
server, no web stack, no HTTP client. The client/server names it exports (`mcp.Client`,
`mcp.ClientSession`, `mcp.stdio_server`, ...) and `mcp.types` resolve their home
module on first access and are then cached on the package, so `from mcp import Client`
costs the client import exactly once, when you ask for it.

Importing an entry point loads only its own side: a client entry point
(`import mcp.client.stdio`) never imports the server stack or the HTTP client stack,
which loads with your first URL-shaped `Client`; a server entry point never imports the
client, and a transport-agnostic one (`mcp.server.stdio`, `MCPServer`, the lowlevel
`Server`) never imports the HTTP web stack (starlette's app/request stack,
`sse_starlette`, `uvicorn`) — that loads when you first build an HTTP app
(`streamable_http_app()`, `sse_app()`, a custom route). Because these are import-graph
promises, they are tested: adding an eager import that breaks one fails the suite.

One introspection consequence: `typing.get_type_hints()` on the seven HTTP-app methods
(`Server.streamable_http_app`, `Server.session_manager`, `MCPServer.streamable_http_app`,
`MCPServer.sse_app`, `MCPServer.run_sse_async`, `MCPServer.run_streamable_http_async`,
`MCPServer.session_manager`) raises `NameError`: their annotations name HTTP types that
those modules import for type checkers only. Signatures, static typing, and calling the
methods are unaffected; if you evaluate the hints at runtime, pass the types yourself, e.g.
`typing.get_type_hints(MCPServer.sse_app, localns={"TransportSecuritySettings":
mcp.server.transport_security.TransportSecuritySettings, "Starlette":
starlette.applications.Starlette})`.

## One-time first-use bills

The generated wire types for each protocol version load with the first message a
connection parses for that version, not at import — a connection negotiates one
version, so a process loads that version's models (a few tens of milliseconds once)
and never the other's. Protocol model validators are then built on a model's first use
(validation, dumping, `model_json_schema()`), a few milliseconds once for the models a
message touches; everything after is at full speed. There is no per-call cost.

Reading whole surface maps in `mcp_types.methods` (`.values()`, `.items()`, spreading
one into an extension map) loads both versions' wire types at that moment, and a
server's first elicitation loads the wire types its schema gate validates against.

If pydantic plugins are installed (`logfire`, for example) pydantic loads them at that
first model build. When you are measuring or shaving cold start and don't use them,
export `PYDANTIC_DISABLE_PLUGINS=__all__`.

## Introspecting a model before its first use

Because a model is built on first use, class-level introspection of a protocol model
that nothing in the process has used yet reflects the not-yet-built state:
`inspect.signature(Tool)` shows the generic `(**data)` initializer, and
`Tool.__pydantic_complete__` is `False`. Using the model once, or calling
`Tool.model_rebuild()`, resolves it; from then on introspection is identical to an
eagerly-built model. Instances, validation, serialization, and schemas are unaffected.

## First use from threads

First-use builds are serialised across threads by one process-wide lock, so concurrent
first use is safe. Two consequences worth knowing: generate schemas through the model's
own `Model.model_json_schema()` (pydantic's module-level `pydantic.json_schema.model_json_schema(Model)`
bypasses the serialisation), and don't `fork()` while another thread is mid-way through a
model's first use — the child inherits the held build lock; use the model once first, or the
`spawn` start method.
