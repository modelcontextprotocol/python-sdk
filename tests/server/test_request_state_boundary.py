"""`mcp.server.request_state`: the `RequestStateBoundary` middleware and its claims
envelope, proven through the public wire surfaces — `requestState` is sealed on the way
out, verified and restored on the way back, and every verification failure collapses to
one frozen wire error (MCP 2026-07-28, basic/patterns/mrtr server requirements 4-5).

Servers here use MANUAL multi-round-trip tools (a plain `@mcp.tool()` returning
`str | InputRequiredResult` that reads `ctx.input_responses` / `ctx.request_state`),
driven by the manual client loop on `client.session.call_tool`.
"""

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

import anyio
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    CallToolRequestParams,
    CallToolResult,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    ListToolsResult,
    PaginatedRequestParams,
    ReadResourceResult,
    RequestParams,
    TextContent,
    TextResourceContents,
    Tool,
)

import mcp.server.request_state as request_state_module
from mcp import Client
from mcp.server import MCPServer, Server, ServerRequestContext
from mcp.server.context import HandlerResult
from mcp.server.mcpserver import Context
from mcp.server.request_state import (
    AESGCMRequestStateCodec,
    InvalidRequestState,
    RequestStateBoundary,
    RequestStateSecurity,
)
from mcp.shared.exceptions import MCPError

from .test_runner import connected_runner

pytestmark = pytest.mark.anyio

_KEY = b"0123456789abcdef0123456789abcdef"  # 32 bytes; a test fixture, not a secret
_T0 = 1_782_345_600.0  # frozen mint instant for clock-controlled tests
_TTL = 600.0


def _ask(message: str) -> ElicitRequest:
    """A minimal elicitation request for a manual tool's `input_requests`."""
    return ElicitRequest(
        params=ElicitRequestFormParams(
            message=message,
            requested_schema={
                "type": "object",
                "properties": {"confirm": {"type": "boolean"}},
                "required": ["confirm"],
            },
        )
    )


def _accept() -> ElicitResult:
    return ElicitResult(action="accept", content={"confirm": True})


async def _list_tools(ctx: ServerRequestContext[Any], params: PaginatedRequestParams | None) -> ListToolsResult:
    """Minimal listing for lowlevel fixtures: `ClientSession.call_tool` consults
    tools/list for output-schema validation, so the server must answer it."""
    return ListToolsResult(tools=[Tool(name="t", input_schema={"type": "object"})])


class _PassthroughCodec:
    """A contract-valid codec with no crypto: the token IS the payload bytes.

    Lets a test place arbitrary payload bytes behind a successful unseal, to
    prove the boundary's own claims checks reject what a codec cannot vouch for.
    """

    def seal(self, payload: bytes) -> str:
        return payload.decode()

    def unseal(self, token: str) -> bytes:
        return token.encode()


class _CustomMethodParams(RequestParams):
    """Params for a lowlevel custom (extension-style) method in the off-set tests."""

    request_state: str | None = None


class _Clock:
    """Stands in for the `time` module inside `mcp.server.request_state`."""

    def __init__(self, now: float) -> None:
        self.now = now

    def time(self) -> float:
        return self.now


def _tamper(token: str) -> str:
    """Flip one mid-token character. Strict canonical decoding means any single-character
    change rejects — including the final char, whose don't-care padding bits a lax decoder
    would ignore (pinned by the canonicality tests in test_request_state.py)."""
    i = len(token) // 2
    return token[:i] + ("A" if token[i] != "A" else "B") + token[i + 1 :]


def _assert_frozen_rejection(exc: pytest.ExceptionInfo[MCPError]) -> None:
    """The single frozen wire shape for every inbound verification failure.

    Frozen contract — asserted explicitly, never snapshotted.
    """
    assert exc.value.error.code == INVALID_PARAMS
    assert exc.value.error.message == "Invalid or expired requestState"
    assert exc.value.error.data == {"reason": "invalid_request_state"}


def _manual_server(
    security: RequestStateSecurity, *, state: str = "awaiting-confirm", name: str = "manual"
) -> tuple[MCPServer, list[str | None]]:
    """An MCPServer with one manual MRTR tool: round 1 asks, the retry records the
    restored `ctx.request_state` and completes. `name` is also the boundary's default
    audience."""
    seen: list[str | None] = []
    mcp = MCPServer(name, request_state_security=security)

    @mcp.tool()
    async def deploy(env: str, ctx: Context) -> str | InputRequiredResult:
        if ctx.input_responses is None:
            return InputRequiredResult(input_requests={"confirm": _ask(f"Deploy to {env}?")}, request_state=state)
        seen.append(ctx.request_state)
        return f"deployed to {env}"

    return mcp, seen


async def _first_round(client: Client, name: str, args: dict[str, Any]) -> str:
    """Round 1 of the manual loop: call without responses, return the wire token."""
    first = await client.session.call_tool(name, args, allow_input_required=True)
    assert isinstance(first, InputRequiredResult)
    assert first.request_state is not None
    return first.request_state


async def _retry(client: Client, name: str, args: dict[str, Any], token: str) -> CallToolResult | InputRequiredResult:
    """The retry round: echo the wire token with the elicited answer attached."""
    return await client.session.call_tool(
        name, args, input_responses={"confirm": _accept()}, request_state=token, allow_input_required=True
    )


# -- end-to-end seal/unseal through the public surfaces -------------------------------


async def test_request_state_is_sealed_on_the_wire_and_restored_for_the_handler() -> None:
    """Spec-mandated (basic/patterns/mrtr server requirements 4-5): the wire carries an
    opaque integrity-protected token — never the handler's plaintext — and a faithful
    echo hands the handler back exactly the state it minted."""
    plaintext = "awaiting-confirm:9f2e"
    mcp, seen = _manual_server(RequestStateSecurity(keys=[_KEY]), state=plaintext)

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            first = await client.session.call_tool("deploy", {"env": "prod"}, allow_input_required=True)
            assert isinstance(first, InputRequiredResult)
            assert first.request_state is not None
            assert first.request_state != plaintext
            assert first.request_state.startswith("v1.")
            second = await _retry(client, "deploy", {"env": "prod"}, first.request_state)

    assert isinstance(second, CallToolResult)
    assert not second.is_error
    assert isinstance(second.content[0], TextContent)
    assert second.content[0].text == "deployed to prod"
    assert seen == [plaintext]


