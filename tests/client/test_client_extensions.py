"""`Client` + `ClientExtension` integration: folding extension declarations into the
session at construction, and `call_tool` driving claim resolvers transparently.

Claimed-shape servers here are real `MCPServer`s whose SEP-2133 server extension
rewrites `tools/call` results via `intercept_tool_call` — the full public-API loop.
The in-process server can only deliver claimed fields the v2026 tools/call surface
keeps (`resultType`, `requestState`, `inputRequests`, `_meta`): the server-side
`serialize_server_result` drops anything else, so claimed payloads here ride
`requestState`.

`tools/call` is never cached (`Client.call_tool` has no `_cached_fetch` weave and the
SEP-2549 cacheable verbs do not include it), so the claim path needs no cache tests.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

import anyio
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import CallToolResult, Result, TextContent
from mcp_types.version import LATEST_MODERN_VERSION
from pydantic import BaseModel
from typing_extensions import assert_type

from mcp.client import ClaimContext, ClientExtension, NotificationBinding, ResultClaim, advertise
from mcp.client.client import Client
from mcp.client.session import ClientRequestContext, _CallToolResultAdapter
from mcp.server import Server, ServerRequestContext
from mcp.server.context import CallNext, HandlerResult
from mcp.server.extension import Extension
from mcp.server.mcpserver import Context, MCPServer

pytestmark = pytest.mark.anyio

_VOUCHER_EXT = "com.example/voucher"
_RIVAL_EXT = "com.example/rival"

_NAME_SCHEMA = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}


def _name_elicitation() -> types.ElicitRequest:
    return types.ElicitRequest(
        params=types.ElicitRequestFormParams(message="What is your name?", requested_schema=_NAME_SCHEMA)
    )


class VoucherResult(Result):
    """The claimed `tools/call` shape, tagged `voucher`; its payload rides `requestState`
    (the only open payload-bearing field the in-process server's surface dump keeps)."""

    result_type: Literal["voucher"] = "voucher"
    request_state: str | None = None


_Resolver = Callable[[VoucherResult, ClaimContext], Awaitable[CallToolResult]]


class _VoucherExtension(ClientExtension):
    """Client half: claims the `voucher` tag with the supplied resolver."""

    identifier = _VOUCHER_EXT

    def __init__(self, resolve: _Resolver) -> None:
        self._resolve = resolve

    def claims(self) -> Sequence[ResultClaim[Any]]:
        return [ResultClaim(result_type="voucher", model=VoucherResult, resolve=self._resolve)]


class _VoucherIssuer(Extension):
    """Server half: rewrites every `tools/call` result into the vendor-claimed shape."""

    identifier = _VOUCHER_EXT

    async def intercept_tool_call(
        self, params: types.CallToolRequestParams, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        return {"resultType": "voucher", "requestState": "v-42"}


class _TwoRoundVoucherIssuer(Extension):
    """Server half: demands input on the first round, then issues the claimed shape."""

    identifier = _VOUCHER_EXT

    async def intercept_tool_call(
        self, params: types.CallToolRequestParams, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        if params.input_responses is None:
            return types.InputRequiredResult(input_requests={"user_name": _name_elicitation()})
        return {"resultType": "voucher", "requestState": "after-input"}


def _voucher_server(issuer: Extension | None = None) -> MCPServer:
    """An `MCPServer` whose `issue` tool the server extension rewrites into the claimed shape."""
    server = MCPServer("vouchers", extensions=[issuer if issuer is not None else _VoucherIssuer()])

    @server.tool()
    def issue() -> CallToolResult:
        """Issue a voucher."""
        raise NotImplementedError  # the server extension short-circuits before the tool runs

    return server


def _structured_voucher_server() -> MCPServer:
    """Like `_voucher_server`, but `issue` declares an output schema (`-> str`)."""
    server = MCPServer("vouchers", extensions=[_VoucherIssuer()])

    @server.tool()
    def issue() -> str:
        """Issue a voucher."""
        raise NotImplementedError  # the server extension short-circuits before the tool runs

    return server


def _add_server() -> MCPServer:
    """A plain claim-less server with one ordinary tool."""
    server = MCPServer("plain")

    @server.tool()
    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    return server


# ── Construction-time validation ────────────────────────────────────────────


def test_bare_extension_instance_is_rejected_with_the_fix_named() -> None:
    """SDK-defined: an instance whose class never set `identifier` fails Client
    construction with an error naming the type and the fix — not an AttributeError."""
    with pytest.raises(ValueError) as exc_info:
        Client(_add_server(), extensions=[ClientExtension()])

    assert str(exc_info.value) == snapshot(
        "ClientExtension has no `identifier`; a ClientExtension must set the `identifier` "
        "class attribute (or assign one in `__init__`) before it can be used"
    )


class _SelfAssignedBadId(ClientExtension):
    """Assigns a malformed identifier in `__init__` — invisible at class definition."""

    def __init__(self) -> None:
        self.identifier = "not-prefixed"


def test_invalid_per_instance_identifier_raises_the_validators_error() -> None:
    """SDK-defined: per-instance identifiers are validated when the Client consumes the
    extension (no class attribute existed at definition time, mirroring the server's
    posture); the shared validator's TypeError surfaces unwrapped."""
    with pytest.raises(TypeError) as exc_info:
        Client(_add_server(), extensions=[_SelfAssignedBadId()])

    assert str(exc_info.value) == snapshot(
        "_SelfAssignedBadId.identifier must be a `vendor-prefix/name` string "
        "(reverse-DNS prefix required), got 'not-prefixed'"
    )


def test_duplicate_extension_identifiers_are_rejected_naming_the_identifier() -> None:
    """SDK-defined: one identifier cannot appear twice — there would be two settings
    dicts for one capability-ad key."""
    with pytest.raises(ValueError) as exc_info:
        Client(_add_server(), extensions=[advertise(_VOUCHER_EXT), advertise(_VOUCHER_EXT, {"a": 1})])

    assert str(exc_info.value) == snapshot("extension identifier 'com.example/voucher' is passed more than once")


async def _unreachable_resolve(claimed: VoucherResult, ctx: ClaimContext) -> CallToolResult:
    raise NotImplementedError  # construction-only extensions never resolve


class _RivalVoucherExtension(ClientExtension):
    """A second extension claiming the same `voucher` tag (construction-conflict tests)."""

    identifier = _RIVAL_EXT

    def claims(self) -> Sequence[ResultClaim[Any]]:
        return [ResultClaim(result_type="voucher", model=VoucherResult, resolve=_unreachable_resolve)]


def test_conflicting_claims_across_extensions_name_both_owners() -> None:
    """SDK-defined: two extensions claiming the same (method, resultType) fail at
    Client construction with both owning extensions named — the session's own
    duplicate check knows only the method and tag, which cannot tell a user which
    two of their extensions collide."""
    with pytest.raises(ValueError) as exc_info:
        Client(_add_server(), extensions=[_VoucherExtension(_unreachable_resolve), _RivalVoucherExtension()])

    assert str(exc_info.value) == snapshot(
        "extensions 'com.example/voucher' and 'com.example/rival' both claim 'tools/call' "
        "resultType 'voucher'; a wire tag can have only one resolver"
    )


class _EventParams(BaseModel):
    seq: int


async def _unreachable_handler(params: _EventParams) -> None:
    raise NotImplementedError  # construction-only extensions never deliver


class _ObserverA(ClientExtension):
    identifier = "com.example/observer-a"

    def notifications(self) -> Sequence[NotificationBinding[Any]]:
        return [
            NotificationBinding(
                method="notifications/vendor/event", params_type=_EventParams, handler=_unreachable_handler
            )
        ]


class _ObserverB(ClientExtension):
    identifier = "com.example/observer-b"

    def notifications(self) -> Sequence[NotificationBinding[Any]]:
        return [
            NotificationBinding(
                method="notifications/vendor/event", params_type=_EventParams, handler=_unreachable_handler
            )
        ]


def test_conflicting_notification_bindings_name_both_owners() -> None:
    """SDK-defined: two extensions binding the same notification method fail at Client
    construction with both owning extensions named, for the same reason as claims."""
    with pytest.raises(ValueError) as exc_info:
        Client(_add_server(), extensions=[_ObserverA(), _ObserverB()])

    assert str(exc_info.value) == snapshot(
        "extensions 'com.example/observer-a' and 'com.example/observer-b' both bind "
        "notification method 'notifications/vendor/event'; a method can have only one observer"
    )


# ── settings() consumption ───────────────────────────────────────────────────


class _CountingSettings(ClientExtension):
    """Counts `settings()` reads to pin the read-once contract."""

    identifier = "com.example/counted"

    def __init__(self) -> None:
        self.reads = 0

    def settings(self) -> dict[str, Any]:
        self.reads += 1
        return {"read": self.reads}


async def test_settings_is_read_exactly_once_at_construction() -> None:
    """SDK-defined: `settings()` is read once, at Client construction — connecting and
    calling tools (each modern request re-stamps the capability ad) never re-reads it."""
    extension = _CountingSettings()
    client = Client(_add_server(), extensions=[extension])
    assert extension.reads == 1

    with anyio.fail_after(5):
        async with client:
            await client.call_tool("add", {"a": 1, "b": 2})
            await client.call_tool("add", {"a": 3, "b": 4})

    assert extension.reads == 1


async def test_settings_dict_is_held_by_reference_not_copied() -> None:
    """SDK-defined: the dict `settings()` returns is held by reference, not copied —
    mutating it between construction and connect changes the advertised ad (the same
    aliasing the dict-form `extensions=` argument had)."""
    observed: list[dict[str, dict[str, Any]] | None] = []

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "probe"
        assert ctx.session.client_params is not None
        observed.append(ctx.session.client_params.capabilities.extensions)
        return CallToolResult(content=[])

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="probe", input_schema={"type": "object"})])

    server = Server("probe", on_call_tool=call_tool, on_list_tools=list_tools)
    settings = {"tier": "bronze"}
    client = Client(server, extensions=[advertise("com.example/loyalty", settings)])
    settings["tier"] = "gold"

    with anyio.fail_after(5):
        async with client:
            await client.call_tool("probe", {})

    assert observed == [{"com.example/loyalty": {"tier": "gold"}}]


