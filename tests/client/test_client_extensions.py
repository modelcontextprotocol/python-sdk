"""`Client` + `ClientExtension` integration: extension declarations fold into the session at
construction, and `call_tool` drives claim resolvers transparently against real `MCPServer`s.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal, cast

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
    """The claimed `tools/call` shape, tagged `voucher`, carrying a vendor top-level field."""

    result_type: Literal["voucher"] = "voucher"
    voucher_code: str | None = None


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
        return {"resultType": "voucher", "voucherCode": "v-42"}


class _TwoRoundVoucherIssuer(Extension):
    """Server half: demands input on the first round, then issues the claimed shape."""

    identifier = _VOUCHER_EXT

    async def intercept_tool_call(
        self, params: types.CallToolRequestParams, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        if params.input_responses is None:
            return types.InputRequiredResult(input_requests={"user_name": _name_elicitation()})
        return {"resultType": "voucher", "voucherCode": "after-input"}


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


# Construction-time validation


class _CouponResult(Result):
    result_type: Literal["coupon"] = "coupon"


async def _unreachable_coupon_resolve(claimed: _CouponResult, ctx: ClaimContext) -> CallToolResult:
    raise NotImplementedError  # the wrong resolver for a voucher; must never run


class _CouponExtension(ClientExtension):
    identifier = "com.example/coupons"

    def claims(self) -> Sequence[ResultClaim[Any]]:
        return [ResultClaim(result_type="coupon", model=_CouponResult, resolve=_unreachable_coupon_resolve)]


class _SelfConflictingClaims(ClientExtension):
    identifier = "com.example/twice"

    def claims(self) -> Sequence[ResultClaim[Any]]:
        return [
            ResultClaim(result_type="twice", model=_TwiceResult, resolve=_unreachable_twice_resolve),
            ResultClaim(result_type="twice", model=_TwiceResult, resolve=_unreachable_twice_resolve),
        ]


class _TwiceResult(Result):
    result_type: Literal["twice"] = "twice"


async def _unreachable_twice_resolve(claimed: _TwiceResult, ctx: ClaimContext) -> CallToolResult:
    raise NotImplementedError


def test_mapping_extensions_get_the_migration_error() -> None:
    """SDK-defined: the replaced dict form fails with a message naming the new shape."""
    with pytest.raises(TypeError) as exc_info:
        Client(_add_server(), extensions=cast("Sequence[ClientExtension]", {"com.example/ui": {}}))

    assert str(exc_info.value) == snapshot(
        "extensions= takes a sequence of ClientExtension instances. The mapping form was "
        "replaced: use advertise(identifier, settings) for advertise-only entries"
    )


def test_one_extension_claiming_a_tag_twice_reads_as_one_owner() -> None:
    """SDK-defined: a self-conflict names the one extension once, not as a pair."""
    with pytest.raises(ValueError) as exc_info:
        Client(_add_server(), extensions=[_SelfConflictingClaims()])

    assert str(exc_info.value) == snapshot(
        "extension 'com.example/twice' claims resultType 'twice'; a wire tag can have only one resolver"
    )


def test_bare_extension_instance_is_rejected_with_the_fix_named() -> None:
    """SDK-defined: an instance whose class never set `identifier` fails construction naming the type and the fix."""
    with pytest.raises(ValueError) as exc_info:
        Client(_add_server(), extensions=[ClientExtension()])

    assert str(exc_info.value) == snapshot(
        "ClientExtension has no `identifier`; a ClientExtension must set the `identifier` "
        "class attribute (or assign one in `__init__`) before it can be used"
    )


class _SelfAssignedBadId(ClientExtension):
    """Assigns a malformed identifier in `__init__`, invisible at class definition."""

    def __init__(self) -> None:
        self.identifier = "not-prefixed"


def test_invalid_per_instance_identifier_raises_the_validators_error() -> None:
    """SDK-defined: per-instance identifiers are validated when the Client consumes the extension."""
    with pytest.raises(TypeError) as exc_info:
        Client(_add_server(), extensions=[_SelfAssignedBadId()])

    assert str(exc_info.value) == snapshot(
        "_SelfAssignedBadId.identifier must be a `vendor-prefix/name` string "
        "(reverse-DNS prefix required), got 'not-prefixed'"
    )


def test_duplicate_extension_identifiers_are_rejected_naming_the_identifier() -> None:
    """SDK-defined: one identifier cannot appear twice across the extensions sequence."""
    with pytest.raises(ValueError) as exc_info:
        Client(_add_server(), extensions=[advertise(_VOUCHER_EXT), advertise(_VOUCHER_EXT, {"a": 1})])

    assert str(exc_info.value) == snapshot("extension identifier 'com.example/voucher' is passed more than once")


async def _unreachable_resolve(claimed: VoucherResult, ctx: ClaimContext) -> CallToolResult:
    raise NotImplementedError


class _RivalVoucherExtension(ClientExtension):
    identifier = _RIVAL_EXT

    def claims(self) -> Sequence[ResultClaim[Any]]:
        return [ResultClaim(result_type="voucher", model=VoucherResult, resolve=_unreachable_resolve)]


def test_conflicting_claims_across_extensions_name_both_owners() -> None:
    """SDK-defined: two extensions claiming the same tag fail at construction with both owners named."""
    with pytest.raises(ValueError) as exc_info:
        Client(_add_server(), extensions=[_VoucherExtension(_unreachable_resolve), _RivalVoucherExtension()])

    assert str(exc_info.value) == snapshot(
        "extensions 'com.example/voucher' and 'com.example/rival' both claim resultType "
        "'voucher'; a wire tag can have only one resolver"
    )


class _EventParams(BaseModel):
    seq: int


async def _unreachable_handler(params: _EventParams) -> None:
    raise NotImplementedError


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
    """SDK-defined: two extensions binding the same notification method fail with both owners named."""
    with pytest.raises(ValueError) as exc_info:
        Client(_add_server(), extensions=[_ObserverA(), _ObserverB()])

    assert str(exc_info.value) == snapshot(
        "extensions 'com.example/observer-a' and 'com.example/observer-b' both bind "
        "notification method 'notifications/vendor/event'; a method can have only one observer"
    )


# settings() consumption


class _CountedResult(Result):
    result_type: Literal["counted"] = "counted"


async def _unreachable_counted_resolve(claimed: _CountedResult, ctx: ClaimContext) -> CallToolResult:
    raise NotImplementedError


class _CountingSettings(ClientExtension):
    identifier = "com.example/counted"

    def __init__(self) -> None:
        self.reads = 0
        self.claims_reads = 0
        self.notifications_reads = 0

    def settings(self) -> dict[str, Any]:
        self.reads += 1
        return {"read": self.reads}

    def claims(self) -> Sequence[ResultClaim[Any]]:
        self.claims_reads += 1
        return [ResultClaim(result_type="counted", model=_CountedResult, resolve=_unreachable_counted_resolve)]

    def notifications(self) -> Sequence[NotificationBinding[Any]]:
        self.notifications_reads += 1
        return [
            NotificationBinding(method="notifications/counted", params_type=_EventParams, handler=_unreachable_handler)
        ]


async def test_declarations_are_read_exactly_once_at_construction() -> None:
    """SDK-defined: each declaration method is read exactly once, at Client construction, never again."""
    extension = _CountingSettings()
    client = Client(_add_server(), extensions=[extension])
    assert (extension.reads, extension.claims_reads, extension.notifications_reads) == (1, 1, 1)

    with anyio.fail_after(5):
        async with client:
            await client.call_tool("add", {"a": 1, "b": 2})
            await client.call_tool("add", {"a": 3, "b": 4})

    assert (extension.reads, extension.claims_reads, extension.notifications_reads) == (1, 1, 1)


async def test_settings_dict_is_held_by_reference_not_copied() -> None:
    """SDK-defined: the settings dict is held by reference, so mutating it before connect changes the ad."""
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


# extensions=None stays byte-identical


@pytest.mark.parametrize("extensions", [None, ()], ids=["none", "empty"])
async def test_no_extensions_keeps_tools_call_parsing_byte_identical(
    extensions: Sequence[ClientExtension] | None,
) -> None:
    """SDK-defined: `extensions=None` and an empty sequence leave the session exactly as a claim-less client's."""
    with anyio.fail_after(5):
        async with Client(_add_server(), extensions=extensions) as client:
            assert client.session._call_tool_adapter is _CallToolResultAdapter
            result = await client.call_tool("add", {"a": 1, "b": 2})

    assert result.structured_content == {"result": 3}


