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
from mcp_types import (
    METHOD_NOT_FOUND,
    MISSING_REQUIRED_CLIENT_CAPABILITY,
    CallToolResult,
    TextContent,
)

from mcp.client import advertise
from mcp.client.client import Client
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.extension import (
    Extension,
    MethodBinding,
    ResourceBinding,
    ToolBinding,
    compose_tool_call_interceptor,
)
from mcp.server.mcpserver import Context, MCPServer, require_client_extension
from mcp.server.mcpserver.resources import TextResource
from mcp.shared.exceptions import MCPError

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


async def _pong_handler(ctx: ServerRequestContext[Any, Any], params: _PingParams) -> _PingResult:
    """The shared `com.example/ping` handler (dispatched by the reachability test)."""
    return _PingResult(pong=True)


class _MethodExt(Extension):
    """Override `methods()` to serve a new vendor request verb."""

    identifier = "com.example/method"

    def methods(self) -> list[MethodBinding]:
        return [MethodBinding("com.example/ping", _PingParams, _pong_handler)]


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


async def test_extension_method_reachable_via_session_send_request() -> None:
    """SDK-defined: an `Extension` overriding `methods()` wires a new request verb
    onto the low-level server, reachable through `client.session.send_request`."""
    server = MCPServer("test", extensions=[_MethodExt()])

    async with Client(server) as client:
        request = _PingRequest(params=_PingParams())
        result = await client.session.send_request(request, _PingResult)

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
    """SDK-defined: an extension that does not override `intercept_tool_call` adds no
    middleware - the composed interceptor exists only when at least one extension
    overrides it."""
    baseline = len(MCPServer("test")._lowlevel_server.middleware)
    server = MCPServer("test", extensions=[_AdditiveExt()])

    assert len(server._lowlevel_server.middleware) == baseline


def test_overriding_extension_installs_one_tool_call_interceptor() -> None:
    """SDK-defined: an extension that overrides `intercept_tool_call` composes exactly
    one additional `tools/call` middleware."""
    baseline = len(MCPServer("test")._lowlevel_server.middleware)
    server = MCPServer("test", extensions=[_ReplacingExt()])

    assert len(server._lowlevel_server.middleware) == baseline + 1


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


def test_extension_subclass_without_prefixed_identifier_is_rejected_at_definition() -> None:
    """SDK-defined: SEP-2133 requires a `vendor-prefix/name` identifier, enforced when the
    subclass is defined (a bare name with no prefix is a TypeError)."""
    with pytest.raises(TypeError):
        type("_BadExt", (Extension,), {"identifier": "noprefix"})


def test_extension_without_identifier_is_rejected_at_registration() -> None:
    """SDK-defined: a subclass that never sets `identifier` (neither class-level nor in
    `__init__`) is rejected when the server applies it."""

    class _NoIdExt(Extension):
        pass

    with pytest.raises(TypeError):
        MCPServer("test", extensions=[_NoIdExt()])


class _VersionPinnedParams(types.RequestParams):
    pass


class _VersionPinnedResult(types.Result):
    ok: bool


class _VersionPinnedRequest(types.Request[_VersionPinnedParams, Literal["com.example/pinned"]]):
    method: Literal["com.example/pinned"] = "com.example/pinned"
    params: _VersionPinnedParams


class _VersionPinnedExt(Extension):
    """A method scoped to 2026-07-28 only via `MethodBinding.protocol_versions`."""

    identifier = "com.example/pinned"

    def methods(self):
        async def handler(ctx: ServerRequestContext[Any, Any], params: _VersionPinnedParams) -> _VersionPinnedResult:
            return _VersionPinnedResult(ok=True)

        return [MethodBinding("com.example/pinned", _VersionPinnedParams, handler, frozenset({"2026-07-28"}))]