# ── extensions=None stays byte-identical ─────────────────────────────────────


@pytest.mark.parametrize("extensions", [None, ()], ids=["none", "empty"])
async def test_no_extensions_keeps_tools_call_parsing_byte_identical(
    extensions: Sequence[ClientExtension] | None,
) -> None:
    """SDK-defined: `extensions=None` (and an empty sequence) leave the session exactly
    as a claim-less client's — the tools/call adapter is the module-level constant by
    identity, and an ordinary call behaves as before."""
    with anyio.fail_after(5):
        async with Client(_add_server(), extensions=extensions) as client:
            assert client.session._call_tool_adapter is _CallToolResultAdapter
            result = await client.call_tool("add", {"a": 1, "b": 2})

    assert result.structured_content == {"result": 3}


# ── The transparent claim path ───────────────────────────────────────────────


async def test_claimed_result_resolves_transparently_to_the_resolvers_result() -> None:
    """A server-claimed `tools/call` shape never surfaces: the owning claim's resolver
    receives the parsed claim model and `Client.call_tool` returns the resolver's
    `CallToolResult` object — the signature stays `-> CallToolResult` (the assert_type
    below is checked by pyright)."""
    received: list[VoucherResult] = []
    produced: list[CallToolResult] = []

    async def resolve(claimed: VoucherResult, ctx: ClaimContext) -> CallToolResult:
        received.append(claimed)
        product = CallToolResult(content=[TextContent(text=f"honored {claimed.request_state}")])
        produced.append(product)
        return product

    with anyio.fail_after(5):
        async with Client(_voucher_server(), extensions=[_VoucherExtension(resolve)]) as client:
            result = await client.call_tool("issue", {})
            assert_type(result, CallToolResult)

    assert [claimed.request_state for claimed in received] == ["v-42"]
    assert result is produced[0]
    assert result.content == [TextContent(text="honored v-42")]