async def test_lowlevel_server_gets_identical_sealing_from_the_one_line_middleware_append() -> None:
    """Spec-mandated (basic/patterns/mrtr server requirements 4-5): appending the public
    `RequestStateBoundary` to `Server.middleware` gives the lowlevel tier the same sealed
    wire and the same plaintext restore — nothing is private to MCPServer."""
    plaintext = "lowlevel-round-1"
    seen: list[str | None] = []

    async def call_tool(
        ctx: ServerRequestContext[Any], params: CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        if params.input_responses is None:
            return InputRequiredResult(input_requests={"confirm": _ask("Proceed?")}, request_state=plaintext)
        seen.append(params.request_state)
        return CallToolResult(content=[TextContent(text="done")])

    server = Server("srv", on_call_tool=call_tool, on_list_tools=_list_tools)
    server.middleware.append(RequestStateBoundary(RequestStateSecurity(keys=[_KEY])))

    with anyio.fail_after(5):
        async with Client(server) as client:
            first = await client.session.call_tool("t", {}, allow_input_required=True)
            assert isinstance(first, InputRequiredResult)
            assert first.request_state is not None
            assert first.request_state != plaintext
            assert first.request_state.startswith("v1.")
            second = await _retry(client, "t", {}, first.request_state)

    assert isinstance(second, CallToolResult)
    assert seen == [plaintext]


async def test_a_resource_template_flow_seals_on_resources_read_and_restores_the_plaintext() -> None:
    """Spec-mandated (basic/patterns/mrtr server requirements 4-5): resources/read is an
    MRTR carrier too — a template's `requestState` crosses the wire sealed and bound to
    the originating uri, and the faithful retry hands the template function back its
    plaintext."""
    plaintext = "resource-round-1"
    seen: list[str | None] = []
    mcp = MCPServer("templated", request_state_security=RequestStateSecurity(keys=[_KEY]))

    @mcp.resource("deploy://{env}/confirm")
    async def confirm(env: str, ctx: Context) -> str | InputRequiredResult:
        if ctx.input_responses is None:
            return InputRequiredResult(input_requests={"confirm": _ask(f"Read {env}?")}, request_state=plaintext)
        seen.append(ctx.request_state)
        return f"confirmed {env}"

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            first = await client.session.read_resource("deploy://prod/confirm", allow_input_required=True)
            assert isinstance(first, InputRequiredResult)
            assert first.request_state is not None
            assert first.request_state != plaintext
            assert first.request_state.startswith("v1.")
            second = await client.session.read_resource(
                "deploy://prod/confirm",
                input_responses={"confirm": _accept()},
                request_state=first.request_state,
                allow_input_required=True,
            )

    assert isinstance(second, ReadResourceResult)
    assert isinstance(second.contents[0], TextResourceContents)
    assert second.contents[0].text == "confirmed prod"
    claims = json.loads(AESGCMRequestStateCodec([_KEY]).unseal(first.request_state))
    assert (claims["m"], claims["t"], claims["s"]) == ("resources/read", "deploy://prod/confirm", plaintext)
    assert seen == [plaintext]


# -- verification failures: tamper, expiry, future skew -------------------------------


async def test_tampered_request_state_is_rejected_with_the_frozen_wire_error() -> None:
    """Spec-mandated (basic/patterns/mrtr server requirement 5): a modified echo fails
    authentication and is rejected with the frozen -32602 shape; the handler never runs."""
    mcp, seen = _manual_server(RequestStateSecurity(keys=[_KEY]))

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            token = await _first_round(client, "deploy", {"env": "prod"})
            with pytest.raises(MCPError) as exc:
                await _retry(client, "deploy", {"env": "prod"}, _tamper(token))
            _assert_frozen_rejection(exc)

    assert seen == []


async def test_expired_request_state_is_rejected_and_just_inside_ttl_is_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec-mandated (basic/patterns/mrtr server requirements 4-5, expiration bound): one
    second past `ttl` is the frozen rejection; one second inside completes the flow."""
    mcp, seen = _manual_server(RequestStateSecurity(keys=[_KEY], ttl=_TTL))
    clock = _Clock(_T0)
    monkeypatch.setattr(request_state_module, "time", clock)

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            token = await _first_round(client, "deploy", {"env": "prod"})  # minted at _T0
            clock.now = _T0 + _TTL + 1
            with pytest.raises(MCPError) as exc:
                await _retry(client, "deploy", {"env": "prod"}, token)
            clock.now = _T0 + _TTL - 1
            second = await _retry(client, "deploy", {"env": "prod"}, token)

    _assert_frozen_rejection(exc)
    assert isinstance(second, CallToolResult)
    assert seen == ["awaiting-confirm"]


async def test_state_minted_in_the_future_is_rejected_beyond_the_sixty_second_skew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec-mandated (basic/patterns/mrtr server requirements 4-5): a token minted 120 s
    ahead of the verifier's clock is rejected; 30 s ahead is inside the skew allowance."""
    mcp, seen = _manual_server(RequestStateSecurity(keys=[_KEY], ttl=_TTL))
    clock = _Clock(_T0)
    monkeypatch.setattr(request_state_module, "time", clock)

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            token = await _first_round(client, "deploy", {"env": "prod"})  # minted at _T0
            clock.now = _T0 - 120
            with pytest.raises(MCPError) as exc:
                await _retry(client, "deploy", {"env": "prod"}, token)
            clock.now = _T0 - 30
            second = await _retry(client, "deploy", {"env": "prod"}, token)

    _assert_frozen_rejection(exc)
    assert isinstance(second, CallToolResult)
    assert seen == ["awaiting-confirm"]


# -- request binding -------------------------------------------------------------------


async def test_round_one_state_replayed_on_a_different_tool_is_rejected() -> None:
    """Spec-mandated (basic/patterns/mrtr server requirement 4, originating-request
    binding): a token minted for tool A fails verification when echoed on tool B of the
    same server, while the faithful retry on tool A still completes."""
    seen: list[str | None] = []

    def make_tool(state: str) -> Callable[[Context], Awaitable[str | InputRequiredResult]]:
        async def tool(ctx: Context) -> str | InputRequiredResult:
            if ctx.input_responses is None:
                return InputRequiredResult(input_requests={"confirm": _ask(state)}, request_state=state)
            seen.append(ctx.request_state)
            return "done"

        return tool

    mcp = MCPServer("two-tools", request_state_security=RequestStateSecurity(keys=[_KEY]))
    mcp.tool(name="alpha")(make_tool("alpha-state"))
    mcp.tool(name="beta")(make_tool("beta-state"))

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            token = await _first_round(client, "alpha", {})
            with pytest.raises(MCPError) as exc:
                await _retry(client, "beta", {}, token)
            second = await _retry(client, "alpha", {}, token)

    _assert_frozen_rejection(exc)
    assert isinstance(second, CallToolResult)
    assert seen == ["alpha-state"]


async def test_retry_with_different_arguments_is_rejected_and_the_original_arguments_complete() -> None:
    """Spec-mandated (basic/patterns/mrtr server requirement 4, argument binding): the
    same tool retried with different arguments is the frozen rejection; the retry that
    repeats the original arguments completes."""
    mcp, seen = _manual_server(RequestStateSecurity(keys=[_KEY]))

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            token = await _first_round(client, "deploy", {"env": "prod"})
            with pytest.raises(MCPError) as exc:
                await _retry(client, "deploy", {"env": "staging"}, token)
            second = await _retry(client, "deploy", {"env": "prod"}, token)

    _assert_frozen_rejection(exc)
    assert isinstance(second, CallToolResult)
    assert seen == ["awaiting-confirm"]


# -- principal binding -----------------------------------------------------------------


async def test_state_minted_with_a_principal_is_rejected_when_the_verifier_derives_none() -> None:
    """Spec-mandated (basic/patterns/mrtr server requirement 4, user binding): principal
    binding fails closed — state sealed for a principal is rejected by a round on which
    `bind_principal` derives none."""
    principal: list[str | None] = ["alice"]
    mcp, seen = _manual_server(RequestStateSecurity(keys=[_KEY], bind_principal=lambda ctx: principal[0]))

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            token = await _first_round(client, "deploy", {"env": "prod"})
            principal[0] = None
            with pytest.raises(MCPError) as exc:
                await _retry(client, "deploy", {"env": "prod"}, token)
            _assert_frozen_rejection(exc)

    assert seen == []


async def test_state_minted_without_a_principal_is_rejected_when_the_verifier_derives_one() -> None:
    """Spec-mandated (basic/patterns/mrtr server requirement 4, user binding): the other
    drift direction also fails closed — unbound state is rejected once the verifying
    round derives a principal."""
    principal: list[str | None] = [None]
    mcp, seen = _manual_server(RequestStateSecurity(keys=[_KEY], bind_principal=lambda ctx: principal[0]))

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            token = await _first_round(client, "deploy", {"env": "prod"})
            principal[0] = "alice"
            with pytest.raises(MCPError) as exc:
                await _retry(client, "deploy", {"env": "prod"}, token)
            _assert_frozen_rejection(exc)

    assert seen == []


async def test_state_for_a_different_principal_is_rejected_and_the_same_principal_completes() -> None:
    """Spec-mandated (basic/patterns/mrtr server requirement 4, user binding): a token
    minted for one principal is rejected when echoed by another, and accepted when the
    same principal returns."""
    principal: list[str | None] = ["alice"]
    mcp, seen = _manual_server(RequestStateSecurity(keys=[_KEY], bind_principal=lambda ctx: principal[0]))

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            token = await _first_round(client, "deploy", {"env": "prod"})
            principal[0] = "bob"
            with pytest.raises(MCPError) as exc:
                await _retry(client, "deploy", {"env": "prod"}, token)
            principal[0] = "alice"
            second = await _retry(client, "deploy", {"env": "prod"}, token)

    _assert_frozen_rejection(exc)
    assert isinstance(second, CallToolResult)
    assert seen == ["awaiting-confirm"]


async def test_a_principal_binding_that_raises_fails_the_seal_as_an_internal_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SDK-defined fail-safe: a raising `bind_principal` must not mint unbound state —
    the round fails as a bare internal error and the traceback stays in the server log."""

    def boom(ctx: ServerRequestContext[Any, Any]) -> str | None:
        raise RuntimeError("identity provider down")

    mcp, seen = _manual_server(RequestStateSecurity(keys=[_KEY], bind_principal=boom))

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            with pytest.raises(MCPError) as exc:
                await client.session.call_tool("deploy", {"env": "prod"}, allow_input_required=True)
            assert exc.value.error.code == INTERNAL_ERROR
            assert exc.value.error.message == "Internal error"
            assert exc.value.error.data is None  # the reason never reaches the wire

    assert seen == []
    assert any(r.exc_info is not None and r.exc_info[0] is RuntimeError for r in caplog.records)


async def test_a_principal_binding_that_raises_fails_the_unseal_with_the_frozen_rejection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SDK-defined fail-safe: a `bind_principal` that raises while verifying must not
    bypass the frozen contract — the round collapses to the frozen -32602 and the
    traceback stays in the server log."""
    rounds: list[int] = []

    def flaky(ctx: ServerRequestContext[Any, Any]) -> str | None:
        rounds.append(1)
        if len(rounds) == 1:
            return "alice"  # the mint succeeds...
        raise RuntimeError("identity provider down")  # ...the verify round raises

    mcp, seen = _manual_server(RequestStateSecurity(keys=[_KEY], bind_principal=flaky))

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            token = await _first_round(client, "deploy", {"env": "prod"})
            with pytest.raises(MCPError) as exc:
                await _retry(client, "deploy", {"env": "prod"}, token)
            _assert_frozen_rejection(exc)

    assert seen == []
    assert any(r.exc_info is not None and r.exc_info[0] is RuntimeError for r in caplog.records)


async def test_two_mints_for_the_same_principal_carry_different_salted_principal_claims() -> None:
    """SDK-defined: the `p` claim is salted per mint, so two tokens for the same
    principal are not linkable by their principal digests (and `p` is present whenever a
    principal is bound)."""
    mcp, _ = _manual_server(RequestStateSecurity(keys=[_KEY], bind_principal=lambda ctx: "alice"))

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            token_one = await _first_round(client, "deploy", {"env": "prod"})
            token_two = await _first_round(client, "deploy", {"env": "prod"})

    codec = AESGCMRequestStateCodec([_KEY])
    claims_one = json.loads(codec.unseal(token_one))
    claims_two = json.loads(codec.unseal(token_two))
    assert "p" in claims_one
    assert "p" in claims_two
    assert claims_one["p"] != claims_two["p"]


# -- audience binding ------------------------------------------------------------------


async def test_two_servers_sharing_a_key_reject_each_others_state_via_the_name_audience() -> None:
    """SDK-defined: `MCPServer` wires its server name as the boundary's default audience,
    so two services sharing (or accidentally reusing) a secret reject each other's state
    out of the box — while each still completes its own flow."""
    mcp_billing, seen_billing = _manual_server(RequestStateSecurity(keys=[_KEY]), name="billing")
    mcp_payments, seen_payments = _manual_server(RequestStateSecurity(keys=[_KEY]), name="payments")

    with anyio.fail_after(5):
        async with Client(mcp_billing) as billing, Client(mcp_payments) as payments:
            token = await _first_round(billing, "deploy", {"env": "prod"})
            with pytest.raises(MCPError) as exc:
                await _retry(payments, "deploy", {"env": "prod"}, token)
            second = await _retry(billing, "deploy", {"env": "prod"}, token)

    _assert_frozen_rejection(exc)
    assert isinstance(second, CallToolResult)
    assert seen_billing == ["awaiting-confirm"]
    assert seen_payments == []


async def test_audience_presence_drift_is_rejected_in_both_directions() -> None:
    """SDK-defined fail-closed: state minted with an audience is rejected by a boundary
    expecting none, and audience-unbound state is rejected by a boundary expecting one —
    while each boundary still accepts its own mint (lowlevel tier: the audience is the
    boundary's `default_audience`, no MCPServer involved)."""

    def make_server(boundary: RequestStateBoundary) -> Server:
        async def call_tool(
            ctx: ServerRequestContext[Any], params: CallToolRequestParams
        ) -> CallToolResult | InputRequiredResult:
            if params.input_responses is None:
                return InputRequiredResult(input_requests={"confirm": _ask("Go?")}, request_state="round-1")
            return CallToolResult(content=[TextContent(text="done")])

        server = Server("srv", on_call_tool=call_tool, on_list_tools=_list_tools)
        server.middleware.append(boundary)
        return server

    security = RequestStateSecurity(keys=[_KEY])
    bound = make_server(RequestStateBoundary(security, default_audience="svc"))
    unbound = make_server(RequestStateBoundary(security))

    with anyio.fail_after(5):
        async with Client(bound) as on_bound, Client(unbound) as on_unbound:
            bound_token = await _first_round(on_bound, "t", {})
            unbound_token = await _first_round(on_unbound, "t", {})
            with pytest.raises(MCPError) as bound_state_on_unbound:
                await _retry(on_unbound, "t", {}, bound_token)
            with pytest.raises(MCPError) as unbound_state_on_bound:
                await _retry(on_bound, "t", {}, unbound_token)
            assert isinstance(await _retry(on_bound, "t", {}, bound_token), CallToolResult)
            assert isinstance(await _retry(on_unbound, "t", {}, unbound_token), CallToolResult)

    _assert_frozen_rejection(bound_state_on_unbound)
    _assert_frozen_rejection(unbound_state_on_bound)


async def test_an_explicit_policy_audience_overrides_the_server_name_default() -> None:
    """SDK-defined: `RequestStateSecurity(audience=...)` wins over the server-name
    default — the envelope carries the policy's audience and the flow still completes."""
    mcp, seen = _manual_server(RequestStateSecurity(keys=[_KEY], audience="prod-fleet"), name="one-box")

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            token = await _first_round(client, "deploy", {"env": "prod"})
            second = await _retry(client, "deploy", {"env": "prod"}, token)

    claims = json.loads(AESGCMRequestStateCodec([_KEY]).unseal(token))
    assert claims["aud"] == "prod-fleet"
    assert isinstance(second, CallToolResult)
    assert seen == ["awaiting-confirm"]


# -- claims envelope (white-box through the public codec) -----------------------------


async def test_claims_envelope_carries_the_documented_fields_and_omits_p_when_unbound() -> None:
    """SDK-defined envelope contract: the sealed payload is the documented claims JSON —
    version, mint/expiry stamps, originating method/target/argument digest, the audience
    (an MCPServer defaults it to the server name), and the plaintext — with no `p` claim
    when `bind_principal` returns None."""
    plaintext = "step-one"
    mcp, _ = _manual_server(
        RequestStateSecurity(keys=[_KEY], ttl=_TTL, bind_principal=lambda ctx: None), state=plaintext
    )

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            token = await _first_round(client, "deploy", {"env": "prod"})

    claims = json.loads(AESGCMRequestStateCodec([_KEY]).unseal(token))
    assert set(claims) == {"v", "iat", "exp", "m", "t", "a", "s", "aud"}
    assert claims["v"] == 1
    assert claims["exp"] == claims["iat"] + int(_TTL)
    assert claims["m"] == "tools/call"
    assert claims["t"] == "deploy"
    assert isinstance(claims["a"], str) and claims["a"]
    assert claims["aud"] == "manual"  # the MCPServer name, the boundary's default audience
    assert claims["s"] == plaintext


async def test_each_round_is_resealed_with_a_fresh_token_and_a_restamped_iat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SDK-defined: a multi-round flow reseals every round — round 2's token differs from
    round 1's and carries a fresh mint stamp, so `ttl` bounds per-round think time rather
    than total flow time."""
    mcp = MCPServer("wizard-server", request_state_security=RequestStateSecurity(keys=[_KEY], ttl=_TTL))

    @mcp.tool()
    async def wizard(ctx: Context) -> str | InputRequiredResult:
        if ctx.input_responses is None:
            return InputRequiredResult(input_requests={"first": _ask("First?")}, request_state="step-1")
        if ctx.request_state == "step-1":
            return InputRequiredResult(input_requests={"second": _ask("Second?")}, request_state="step-2")
        return "done"

    clock = _Clock(_T0)
    monkeypatch.setattr(request_state_module, "time", clock)

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            first = await client.session.call_tool("wizard", {}, allow_input_required=True)
            assert isinstance(first, InputRequiredResult)
            assert first.request_state is not None
            clock.now = _T0 + 5
            second = await client.session.call_tool(
                "wizard",
                {},
                input_responses={"first": _accept()},
                request_state=first.request_state,
                allow_input_required=True,
            )
            assert isinstance(second, InputRequiredResult)
            assert second.request_state is not None
            third = await client.session.call_tool(
                "wizard",
                {},
                input_responses={"second": _accept()},
                request_state=second.request_state,
                allow_input_required=True,
            )

    assert isinstance(third, CallToolResult)
    assert first.request_state != second.request_state
    codec = AESGCMRequestStateCodec([_KEY])
    claims_one = json.loads(codec.unseal(first.request_state))
    claims_two = json.loads(codec.unseal(second.request_state))
    assert claims_two["iat"] >= claims_one["iat"]
    assert (claims_one["iat"], claims_two["iat"]) == (int(_T0), int(_T0) + 5)


# -- unconfigured boundary (lowlevel tier, no startup gate) ----------------------------


async def test_an_unconfigured_boundary_rejects_inbound_request_state_before_the_handler() -> None:
    """Spec-mandated fail-safe (basic/patterns/mrtr server requirement 5): a server that
    never minted state rejects any inbound echo with the frozen error before the handler
    runs; a request without `requestState` is untouched."""
    calls: list[str] = []

    async def call_tool(ctx: ServerRequestContext[Any], params: CallToolRequestParams) -> CallToolResult:
        calls.append(params.name)
        return CallToolResult(content=[TextContent(text="ran")])

    server = Server("srv", on_call_tool=call_tool, on_list_tools=_list_tools)
    server.middleware.append(RequestStateBoundary(None))

    with anyio.fail_after(5):
        async with Client(server) as client:
            with pytest.raises(MCPError) as exc:
                await client.session.call_tool("t", {}, request_state="v1.forged", allow_input_required=True)
            assert calls == []
            ok = await client.session.call_tool("t", {})

    _assert_frozen_rejection(exc)
    assert isinstance(ok, CallToolResult)
    assert calls == ["t"]


async def test_an_unconfigured_boundary_answers_outbound_state_with_internal_error_and_logs_remediation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SDK-defined fail-safe: an unconfigured boundary never forwards plaintext state —
    the request fails as a bare internal error and the full remediation (and nothing
    secret) goes to the server log."""

    async def call_tool(ctx: ServerRequestContext[Any], params: CallToolRequestParams) -> InputRequiredResult:
        return InputRequiredResult(input_requests={"confirm": _ask("?")}, request_state="oops-plaintext")

    server = Server("srv", on_call_tool=call_tool)
    server.middleware.append(RequestStateBoundary(None))

    with anyio.fail_after(5):
        async with Client(server) as client:
            with pytest.raises(MCPError) as exc:
                await client.session.call_tool("t", {}, allow_input_required=True)
            assert exc.value.error.code == INTERNAL_ERROR
            assert exc.value.error.message == "Internal error"

    errors = [r for r in caplog.records if r.name == "mcp.server.request_state" and r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert errors[0].getMessage() == snapshot(
        "handler for tools/call returned an InputRequiredResult with requestState, but no "
        "request_state_security is configured on this server; refusing to send unprotected "
        "state. Pass request_state_security=RequestStateSecurity(...) to MCPServer "
        "(or .ephemeral() for single-process, or .unprotected() to accept the risk)."
    )
    assert "oops-plaintext" not in caplog.text


# -- explicit opt-out ------------------------------------------------------------------


async def test_unprotected_mode_passes_request_state_through_verbatim() -> None:
    """SDK-defined: `RequestStateSecurity.unprotected()` is the spec's explicit opt-out
    (MAY omit protection when tampering can cause nothing worse than request failure) —
    the wire carries exactly the handler's plaintext and a verbatim echo is accepted."""
    plaintext = "plain-wizard-state"
    mcp, seen = _manual_server(RequestStateSecurity.unprotected(), state=plaintext)

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            first = await client.session.call_tool("deploy", {"env": "prod"}, allow_input_required=True)
            assert isinstance(first, InputRequiredResult)
            assert first.request_state == plaintext
            second = await _retry(client, "deploy", {"env": "prod"}, plaintext)

    assert isinstance(second, CallToolResult)
    assert seen == [plaintext]


# -- malformed wire input --------------------------------------------------------------


async def test_non_string_inbound_request_state_is_rejected_with_the_frozen_error() -> None:
    """Spec-mandated (basic/patterns/mrtr server requirement 5): a structurally invalid
    (non-string) `requestState` placed raw in the params fails at the boundary — before
    model validation — with the frozen shape; a stateless request still reaches the
    handler."""
    calls: list[str] = []

    async def call_tool(ctx: ServerRequestContext[Any], params: CallToolRequestParams) -> CallToolResult:
        calls.append(params.name)
        return CallToolResult(content=[TextContent(text="ran")])

    server = Server("srv", on_call_tool=call_tool)
    server.middleware.append(RequestStateBoundary(RequestStateSecurity(keys=[_KEY])))

    async with connected_runner(server) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("tools/call", {"name": "t", "arguments": {}, "requestState": 123})
        assert calls == []
        result = await client.send_raw_request("tools/call", {"name": "t", "arguments": {}})

    _assert_frozen_rejection(exc)
    assert result["content"][0]["text"] == "ran"
    assert calls == ["t"]


@pytest.mark.parametrize(
    "security",
    [
        pytest.param(RequestStateSecurity(keys=[_KEY]), id="configured"),
        pytest.param(None, id="unconfigured"),
    ],
)
async def test_an_explicit_null_request_state_is_treated_as_absent(security: RequestStateSecurity | None) -> None:
    """SDK-defined (spec-aligned): an explicit `"requestState": null` is the field's
    absence — a fresh flow, not presented state. The reject-MUST governs PRESENTED state,
    and stripping the field is already in any client's power, so the handler runs and
    sees None — on a configured server and on an unconfigured boundary alike."""
    seen: list[str | None] = []

    async def call_tool(ctx: ServerRequestContext[Any], params: CallToolRequestParams) -> CallToolResult:
        seen.append(params.request_state)
        return CallToolResult(content=[TextContent(text="ran")])

    server = Server("srv", on_call_tool=call_tool)
    server.middleware.append(RequestStateBoundary(security))

    async with connected_runner(server) as (client, _):
        result = await client.send_raw_request("tools/call", {"name": "t", "arguments": {}, "requestState": None})

    assert result["content"][0]["text"] == "ran"
    assert seen == [None]


# -- off-set methods: requestState has exactly three legal carriers ---------------------


async def test_inbound_request_state_on_a_non_mrtr_method_is_rejected_before_dispatch() -> None:
    """Spec-aligned fail-closed: only tools/call, prompts/get, and resources/read may
    carry `requestState`, so a custom (extension-style) method or any other spec method
    presenting one is answered with the frozen rejection before any unseal or handler
    dispatch — forged state can never be laundered through a method the claims check
    does not cover."""
    calls: list[str] = []

    async def custom(ctx: ServerRequestContext[Any], params: _CustomMethodParams) -> dict[str, Any]:
        calls.append(params.request_state or "fresh")
        return {"resultType": "complete"}

    server = Server("srv", on_list_tools=_list_tools)
    server.add_request_handler("example/mrtr", _CustomMethodParams, custom)
    server.middleware.append(RequestStateBoundary(RequestStateSecurity(keys=[_KEY])))

    async with connected_runner(server) as (client, _):
        for method in ("example/mrtr", "tools/list"):
            with pytest.raises(MCPError) as exc:
                await client.send_raw_request(method, {"requestState": "FORGED-BY-CLIENT"})
            _assert_frozen_rejection(exc)
        assert calls == []
        ok = await client.send_raw_request("example/mrtr", {})  # no state: dispatch is untouched

    assert ok == {"resultType": "complete"}
    assert calls == ["fresh"]


async def test_outbound_request_state_on_a_non_mrtr_method_is_an_internal_error_with_logged_remediation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Spec-aligned fail-closed: the spec restricts InputRequiredResult to the three MRTR
    carriers, so a custom method minting `requestState` is a server bug — the wire gets a
    bare internal error (never plaintext, never a sealed token) and the remediation goes
    to the server log."""

    async def custom(ctx: ServerRequestContext[Any], params: _CustomMethodParams) -> InputRequiredResult:
        return InputRequiredResult(input_requests={"confirm": _ask("?")}, request_state="ext-secret-plaintext")

    server = Server("srv", on_list_tools=_list_tools)
    server.add_request_handler("example/mrtr", _CustomMethodParams, custom)
    server.middleware.append(RequestStateBoundary(RequestStateSecurity(keys=[_KEY])))

    async with connected_runner(server) as (client, _):
        with pytest.raises(MCPError) as exc:
            await client.send_raw_request("example/mrtr", {})

    assert exc.value.error.code == INTERNAL_ERROR
    assert exc.value.error.message == "Internal error"
    errors = [r for r in caplog.records if r.name == "mcp.server.request_state" and r.levelno == logging.ERROR]
    assert len(errors) == 1
    assert errors[0].getMessage() == snapshot(
        "handler for example/mrtr returned an input_required result carrying requestState, but the spec "
        "restricts InputRequiredResult to tools/call, prompts/get, and resources/read; extension "
        "and custom methods must not mint requestState. Refusing to send it."
    )
    assert "ext-secret-plaintext" not in caplog.text


async def test_an_off_set_input_required_result_without_state_passes_through_untouched() -> None:
    """SDK-defined: an input_required-shaped result on a non-MRTR method that mints no
    `requestState` is not this module's concern — it crosses the boundary unmodified."""

    async def custom(ctx: ServerRequestContext[Any], params: _CustomMethodParams) -> InputRequiredResult:
        return InputRequiredResult(input_requests={"confirm": _ask("?")})

    server = Server("srv", on_list_tools=_list_tools)
    server.add_request_handler("example/mrtr", _CustomMethodParams, custom)
    server.middleware.append(RequestStateBoundary(RequestStateSecurity(keys=[_KEY])))

    async with connected_runner(server) as (client, _):
        result = await client.send_raw_request("example/mrtr", {})

    assert result["resultType"] == "input_required"
    assert "confirm" in result["inputRequests"]
    assert "requestState" not in result


# -- custom codec: deny on error -------------------------------------------------------


async def test_a_codec_that_raises_unexpectedly_fails_closed_with_the_frozen_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Spec-mandated fail-safe (basic/patterns/mrtr server requirement 5): a buggy custom
    codec denies on error — the wire gets the frozen rejection while the traceback stays
    in the server log."""

    class ExplodingCodec:
        def seal(self, payload: bytes) -> str:
            return "opaque-token"

        def unseal(self, token: str) -> bytes:
            raise RuntimeError("codec exploded")

    mcp, seen = _manual_server(RequestStateSecurity(codec=ExplodingCodec()))

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            token = await _first_round(client, "deploy", {"env": "prod"})
            assert token == "opaque-token"
            with pytest.raises(MCPError) as exc:
                await _retry(client, "deploy", {"env": "prod"}, token)
            # The exact-match frozen assertions also prove the exception text
            # never reached the wire.
            _assert_frozen_rejection(exc)

    assert seen == []
    assert any(r.exc_info is not None and r.exc_info[0] is RuntimeError for r in caplog.records)


async def test_a_codec_reject_reason_reaches_the_log_but_never_the_wire(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Spec-mandated (basic/patterns/mrtr server requirement 5) plus the SDK log
    contract: an `InvalidRequestState` reason from a custom codec is logged server-side
    while the wire stays the frozen shape."""

    class RefusingCodec:
        def seal(self, payload: bytes) -> str:
            return "opaque-token"

        def unseal(self, token: str) -> bytes:
            raise InvalidRequestState("boom")

    mcp, seen = _manual_server(RequestStateSecurity(codec=RefusingCodec()))

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            token = await _first_round(client, "deploy", {"env": "prod"})
            with pytest.raises(MCPError) as exc:
                await _retry(client, "deploy", {"env": "prod"}, token)
            # Exact-match frozen assertions prove "boom" is not on the wire.
            _assert_frozen_rejection(exc)

    assert "boom" in caplog.text
    assert seen == []


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param("not a claims envelope", id="not-json"),
        pytest.param(json.dumps({"v": 1, "iat": 1, "exp": 2}), id="json-missing-claims"),
        pytest.param(json.dumps({"v": 2, "iat": 1, "exp": 2, "s": "x"}), id="json-wrong-envelope-version"),
        pytest.param(json.dumps({"v": 1, "iat": 1, "exp": 2, "s": 7}), id="json-non-string-state"),
    ],
)
async def test_codec_authenticated_bytes_that_are_not_a_claims_envelope_are_rejected(payload: str) -> None:
    """SDK-defined (claims enforcement for every codec): bytes a codec vouches for are
    still nothing until they parse as the SDK's claims envelope — non-JSON payloads and
    well-formed JSON of the wrong shape both collapse to the frozen rejection before the
    handler runs (crafted via a passthrough codec; the built-in AEAD only ever
    authenticates envelopes it sealed itself)."""
    mcp, seen = _manual_server(RequestStateSecurity(codec=_PassthroughCodec(), bind_principal=None))

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            with pytest.raises(MCPError) as exc:
                await _retry(client, "deploy", {"env": "prod"}, payload)
            _assert_frozen_rejection(exc)

    assert seen == []


