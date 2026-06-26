"""Tests for the core SEP-2133 extension API (`Extension`, `MCPServer` wiring).

These exercise the closed set of extension contribution kinds - tools,
resources, request methods, and the single `tools/call` interceptor - through
the highest-level public surface (in-memory `Client`), plus the
`compose_tool_call_interceptor` helper directly.
"""

from typing import Any, Literal, cast

import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import CallToolResult, TextContent

from mcp.client.client import Client
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.extension import (
    Extension,
    MethodBinding,
    ResourceBinding,
    ToolBinding,
    compose_tool_call_interceptor,
)
from mcp.server.mcpserver.resources import TextResource

pytestmark = pytest.mark.anyio

_TOOL_META: dict[str, Any] = {"com.example/marker": {"v": 1}}


class _AdditiveExt(Extension):
    """Override `tools()`/`resources()` only - a purely additive extension."""

    identifier = "com.example/additive"

    def tools(self):
        def ping() -> str:
            """Reply with pong."""
            return "pong"

        return [ToolBinding(fn=ping, meta=_TOOL_META)]

    def resources(self):
        return [ResourceBinding(resource=TextResource(uri="ext://greeting", name="greeting", text="hello"))]


class _SettingsExt(Extension):
    """Override `settings()` so the extension advertises a non-empty settings map."""

    identifier = "com.example/settings"

    def settings(self) -> dict[str, Any]:
        return {"feature": {"enabled": True}}


class _PingParams(types.RequestParams):
    pass


class _PingResult(types.Result):
    pong: bool


class _PingRequest(types.Request[_PingParams, Literal["com.example/ping"]]):
    method: Literal["com.example/ping"] = "com.example/ping"
    params: _PingParams


class _MethodExt(Extension):
    """Override `methods()` to serve a new vendor request verb."""

    identifier = "com.example/method"

    def methods(self):
        async def handler(ctx: ServerRequestContext[Any, Any], params: _PingParams) -> _PingResult:
            return _PingResult(pong=True)

        return [MethodBinding("com.example/ping", _PingParams, handler)]