async def test_resolver_product_gets_the_direct_paths_output_schema_revalidation() -> None:
    """The resolver's product passes through `validate_tool_result` exactly like a
    directly-returned result: against the tool's output schema, missing structured
    content raises the direct path's RuntimeError (the message below is the same
    one `ClientSession.call_tool`'s own guard produces)."""

    async def resolve(claimed: VoucherResult, ctx: ClaimContext) -> CallToolResult:
        return CallToolResult(content=[TextContent(text="unstructured")])

    async with Client(_structured_voucher_server(), extensions=[_VoucherExtension(resolve)]) as client:
        with anyio.fail_after(5), pytest.raises(RuntimeError) as exc_info:
            await client.call_tool("issue", {})

    assert str(exc_info.value) == snapshot("Tool issue has an output schema but did not return structured content")


async def test_resolver_error_result_is_returned_not_raised() -> None:
    """An `isError` resolver product skips output-schema revalidation and comes back
    as-is — the same strictness as the direct path, which only revalidates successes.
    The tool here declares an output schema, so revalidating would have raised."""

    async def resolve(claimed: VoucherResult, ctx: ClaimContext) -> CallToolResult:
        return CallToolResult(content=[TextContent(text="voucher printer on fire")], is_error=True)

    with anyio.fail_after(5):
        async with Client(_structured_voucher_server(), extensions=[_VoucherExtension(resolve)]) as client:
            result = await client.call_tool("issue", {})

    assert result.is_error
    assert result.content == [TextContent(text="voucher printer on fire")]