async def test_a_forged_principal_claim_that_is_not_base64_is_rejected() -> None:
    """SDK-defined (principal binding): a `p` claim that does not decode as base64 can
    never match any principal, so the round collapses to the frozen rejection even
    inside a token the codec authenticated (crafted via a passthrough codec; the
    built-in AEAD makes the claim untouchable)."""
    mcp, seen = _manual_server(RequestStateSecurity(codec=_PassthroughCodec(), bind_principal=lambda ctx: "alice"))

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            token = await _first_round(client, "deploy", {"env": "prod"})
            claims = json.loads(token)  # passthrough codec: the token IS the envelope JSON
            claims["p"] = "A"  # a single base64 char can never pad to a valid quantum
            with pytest.raises(MCPError) as exc:
                await _retry(client, "deploy", {"env": "prod"}, json.dumps(claims))
            _assert_frozen_rejection(exc)

    assert seen == []


@pytest.mark.parametrize("forged", [pytest.param(7, id="int"), pytest.param({"x": 1}, id="object")])
async def test_a_non_string_principal_claim_is_rejected_with_the_frozen_error(forged: Any) -> None:
    """SDK-defined (principal binding): a non-string `p` claim inside a validly-sealed
    envelope (possible only through a weak custom codec) collapses to the frozen
    rejection — it can never raise past `_reject` and leak exception text onto the
    wire."""
    mcp, seen = _manual_server(RequestStateSecurity(codec=_PassthroughCodec(), bind_principal=lambda ctx: "alice"))

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            token = await _first_round(client, "deploy", {"env": "prod"})
            claims = json.loads(token)  # passthrough codec: the token IS the envelope JSON
            claims["p"] = forged
            with pytest.raises(MCPError) as exc:
                await _retry(client, "deploy", {"env": "prod"}, json.dumps(claims))
            _assert_frozen_rejection(exc)

    assert seen == []