class _ReplacingExt(Extension):
    """Override `intercept_tool_call()` to short-circuit with a fixed result."""

    identifier = "com.example/replacing"

    async def intercept_tool_call(
        self, params: types.CallToolRequestParams, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        return CallToolResult(content=[TextContent(type="text", text="intercepted")])


class _PassThroughExt(Extension):
    """Override `intercept_tool_call()` but always delegate to `call_next` unchanged."""

    identifier = "com.example/passthrough"

    async def intercept_tool_call(
        self, params: types.CallToolRequestParams, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        return await call_next(ctx)


class _DefaultExt(Extension):
    """Override nothing - relies on the base `intercept_tool_call` default (pass through)."""

    identifier = "com.example/default"


class _RecordingExt(Extension):
    """Override `intercept_tool_call()` to record `(identifier, tool_name)` then pass through."""

    def __init__(self, identifier: str, log: list[tuple[str, str]]) -> None:
        self.identifier = identifier
        self._log = log

    async def intercept_tool_call(
        self, params: types.CallToolRequestParams, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        self._log.append((self.identifier, params.name))
        return await call_next(ctx)


def _echo(value: str) -> str:
    """Echo the input value (shared tool body across interceptor tests)."""
    return value


async def test_additive_extension_registers_its_tool_and_resource() -> None:
    """SDK-defined: an `Extension` overriding `tools()`/`resources()` surfaces both
    through `MCPServer`'s normal `list_tools`/`list_resources`, and the tool's
    `_meta` round-trips equal to the exact dict the binding carried (identity can't
    hold - the value is JSON-serialized over the transport)."""
    server = MCPServer("test", extensions=[_AdditiveExt()])

    async with Client(server) as client:
        tools = await client.list_tools()
        resources = await client.list_resources()
        called = await client.call_tool("ping", {})

    assert [t.name for t in tools.tools] == ["ping"]
    assert tools.tools[0].meta == _TOOL_META
    assert called == snapshot(CallToolResult(content=[TextContent(text="pong")], structured_content={"result": "pong"}))
    assert resources == snapshot(
        types.ListResourcesResult(
            resources=[types.Resource(name="greeting", uri="ext://greeting", mime_type="text/plain")]
        )
    )


async def test_extension_settings_advertised_under_server_capabilities() -> None:
    """SDK-defined: `settings()` rides `server/discover` and lands under
    `server_capabilities.extensions[identifier]` on the modern (`auto`) path."""
    server = MCPServer("test", extensions=[_SettingsExt()])

    async with Client(server, mode="auto") as client:
        extensions = client.server_capabilities.extensions

    assert extensions == snapshot({"com.example/settings": {"feature": {"enabled": True}}})


async def test_extension_settings_dropped_on_legacy_handshake() -> None:
    """Pinned gap: the 2025 `ServerCapabilities` wire schema has no `extensions`
    field, so a legacy `initialize` handshake drops the advertised extension even
    though the modern `auto` path carries it."""
    server = MCPServer("test", extensions=[_SettingsExt()])

    async with Client(server, mode="legacy") as client:
        assert client.server_capabilities.extensions is None


def test_duplicate_extension_identifier_raises() -> None:
    """SDK-defined: registering two extensions with the same `identifier` is a
    construction error."""
    with pytest.raises(ValueError):
        MCPServer("test", extensions=[_SettingsExt(), _SettingsExt()])


def test_add_extension_after_construction_rejects_duplicate_identifier() -> None:
    """SDK-defined: `add_extension` enforces the same uniqueness as the constructor."""
    server = MCPServer("test", extensions=[_SettingsExt()])
    with pytest.raises(ValueError):
        server.add_extension(_SettingsExt())


async def test_extension_method_reachable_via_session_send_request() -> None:
    """SDK-defined: an `Extension` overriding `methods()` wires a new request verb
    onto the low-level server, reachable through `client.session.send_request`."""
    server = MCPServer("test", extensions=[_MethodExt()])

    async with Client(server) as client:
        request = _PingRequest(params=_PingParams())
        result = await client.session.send_request(cast("types.ClientRequest", request), _PingResult)

    assert result == snapshot(_PingResult(pong=True))


async def test_pass_through_interceptor_leaves_tool_result_unchanged() -> None:
    """SDK-defined: an extension whose `intercept_tool_call` delegates to
    `call_next` does not alter the underlying tool's `CallToolResult`."""
    server = MCPServer("test", extensions=[_PassThroughExt()])
    server.tool(name="echo")(_echo)

    async with Client(server) as client:
        result = await client.call_tool("echo", {"value": "hi"})

    assert result == snapshot(CallToolResult(content=[TextContent(text="hi")], structured_content={"result": "hi"}))


async def test_short_circuiting_interceptor_replaces_tool_result() -> None:
    """SDK-defined: an extension that returns from `intercept_tool_call` without
    calling `call_next` replaces the tool's result wholesale (the tool never runs)."""
    server = MCPServer("test", extensions=[_ReplacingExt()])
    server.tool(name="echo", structured_output=False)(_echo)

    async with Client(server) as client:
        result = await client.call_tool("echo", {"value": "hi"})

    assert result == snapshot(CallToolResult(content=[TextContent(text="intercepted")]))


def test_plain_extension_installs_no_tool_call_interceptor() -> None:
    """SDK-defined: an extension that does not override `intercept_tool_call` leaves
    `_extension_interceptor` unset and adds no middleware - the composed
    interceptor exists only when at least one extension overrides it."""
    baseline = len(MCPServer("test")._lowlevel_server.middleware)
    server = MCPServer("test", extensions=[_AdditiveExt()])

    assert server._extension_interceptor is None
    assert len(server._lowlevel_server.middleware) == baseline


def test_overriding_extension_installs_one_tool_call_interceptor() -> None:
    """SDK-defined: registering an extension that overrides `intercept_tool_call`
    composes exactly one middleware and records it as `_extension_interceptor`."""
    baseline = len(MCPServer("test")._lowlevel_server.middleware)
    server = MCPServer("test", extensions=[_ReplacingExt()])

    assert server._extension_interceptor is not None
    assert len(server._lowlevel_server.middleware) == baseline + 1
    assert server._lowlevel_server.middleware[-1] is server._extension_interceptor


async def test_default_interceptor_passes_through_alongside_an_overriding_one() -> None:
    """SDK-defined: an extension that does not override `intercept_tool_call` runs the
    base-class default (pass through) when another extension forces the composed
    middleware to exist, leaving the tool result untouched."""
    server = MCPServer("test", extensions=[_DefaultExt(), _PassThroughExt()])
    server.tool(name="echo")(_echo)

    async with Client(server) as client:
        result = await client.call_tool("echo", {"value": "hi"})

    assert result == snapshot(CallToolResult(content=[TextContent(text="hi")], structured_content={"result": "hi"}))


async def test_interceptors_run_in_registration_order_with_threaded_params() -> None:
    """SDK-defined: `compose_tool_call_interceptor` nests extensions first-outermost, so
    two passing-through interceptors record in registration order, each seeing the
    validated `tools/call` params (the real tool name)."""
    log: list[tuple[str, str]] = []
    server = MCPServer(
        "test",
        extensions=[_RecordingExt("com.example/first", log), _RecordingExt("com.example/second", log)],
    )
    server.tool(name="echo")(_echo)

    async with Client(server) as client:
        await client.call_tool("echo", {"value": "hi"})

    assert log == [("com.example/first", "echo"), ("com.example/second", "echo")]


async def test_compose_tool_call_interceptor_passes_through_non_tools_call() -> None:
    """SDK-defined: the composed middleware is a no-op for any method other than
    `tools/call` - it forwards to `call_next` without touching the interceptors."""
    sentinel = types.EmptyResult()

    async def call_next(ctx: ServerRequestContext[Any, Any]) -> HandlerResult:
        return sentinel

    middleware = compose_tool_call_interceptor([_ReplacingExt()])
    ctx = ServerRequestContext(
        session=cast("Any", None),
        lifespan_context={},
        protocol_version="2026-07-28",
        method="tasks/get",
        params={"taskId": "t-1"},
    )

    result = await middleware(ctx, call_next)

    assert result is sentinel