async def test_resolver_receives_the_calls_claim_context() -> None:
    """`ClaimContext` hands the resolver the client's own session object, the tool
    name, and the per-call read timeout `call_tool` was given."""
    contexts: list[ClaimContext] = []

    async def resolve(claimed: VoucherResult, ctx: ClaimContext) -> CallToolResult:
        contexts.append(ctx)
        return CallToolResult(content=[])

    with anyio.fail_after(5):
        async with Client(_voucher_server(), extensions=[_VoucherExtension(resolve)]) as client:
            await client.call_tool("issue", {}, read_timeout_seconds=7.0)
            [ctx] = contexts
            assert ctx.session is client.session

    assert ctx.tool_name == "issue"
    assert ctx.read_timeout_seconds == 7.0


class _VoucherRefused(Exception):
    """Extension-owned error vocabulary."""


async def test_resolver_exception_propagates_untouched() -> None:
    """A resolver exception reaches the `call_tool` caller as the very object the
    resolver raised — no wrapping, the extension owns its error vocabulary."""
    refusal = _VoucherRefused("the voucher is refused")

    async def resolve(claimed: VoucherResult, ctx: ClaimContext) -> CallToolResult:
        raise refusal

    async with Client(_voucher_server(), extensions=[_VoucherExtension(resolve)]) as client:
        with anyio.fail_after(5), pytest.raises(_VoucherRefused) as exc_info:
            await client.call_tool("issue", {})

    assert exc_info.value is refusal


# ── Unclaimed results with extensions present ────────────────────────────────


async def test_unclaimed_result_flows_through_unchanged_with_extensions_present() -> None:
    """An ordinary `CallToolResult` is untouched by the claim machinery — the resolver
    never runs and the result matches a claim-less client's."""

    async def resolve(claimed: VoucherResult, ctx: ClaimContext) -> CallToolResult:
        raise NotImplementedError  # this server never produces a claimed shape

    with anyio.fail_after(5):
        async with Client(_add_server(), extensions=[_VoucherExtension(resolve)]) as client:
            result = await client.call_tool("add", {"a": 1, "b": 2})

    assert result.structured_content == {"result": 3}