# The transparent claim path


async def test_claimed_result_resolves_transparently_to_the_resolvers_result() -> None:
    """A claimed shape never surfaces: the resolver gets the parsed model and `call_tool` returns its product."""
    received: list[VoucherResult] = []
    produced: list[CallToolResult] = []

    async def resolve(claimed: VoucherResult, ctx: ClaimContext) -> CallToolResult:
        received.append(claimed)
        product = CallToolResult(content=[TextContent(text=f"honored {claimed.voucher_code}")])
        produced.append(product)
        return product

    with anyio.fail_after(5):
        async with Client(_voucher_server(), extensions=[_VoucherExtension(resolve)]) as client:
            result = await client.call_tool("issue", {})
            assert_type(result, CallToolResult)

    assert [claimed.voucher_code for claimed in received] == ["v-42"]
    assert result is produced[0]
    assert result.content == [TextContent(text="honored v-42")]


async def test_claimed_shape_routes_to_its_owning_extensions_resolver() -> None:
    """With two claim-bearing extensions registered, the parsed shape runs its owner's resolver only."""
    received: list[VoucherResult] = []

    async def resolve(claimed: VoucherResult, ctx: ClaimContext) -> CallToolResult:
        received.append(claimed)
        return CallToolResult(content=[TextContent(text="routed")])

    extensions = [_CouponExtension(), _VoucherExtension(resolve)]
    with anyio.fail_after(5):
        async with Client(_voucher_server(), extensions=extensions) as client:
            result = await client.call_tool("issue", {})

    assert [claimed.voucher_code for claimed in received] == ["v-42"]
    assert result.content == [TextContent(text="routed")]