async def test_version_pinned_method_is_served_at_an_allowed_version() -> None:
    """SDK-defined: a `MethodBinding` with `protocol_versions` serves the method at a version
    in the set."""
    server = MCPServer("test", extensions=[_VersionPinnedExt()])

    async with Client(server, mode="2026-07-28") as client:
        request = _VersionPinnedRequest(params=_VersionPinnedParams())
        result = await client.session.send_request(request, _VersionPinnedResult)

    assert result == snapshot(_VersionPinnedResult(ok=True))


async def test_version_pinned_method_is_method_not_found_at_a_disallowed_version() -> None:
    """SDK-defined: the same method at a version outside `protocol_versions` is rejected with
    METHOD_NOT_FOUND, mirroring the spec's per-version boundary."""
    server = MCPServer("test", extensions=[_VersionPinnedExt()])

    async with Client(server, mode="legacy") as client:
        request = _VersionPinnedRequest(params=_VersionPinnedParams())
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(request, _VersionPinnedResult)

    assert exc_info.value.code == METHOD_NOT_FOUND
    assert exc_info.value.error.data == "com.example/pinned"


@pytest.mark.parametrize("method", ["tools/list", "completion/complete"])
def test_method_binding_rejects_spec_methods(method: str) -> None:
    """SDK-defined: extension methods are additive — binding a spec-defined request method
    would silently shadow (or be shadowed by) the server's own handler, so it is rejected
    when the binding is constructed."""
    with pytest.raises(ValueError):
        MethodBinding(method, _PingParams, _pong_handler)


def test_method_binding_rejects_empty_protocol_versions() -> None:
    """SDK-defined: an empty `protocol_versions` set would make the method unreachable at
    every version; `None` is the universal-version spelling."""
    with pytest.raises(ValueError) as exc_info:
        MethodBinding("com.example/dead", _PingParams, _pong_handler, frozenset())
    assert str(exc_info.value) == snapshot(
        "MethodBinding for 'com.example/dead' has an empty protocol_versions set, so it could "
        "never be served; use None to admit every version"
    )


class _OtherMethodExt(Extension):
    """A second extension binding the same verb as `_MethodExt`."""

    identifier = "com.example/other-method"

    def methods(self) -> list[MethodBinding]:
        return [MethodBinding("com.example/ping", _PingParams, _pong_handler)]


def test_colliding_extension_methods_are_rejected_at_registration() -> None:
    """SDK-defined: two extensions binding the same method would silently last-write-win;
    the collision is rejected when the second extension is applied."""
    with pytest.raises(ValueError) as exc_info:
        MCPServer("test", extensions=[_MethodExt(), _OtherMethodExt()])
    assert str(exc_info.value) == snapshot(
        "Extension 'com.example/other-method' binds method 'com.example/ping', which is already "
        "registered; extension methods are additive and cannot replace another handler"
    )


_NEEDS_EXT = "com.example/needed"


class _RequiresExt(Extension):
    """A tool that requires the client to have declared `com.example/needed`."""

    identifier = _NEEDS_EXT

    def tools(self):
        def guarded(ctx: Context) -> str:
            require_client_extension(ctx.request_context, _NEEDS_EXT)
            return "ok"

        return [ToolBinding(fn=guarded)]


async def test_require_client_extension_passes_when_client_declared_it() -> None:
    """SDK-defined: `require_client_extension` is a no-op when the client advertised the id."""
    server = MCPServer("test", extensions=[_RequiresExt()])

    async with Client(server, extensions=[advertise(_NEEDS_EXT)]) as client:
        result = await client.call_tool("guarded", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="ok")], structured_content={"result": "ok"}))


async def test_require_client_extension_raises_minus_32021_when_client_did_not_declare_it() -> None:
    """SDK-defined: `require_client_extension` raises the -32021 missing-required-capability
    error when the client did not advertise the id."""
    server = MCPServer("test", extensions=[_RequiresExt()])

    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("guarded", {})

    assert exc_info.value.code == MISSING_REQUIRED_CLIENT_CAPABILITY
    assert exc_info.value.error.data == snapshot({"requiredCapabilities": {"extensions": {_NEEDS_EXT: {}}}})