async def test_input_required_then_plain_result_keeps_the_auto_loop_working() -> None:
    """With a claim-bearing extension present, the auto loop on an unclaimed tool is
    unchanged: input_required resolves via the elicitation callback and the plain
    terminal result comes back; the resolver never runs."""
    server = MCPServer("mrtr")

    @server.tool()
    async def greet(ctx: Context) -> str | types.InputRequiredResult:
        responses = ctx.input_responses
        if responses and "user_name" in responses:
            answer = responses["user_name"]
            assert isinstance(answer, types.ElicitResult)
            assert answer.content is not None
            return f"Hello, {answer.content['name']}!"
        return types.InputRequiredResult(input_requests={"user_name": _name_elicitation()})

    async def elicitation_callback(
        context: ClientRequestContext, params: types.ElicitRequestParams
    ) -> types.ElicitResult | types.ErrorData:
        return types.ElicitResult(action="accept", content={"name": "Ada"})

    async def resolve(claimed: VoucherResult, ctx: ClaimContext) -> CallToolResult:
        raise NotImplementedError  # this server never produces a claimed shape

    with anyio.fail_after(5):
        async with Client(
            server, elicitation_callback=elicitation_callback, extensions=[_VoucherExtension(resolve)]
        ) as client:
            result = await client.call_tool("greet")

    assert result.content == [TextContent(text="Hello, Ada!")]


# ── The multi-round-trip + claimed interplay ─────────────────────────────────


async def test_input_required_then_claimed_result_on_retry_resolves_transparently() -> None:
    """The retry-leg regression: a call that demands input first and returns a claimed
    shape on the retry still resolves transparently. The driver's retry must admit
    claimed shapes — multi-round-trip input resolves before a claimed result, so a
    claim may terminate any round, not just the first."""
    prompted: list[str] = []
    received: list[VoucherResult] = []

    async def elicitation_callback(
        context: ClientRequestContext, params: types.ElicitRequestParams
    ) -> types.ElicitResult | types.ErrorData:
        assert isinstance(params, types.ElicitRequestFormParams)
        prompted.append(params.message)
        return types.ElicitResult(action="accept", content={"name": "Ada"})

    async def resolve(claimed: VoucherResult, ctx: ClaimContext) -> CallToolResult:
        received.append(claimed)
        return CallToolResult(content=[TextContent(text=f"honored {claimed.request_state}")])

    server = _voucher_server(issuer=_TwoRoundVoucherIssuer())
    with anyio.fail_after(5):
        async with Client(
            server, elicitation_callback=elicitation_callback, extensions=[_VoucherExtension(resolve)]
        ) as client:
            result = await client.call_tool("issue", {})

    assert prompted == ["What is your name?"]
    assert [claimed.request_state for claimed in received] == ["after-input"]
    assert result.content == [TextContent(text="honored after-input")]


# ── Notification bindings fold into the session ──────────────────────────────


class _CoreMethodObserver(ClientExtension):
    """Binds a method the modern core tables already define (construction-legal; the
    session warns once at adopt that it can never fire)."""

    identifier = "com.example/observer"

    def notifications(self) -> Sequence[NotificationBinding[Any]]:
        return [
            NotificationBinding(method="notifications/message", params_type=_EventParams, handler=_unreachable_handler)
        ]


async def test_notification_bindings_fold_into_the_session(caplog: pytest.LogCaptureFixture) -> None:
    """The Client threads extension notification bindings into its session: a binding
    for a core-known method draws the session's one-time gone-quiet warning at adopt.
    (Delivery mechanics are session-tier covered in
    test_session_notification_bindings.py; this pins the Client fold seam.)"""
    with caplog.at_level(logging.WARNING, logger="client"):
        async with Client(_add_server(), extensions=[_CoreMethodObserver()]):
            pass

    expected = f"notification binding for 'notifications/message' will never fire at {LATEST_MODERN_VERSION}"
    assert caplog.text.count(expected) == 1
