"""Tests for the SEP-2133 extension API (`Extension`, `MCPServer` wiring).

Covers tools, resources, request methods, and the `tools/call` interceptor,
exercised through the in-memory `Client` plus `compose_tool_call_interceptor` directly.
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

from mcp.client.client import Client
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.extension import (
    Extension,
    MethodBinding,
    ResourceBinding,
    ToolBinding,
    compose_tool_call_interceptor,
    validate_extension_identifier,
)
from mcp.server.mcpserver import Context, MCPServer, require_client_extension
from mcp.server.mcpserver.resources import TextResource
from mcp.shared.exceptions import MCPError

pytestmark = pytest.mark.anyio

_TOOL_META: dict[str, Any] = {"com.example/marker": {"v": 1}}


class _AdditiveExt(Extension):
    identifier = "com.example/additive"

    def tools(self):
        def ping() -> str:
            """Reply with pong."""
            return "pong"

        return [ToolBinding(fn=ping, meta=_TOOL_META)]

    def resources(self):
        return [ResourceBinding(resource=TextResource(uri="ext://greeting", name="greeting", text="hello"))]


class _SettingsExt(Extension):
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
    return _PingResult(pong=True)


class _MethodExt(Extension):
    identifier = "com.example/method"

    def methods(self) -> list[MethodBinding]:
        return [MethodBinding("com.example/ping", _PingParams, _pong_handler)]


class _ReplacingExt(Extension):
    identifier = "com.example/replacing"

    async def intercept_tool_call(
        self, params: types.CallToolRequestParams, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        return CallToolResult(content=[TextContent(type="text", text="intercepted")])


class _PassThroughExt(Extension):
    identifier = "com.example/passthrough"

    async def intercept_tool_call(
        self, params: types.CallToolRequestParams, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        return await call_next(ctx)


class _DefaultExt(Extension):
    """Overrides nothing - exercises the base `intercept_tool_call` pass-through default."""

    identifier = "com.example/default"


class _RecordingExt(Extension):
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
    server = MCPServer("test", extensions=[_SettingsExt()])

    async with Client(server, mode="auto") as client:
        extensions = client.server_capabilities.extensions

    assert extensions == snapshot({"com.example/settings": {"feature": {"enabled": True}}})


async def test_extension_settings_dropped_on_legacy_handshake() -> None:
    """The 2025 `ServerCapabilities` wire schema has no `extensions` field, so a legacy handshake drops them."""
    server = MCPServer("test", extensions=[_SettingsExt()])

    async with Client(server, mode="legacy") as client:
        assert client.server_capabilities.extensions is None


def test_duplicate_extension_identifier_raises() -> None:
    with pytest.raises(ValueError):
        MCPServer("test", extensions=[_SettingsExt(), _SettingsExt()])


async def test_extension_method_reachable_via_session_send_request() -> None:
    server = MCPServer("test", extensions=[_MethodExt()])

    async with Client(server) as client:
        request = _PingRequest(params=_PingParams())
        result = await client.session.send_request(cast("types.ClientRequest", request), _PingResult)

    assert result == snapshot(_PingResult(pong=True))


async def test_pass_through_interceptor_leaves_tool_result_unchanged() -> None:
    server = MCPServer("test", extensions=[_PassThroughExt()])
    server.tool(name="echo")(_echo)

    async with Client(server) as client:
        result = await client.call_tool("echo", {"value": "hi"})

    assert result == snapshot(CallToolResult(content=[TextContent(text="hi")], structured_content={"result": "hi"}))


async def test_short_circuiting_interceptor_replaces_tool_result() -> None:
    server = MCPServer("test", extensions=[_ReplacingExt()])
    server.tool(name="echo", structured_output=False)(_echo)

    async with Client(server) as client:
        result = await client.call_tool("echo", {"value": "hi"})

    assert result == snapshot(CallToolResult(content=[TextContent(text="intercepted")]))


def test_plain_extension_installs_no_tool_call_interceptor() -> None:
    baseline = len(MCPServer("test")._lowlevel_server.middleware)
    server = MCPServer("test", extensions=[_AdditiveExt()])

    assert len(server._lowlevel_server.middleware) == baseline


def test_overriding_extension_installs_one_tool_call_interceptor() -> None:
    baseline = len(MCPServer("test")._lowlevel_server.middleware)
    server = MCPServer("test", extensions=[_ReplacingExt()])

    assert len(server._lowlevel_server.middleware) == baseline + 1


async def test_default_interceptor_passes_through_alongside_an_overriding_one() -> None:
    server = MCPServer("test", extensions=[_DefaultExt(), _PassThroughExt()])
    server.tool(name="echo")(_echo)

    async with Client(server) as client:
        result = await client.call_tool("echo", {"value": "hi"})

    assert result == snapshot(CallToolResult(content=[TextContent(text="hi")], structured_content={"result": "hi"}))


async def test_interceptors_run_in_registration_order_with_threaded_params() -> None:
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
    with pytest.raises(TypeError):
        type("_BadExt", (Extension,), {"identifier": "noprefix"})


def test_extension_without_identifier_is_rejected_at_registration() -> None:
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
    identifier = "com.example/pinned"

    def methods(self):
        async def handler(ctx: ServerRequestContext[Any, Any], params: _VersionPinnedParams) -> _VersionPinnedResult:
            return _VersionPinnedResult(ok=True)

        return [MethodBinding("com.example/pinned", _VersionPinnedParams, handler, frozenset({"2026-07-28"}))]


async def test_version_pinned_method_is_served_at_an_allowed_version() -> None:
    server = MCPServer("test", extensions=[_VersionPinnedExt()])

    async with Client(server, mode="2026-07-28") as client:
        request = _VersionPinnedRequest(params=_VersionPinnedParams())
        result = await client.session.send_request(cast("types.ClientRequest", request), _VersionPinnedResult)

    assert result == snapshot(_VersionPinnedResult(ok=True))


async def test_version_pinned_method_is_method_not_found_at_a_disallowed_version() -> None:
    server = MCPServer("test", extensions=[_VersionPinnedExt()])

    async with Client(server, mode="legacy") as client:
        request = _VersionPinnedRequest(params=_VersionPinnedParams())
        with pytest.raises(MCPError) as exc_info:
            await client.session.send_request(cast("types.ClientRequest", request), _VersionPinnedResult)

    assert exc_info.value.code == METHOD_NOT_FOUND
    assert exc_info.value.error.data == "com.example/pinned"


@pytest.mark.parametrize(
    "identifier",
    [
        "io.modelcontextprotocol/ui",
        "com.example/my_ext",
        "com.x-y.z2/n.a-b_c",
        "example/x",
        "a/b",
        "com.example/9start",
    ],
)
def test_grammar_conformant_extension_identifiers_are_accepted(identifier: str) -> None:
    """Spec `_meta` key grammar: dot-separated labels (letter start, letter/digit end,
    hyphens interior), a slash, then a name that starts and ends alphanumeric."""
    validate_extension_identifier(identifier, owner="T")


@pytest.mark.parametrize(
    "identifier",
    [
        "noprefix",
        "-foo/bar",
        ".leading/x",
        "a..b/x",
        "foo-/x",
        "9foo/x",
        "foo/-bar",
        "foo/bar-",
        "foo/",
        "/bar",
        "foo/ba r",
        "io.modelcontextprotocol/ui\n",
        "",
        None,
        42,
    ],
)
def test_malformed_extension_identifiers_are_rejected(identifier: Any) -> None:
    with pytest.raises(TypeError):
        validate_extension_identifier(identifier, owner="T")


@pytest.mark.parametrize("method", ["tools/list", "completion/complete"])
def test_method_binding_rejects_spec_methods(method: str) -> None:
    """Binding a spec-defined request method would silently shadow the server's own handler."""
    with pytest.raises(ValueError):
        MethodBinding(method, _PingParams, _pong_handler)