# -- log secrecy and the cause-invariant wire error ------------------------------------


async def test_the_wire_error_never_varies_by_cause_and_logs_never_leak_secrets(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Spec-mandated (basic/patterns/mrtr server requirement 5) plus the SDK log
    contract: tampered, expired, and rebound echoes produce byte-identical wire errors
    (no failure oracle), the real reasons are logged at WARNING, and no log record ever
    carries the token, the plaintext state, or the principal."""
    plaintext = "secret-plaintext-state-1f9b"
    principal = "principal-alice-7c3d"
    mcp, seen = _manual_server(
        RequestStateSecurity(keys=[_KEY], ttl=_TTL, bind_principal=lambda ctx: principal), state=plaintext
    )
    clock = _Clock(_T0)
    monkeypatch.setattr(request_state_module, "time", clock)

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            token = await _first_round(client, "deploy", {"env": "prod"})
            with pytest.raises(MCPError) as tampered:
                await _retry(client, "deploy", {"env": "prod"}, _tamper(token))
            clock.now = _T0 + _TTL + 1
            with pytest.raises(MCPError) as expired:
                await _retry(client, "deploy", {"env": "prod"}, token)
            clock.now = _T0
            with pytest.raises(MCPError) as rebound:
                await _retry(client, "deploy", {"env": "staging"}, token)
            _assert_frozen_rejection(tampered)

    shapes = [(e.value.error.code, e.value.error.message, e.value.error.data) for e in (tampered, expired, rebound)]
    assert shapes[0] == shapes[1] == shapes[2]
    assert seen == []

    reject_logs = [r for r in caplog.records if r.name == "mcp.server.request_state" and r.levelno == logging.WARNING]
    assert len(reject_logs) == 3  # the real reasons ARE logged...
    for record in caplog.records:  # ...but never the secrets
        message = record.getMessage()
        assert token not in message
        assert plaintext not in message
        assert principal not in message


# -- pass-through inertness ------------------------------------------------------------


async def test_a_complete_result_crosses_the_boundary_untouched() -> None:
    """SDK-defined: the outbound seam keys off `resultType` — a complete tools/call wire
    result passes through as the identical object."""
    boundary = RequestStateBoundary(RequestStateSecurity(keys=[_KEY], bind_principal=None))
    complete: dict[str, Any] = {"resultType": "complete", "content": []}

    async def call_next(ctx: ServerRequestContext[Any, Any]) -> HandlerResult:
        return complete

    ctx = ServerRequestContext(
        session=cast("Any", None),
        lifespan_context={},
        protocol_version="2026-07-28",
        method="tools/call",
        params={"name": "t", "arguments": {}},
    )

    assert await boundary(ctx, call_next) is complete


async def test_input_required_without_request_state_is_untouched() -> None:
    """SDK-defined: sealing keys off the `requestState` field — an `input_required`
    result that asks without minting state crosses the boundary unmodified, and the
    response-only retry completes."""
    seen: list[str | None] = []
    mcp = MCPServer("stateless-ask", request_state_security=RequestStateSecurity(keys=[_KEY]))

    @mcp.tool()
    async def ask(ctx: Context) -> str | InputRequiredResult:
        if ctx.input_responses is None:
            return InputRequiredResult(input_requests={"confirm": _ask("Sure?")})
        seen.append(ctx.request_state)
        return "done"

    with anyio.fail_after(5):
        async with Client(mcp) as client:
            first = await client.session.call_tool("ask", {}, allow_input_required=True)
            assert isinstance(first, InputRequiredResult)
            assert first.request_state is None
            second = await client.session.call_tool(
                "ask", {}, input_responses={"confirm": _accept()}, allow_input_required=True
            )

    assert isinstance(second, CallToolResult)
    assert seen == [None]


async def test_an_input_required_mapping_with_a_non_string_state_is_not_sealed() -> None:
    """SDK-defined: only a middleware short-circuiting below the boundary can put a
    non-string `requestState` in a wire mapping (the spec path validates the field as a
    string); that value is not state this module minted or seals, so the result crosses
    unchanged."""
    boundary = RequestStateBoundary(RequestStateSecurity(keys=[_KEY], bind_principal=None))
    malformed: dict[str, Any] = {"resultType": "input_required", "inputRequests": {}, "requestState": 7}

    async def call_next(ctx: ServerRequestContext[Any, Any]) -> HandlerResult:
        return malformed

    ctx = ServerRequestContext(
        session=cast("Any", None),
        lifespan_context={},
        protocol_version="2026-07-28",
        method="tools/call",
        params={"name": "t", "arguments": {}},
    )

    assert await boundary(ctx, call_next) is malformed


async def test_a_notification_crosses_the_boundary_unharmed() -> None:
    """SDK-defined: the boundary is inert for notifications — the context reaches
    `call_next` as the identical object and the None result comes back unchanged."""
    boundary = RequestStateBoundary(RequestStateSecurity(keys=[_KEY], bind_principal=None))
    forwarded: list[ServerRequestContext[Any, Any]] = []

    async def call_next(ctx: ServerRequestContext[Any, Any]) -> HandlerResult:
        forwarded.append(ctx)
        return None

    ctx = ServerRequestContext(
        session=cast("Any", None),
        lifespan_context={},
        protocol_version="2026-07-28",
        method="notifications/progress",
        params={"progressToken": "p", "progress": 1},
    )

    assert await boundary(ctx, call_next) is None
    assert len(forwarded) == 1
    assert forwarded[0] is ctx


async def test_a_non_mrtr_method_with_no_params_is_untouched() -> None:
    """SDK-defined: methods outside the MRTR trio pass the boundary inert — `tools/list`
    with absent params is forwarded and its result returned identically."""
    boundary = RequestStateBoundary(RequestStateSecurity(keys=[_KEY], bind_principal=None))
    listing: dict[str, Any] = {"tools": [], "resultType": "complete"}

    async def call_next(ctx: ServerRequestContext[Any, Any]) -> HandlerResult:
        return listing

    ctx = ServerRequestContext(
        session=cast("Any", None),
        lifespan_context={},
        protocol_version="2026-07-28",
        method="tools/list",
        params=None,
    )

    assert await boundary(ctx, call_next) is listing


# -- direct chain invocation: the model-path seal --------------------------------------


async def test_a_short_circuited_input_required_model_is_sealed_via_the_model_path() -> None:
    """SDK-defined: a middleware below the boundary that short-circuits with an
    `InputRequiredResult` MODEL (not the serialized wire dict) still has its state
    sealed — the boundary returns a copy carrying the sealed token, requests intact."""
    boundary = RequestStateBoundary(RequestStateSecurity(keys=[_KEY], bind_principal=None))
    interim = InputRequiredResult(input_requests={"confirm": _ask("Go?")}, request_state="model-plaintext")

    async def call_next(ctx: ServerRequestContext[Any, Any]) -> HandlerResult:
        return interim

    ctx = ServerRequestContext(
        session=cast("Any", None),
        lifespan_context={},
        protocol_version="2026-07-28",
        method="tools/call",
        params={"name": "shortcut", "arguments": {}},
    )

    result = await boundary(ctx, call_next)

    assert isinstance(result, InputRequiredResult)
    assert result.input_requests == interim.input_requests
    assert result.request_state is not None
    assert result.request_state != "model-plaintext"
    assert result.request_state.startswith("v1.")
    claims = json.loads(AESGCMRequestStateCodec([_KEY]).unseal(result.request_state))
    assert (claims["m"], claims["t"], claims["s"]) == ("tools/call", "shortcut", "model-plaintext")
    assert interim.request_state == "model-plaintext"  # sealed on a copy; the original is untouched