async def test_resolver_product_gets_the_direct_paths_output_schema_revalidation() -> None:
    """The resolver's product is revalidated against the tool's output schema exactly like a direct result."""

    async def resolve(claimed: VoucherResult, ctx: ClaimContext) -> CallToolResult:
        return CallToolResult(content=[TextContent(text="unstructured")])

    async with Client(_structured_voucher_server(), extensions=[_VoucherExtension(resolve)]) as client:
        with anyio.fail_after(5), pytest.raises(RuntimeError) as exc_info:
            await client.call_tool("issue", {})

    assert str(exc_info.value) == snapshot("Tool issue has an output schema but did not return structured content")


async def test_resolver_error_result_is_returned_not_raised() -> None:
    """An `isError` resolver product skips output-schema revalidation and comes back as-is."""

    async def resolve(claimed: VoucherResult, ctx: ClaimContext) -> CallToolResult:
        return CallToolResult(content=[TextContent(text="voucher printer on fire")], is_error=True)

    with anyio.fail_after(5):
        async with Client(_structured_voucher_server(), extensions=[_VoucherExtension(resolve)]) as client:
            result = await client.call_tool("issue", {})

    assert result.is_error
    assert result.content == [TextContent(text="voucher printer on fire")]


async def test_resolver_receives_the_calls_claim_context() -> None:
    """`ClaimContext` carries the client's own session object, the tool name, and the per-call read timeout."""
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
    """A resolver exception reaches the `call_tool` caller as the very object raised, unwrapped."""
    refusal = _VoucherRefused("the voucher is refused")

    async def resolve(claimed: VoucherResult, ctx: ClaimContext) -> CallToolResult:
        raise refusal

    async with Client(_voucher_server(), extensions=[_VoucherExtension(resolve)]) as client:
        with anyio.fail_after(5), pytest.raises(_VoucherRefused) as exc_info:
            await client.call_tool("issue", {})

    assert exc_info.value is refusal


# Unclaimed results with extensions present


async def test_unclaimed_result_flows_through_unchanged_with_extensions_present() -> None:
    """An ordinary `CallToolResult` is untouched by the claim machinery; the resolver never runs."""

    async def resolve(claimed: VoucherResult, ctx: ClaimContext) -> CallToolResult:
        raise NotImplementedError  # this server never produces a claimed shape

    with anyio.fail_after(5):
        async with Client(_add_server(), extensions=[_VoucherExtension(resolve)]) as client:
            result = await client.call_tool("add", {"a": 1, "b": 2})

    assert result.structured_content == {"result": 3}


async def test_input_required_then_plain_result_keeps_the_auto_loop_working() -> None:
    """With a claim-bearing extension present, the input_required auto loop on an unclaimed tool is unchanged."""
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


# The multi-round-trip + claimed interplay


async def test_input_required_then_claimed_result_on_retry_resolves_transparently() -> None:
    """A call that demands input first and returns a claimed shape on the retry still resolves transparently."""
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
        return CallToolResult(content=[TextContent(text=f"honored {claimed.voucher_code}")])

    server = _voucher_server(issuer=_TwoRoundVoucherIssuer())
    with anyio.fail_after(5):
        async with Client(
            server, elicitation_callback=elicitation_callback, extensions=[_VoucherExtension(resolve)]
        ) as client:
            result = await client.call_tool("issue", {})

    assert prompted == ["What is your name?"]
    assert [claimed.voucher_code for claimed in received] == ["after-input"]
    assert result.content == [TextContent(text="honored after-input")]


# Notification bindings fold into the session


class _CoreMethodObserver(ClientExtension):
    """Binds a method the modern core tables already define."""

    identifier = "com.example/observer"

    def notifications(self) -> Sequence[NotificationBinding[Any]]:
        return [
            NotificationBinding(method="notifications/message", params_type=_EventParams, handler=_unreachable_handler)
        ]


async def test_notification_bindings_fold_into_the_session(caplog: pytest.LogCaptureFixture) -> None:
    """The Client threads extension bindings into its session; a core-known binding draws the one-time warning."""
    with caplog.at_level(logging.WARNING, logger="client"):
        async with Client(_add_server(), extensions=[_CoreMethodObserver()]):
            pass

    expected = f"notification binding for 'notifications/message' will never fire at {LATEST_MODERN_VERSION}"
    assert caplog.text.count(expected) == 1