def test_method_binding_rejects_empty_protocol_versions() -> None:
    with pytest.raises(ValueError) as exc_info:
        MethodBinding("com.example/dead", _PingParams, _pong_handler, frozenset())
    assert str(exc_info.value) == snapshot(
        "MethodBinding for 'com.example/dead' has an empty protocol_versions set, so it could "
        "never be served; use None to admit every version"
    )


class _OtherMethodExt(Extension):
    identifier = "com.example/other-method"

    def methods(self) -> list[MethodBinding]:
        return [MethodBinding("com.example/ping", _PingParams, _pong_handler)]


def test_colliding_extension_methods_are_rejected_at_registration() -> None:
    with pytest.raises(ValueError) as exc_info:
        MCPServer("test", extensions=[_MethodExt(), _OtherMethodExt()])
    assert str(exc_info.value) == snapshot(
        "Extension 'com.example/other-method' binds method 'com.example/ping', which is already "
        "registered; extension methods are additive and cannot replace another handler"
    )


_NEEDS_EXT = "com.example/needed"


class _RequiresExt(Extension):
    identifier = _NEEDS_EXT

    def tools(self):
        def guarded(ctx: Context) -> str:
            require_client_extension(ctx.request_context, _NEEDS_EXT)
            return "ok"

        return [ToolBinding(fn=guarded)]


async def test_require_client_extension_passes_when_client_declared_it() -> None:
    server = MCPServer("test", extensions=[_RequiresExt()])

    async with Client(server, extensions={_NEEDS_EXT: {}}) as client:
        result = await client.call_tool("guarded", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="ok")], structured_content={"result": "ok"}))


async def test_require_client_extension_raises_minus_32021_when_client_did_not_declare_it() -> None:
    server = MCPServer("test", extensions=[_RequiresExt()])

    async with Client(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("guarded", {})

    assert exc_info.value.code == MISSING_REQUIRED_CLIENT_CAPABILITY
    assert exc_info.value.error.data == snapshot({"requiredCapabilities": {"extensions": {_NEEDS_EXT: {}}}})
