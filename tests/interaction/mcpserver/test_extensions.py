"""Client extensions (SEP-2133) over the full client-server loop.

The servers here are MCPServers whose server extension substitutes a claimed `tools/call`
shape via `intercept_tool_call`; the client declares the owning `ClientExtension` and its
claim resolver finishes the call. The in-process server's 2026 result surface keeps only
`resultType` / `requestState` / `inputRequests` / `_meta` on a claimed result, so claimed
payloads here ride `requestState`.
"""

import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Literal

import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import MISSING_REQUIRED_CLIENT_CAPABILITY, CallToolResult, Result, TextContent
from pydantic import ValidationError

from mcp import MCPError
from mcp.client import ClaimContext, ClientExtension, ResultClaim, advertise
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.server.extension import Extension
from mcp.server.mcpserver import Context, MCPServer, require_client_extension
from tests.interaction._connect import Connect
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio

_RECEIPTS = "com.example/receipts"
_FLAGS = "com.example/flags"


class ReceiptResult(Result):
    """The claimed `tools/call` shape, tagged `receipt`; its payload rides `requestState`."""

    result_type: Literal["receipt"] = "receipt"
    request_state: str


_Resolver = Callable[[ReceiptResult, ClaimContext], Awaitable[CallToolResult]]


class Receipts(ClientExtension):
    """Client half: claims the `receipt` tag with the test's resolver and settings."""

    identifier = _RECEIPTS

    def __init__(self, resolve: _Resolver, settings: dict[str, Any] | None = None) -> None:
        self._resolve = resolve
        self._settings = {} if settings is None else settings

    def settings(self) -> dict[str, Any]:
        return self._settings

    def claims(self) -> Sequence[ResultClaim[Any]]:
        return [ResultClaim(result_type="receipt", model=ReceiptResult, resolve=self._resolve)]


class _ReceiptIssuer(Extension):
    """Server half: answers `buy` with the claimed shape; every other tool passes through."""

    identifier = _RECEIPTS

    async def intercept_tool_call(
        self, params: types.CallToolRequestParams, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        if params.name != "buy":
            return await call_next(ctx)
        return {"resultType": "receipt", "requestState": "r-117"}


def _receipt_shop(issuer: Extension) -> MCPServer:
    """An MCPServer whose `buy` tool the server extension rewrites into the claimed shape."""
    server = MCPServer("shop", extensions=[issuer])

    @server.tool()
    def buy(item: str) -> CallToolResult:
        """Buy an item."""
        raise NotImplementedError  # the server extension answers `buy` before the tool runs

    @server.tool()
    def redeem(token: str) -> str:
        """Exchange a receipt token for the goods."""
        return f"goods for {token}"

    return server


@requirement("extensions:client:claimed-result-resolved")
async def test_claimed_result_is_finished_by_the_owning_extensions_resolver(connect: Connect) -> None:
    """The transparent claim path, both ends real: the server extension substitutes the
    `receipt` shape, the client's claim resolver redeems it with a follow-up `tools/call`
    through `ctx.session` — the same authority as `client.session` — and `call_tool`
    returns the resolver's plain `CallToolResult`. The claimed shape never surfaces."""
    received: list[ReceiptResult] = []

    async def redeem_receipt(claimed: ReceiptResult, ctx: ClaimContext) -> CallToolResult:
        received.append(claimed)
        return await ctx.session.call_tool("redeem", {"token": claimed.request_state})

    async with connect(_receipt_shop(_ReceiptIssuer()), extensions=[Receipts(redeem_receipt)]) as client:
        result = await client.call_tool("buy", {"item": "lamp"})

    assert [claimed.request_state for claimed in received] == ["r-117"]
    assert result == snapshot(
        CallToolResult(content=[TextContent(text="goods for r-117")], structured_content={"result": "goods for r-117"})
    )


@requirement("extensions:client:claimed-result-undeclared-invalid")
async def test_claimed_shape_fails_validation_for_a_client_without_the_extension(connect: Connect) -> None:
    """Spec-mandated: an unrecognized `resultType` is invalid. A client that did not
    construct the owning extension rejects the very shape the previous test resolves —
    the request reaches the server, the substituted result fails client-side parsing."""
    async with connect(_receipt_shop(_ReceiptIssuer())) as client:
        with pytest.raises(ValidationError):
            await client.call_tool("buy", {"item": "lamp"})


class _SettingsEchoIssuer(Extension):
    """Server half for the ad tests: refuses non-declaring clients, then echoes the
    declared settings back through the claimed payload."""

    identifier = _RECEIPTS

    async def intercept_tool_call(
        self, params: types.CallToolRequestParams, ctx: ServerRequestContext[Any, Any], call_next: CallNext
    ) -> HandlerResult:
        require_client_extension(ctx, _RECEIPTS)
        client_params = ctx.session.client_params
        assert client_params is not None  # require_client_extension just read it
        extensions = client_params.capabilities.extensions
        assert extensions is not None
        return {"resultType": "receipt", "requestState": json.dumps(extensions[_RECEIPTS], sort_keys=True)}


@requirement("extensions:client:capability-ad:gates-server-behaviour")
async def test_per_request_ad_carries_settings_and_gates_the_claimed_substitution(connect: Connect) -> None:
    """The per-request `_meta` capability ad is the entitlement for claimed shapes: the
    server extension's gate passes only for the declaring client, observes the declared
    settings on the request, and the resolver receives them back through the payload.
    A client declaring nothing is refused with -32021, not served the shape."""
    server = MCPServer("shop", extensions=[_SettingsEchoIssuer()])

    @server.tool()
    def buy(item: str) -> CallToolResult:
        """Buy an item."""
        raise NotImplementedError  # the server extension answers `buy` before the tool runs

    received: list[ReceiptResult] = []

    async def keep(claimed: ReceiptResult, ctx: ClaimContext) -> CallToolResult:
        received.append(claimed)
        return CallToolResult(content=[TextContent(text="done")])

    async with connect(server, extensions=[Receipts(keep, settings={"tier": "gold"})]) as client:
        result = await client.call_tool("buy", {"item": "lamp"})
    assert result.content == [TextContent(text="done")]
    assert [json.loads(claimed.request_state) for claimed in received] == [{"tier": "gold"}]

    async with connect(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("buy", {"item": "lamp"})
    assert exc_info.value.code == MISSING_REQUIRED_CLIENT_CAPABILITY


async def _unreachable_resolve(claimed: ReceiptResult, ctx: ClaimContext) -> CallToolResult:
    raise NotImplementedError  # no claimed shape can be delivered on a legacy wire


@requirement("extensions:client:capability-ad:legacy-omits-claimed")
async def test_legacy_ad_omits_claim_bearing_identifiers_but_keeps_claim_less_ones(connect: Connect) -> None:
    """On a legacy connection the claims dissolve and the ad follows them: the
    claim-bearing identifier is absent from the initialize capability ad the server
    sees, while an ad-only identifier on the same client still advertises."""
    server = MCPServer("introspector")

    @server.tool()
    def declared(ctx: Context) -> list[str]:
        """Report the extension identifiers the client advertised."""
        capabilities = ctx.client_capabilities
        assert capabilities is not None
        return sorted(capabilities.extensions or {})

    client_extensions = [Receipts(_unreachable_resolve), advertise(_FLAGS)]
    async with connect(server, extensions=client_extensions) as client:
        result = await client.call_tool("declared", {})

    assert result.structured_content == {"result": [_FLAGS]}
