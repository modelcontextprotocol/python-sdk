"""The 2026-07-28 multi-round-trip request (MRTR) pattern over tools/call.

Fixture-driven tests pin the client driver's contract on both 2026 matrix cells; the one
wire-level test records JSON-RPC frames over the modern HTTP entry, the only transport with
2026 framing.
"""

from typing import Any

import anyio
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    INVALID_PARAMS,
    INVALID_REQUEST,
    CallToolResult,
    ClientCapabilities,
    CreateMessageRequest,
    CreateMessageRequestParams,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    ErrorData,
    InputRequiredResult,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    ListRootsRequest,
    ListRootsResult,
    Root,
    RootsCapability,
    SamplingCapability,
    SamplingMessage,
    TextContent,
)
from mcp_types.version import LATEST_MODERN_VERSION
from pydantic import FileUrl

from mcp import InputRequiredRoundsExceededError, MCPError
from mcp.client import ClientRequestContext
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer, Server, ServerRequestContext
from mcp.server.context import CallNext, HandlerResult
from mcp.server.extension import Extension
from mcp.shared.exceptions import NoBackChannelError
from mcp.shared.message import SessionMessage
from tests._stamp import Unstamp
from tests._stamp import unstamped as strip_stamp
from tests.interaction._connect import BASE_URL, Connect, mounted_app
from tests.interaction._helpers import RecordingTransport, tool_listing
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio

# Not parseable as JSON or base64: a client that inspected request_state instead of echoing it fails below.
OPAQUE_STATE = 'state!{"not-json'

_NAME_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
}


def _form_request(message: str) -> ElicitRequest:
    """A form-mode elicitation request embeddable in input_requests."""
    return ElicitRequest(params=ElicitRequestFormParams(message=message, requested_schema=_NAME_SCHEMA))


@requirement("mrtr:tools-call:write-once-roundtrip")
async def test_input_required_tool_call_is_auto_fulfilled_and_retried_to_completion(
    connect: Connect, unstamped: Unstamp
) -> None:
    """An input_required tools/call is auto-fulfilled by the client driver and retried to completion.

    The retry is an independent request with a fresh id (spec MUST), and its byte-exact requestState
    echo is the only observable proxy for the MUST NOT inspect/parse/modify rule.
    """
    rounds: list[tuple[types.RequestId | None, str | None]] = []

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name == "login"
        rounds.append((ctx.request_id, params.request_state))
        if params.input_responses is None:
            assert params.request_state is None
            return InputRequiredResult(
                input_requests={"github_login": _form_request("Provide your GitHub username")},
                request_state=OPAQUE_STATE,
            )
        answer = params.input_responses["github_login"]
        assert isinstance(answer, ElicitResult)
        assert answer.action == "accept"
        assert answer.content is not None
        return CallToolResult(content=[TextContent(text=f"hello {answer.content['name']}")])

    server = Server("mrtr", on_list_tools=tool_listing("login"), on_call_tool=call_tool)

    prompts: list[str] = []

    async def answer_login(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        prompts.append(params.message)
        return ElicitResult(action="accept", content={"name": "octocat"})

    async with connect(server, elicitation_callback=answer_login) as client:
        result = await client.call_tool("login", {})

    assert unstamped(result) == snapshot(CallToolResult(content=[TextContent(text="hello octocat")]))
    assert prompts == ["Provide your GitHub username"]
    assert [state for _, state in rounds] == [None, OPAQUE_STATE]
    # Inequality, not pinned values: the id sequence belongs to protocol:request-id:unique.
    assert rounds[0][0] != rounds[1][0]


@requirement("mrtr:request-state-only:retry")
async def test_state_only_input_required_is_retried_with_no_responses_and_echoed_state(
    connect: Connect, unstamped: Unstamp
) -> None:
    """A state-only input_required result is retried with no inputResponses and the state echoed.

    No callbacks are registered: a driver that wrongly dispatched here would error the call.
    """
    resume_token = "resume-token-1"
    request_states: list[str | None] = []

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name == "resume"
        request_states.append(params.request_state)
        # Both rounds carry input_responses=None here, so the rounds are told apart by the state.
        if params.request_state is None:
            return InputRequiredResult(request_state=resume_token)
        assert params.request_state == resume_token
        assert params.input_responses is None
        return CallToolResult(content=[TextContent(text="done")])

    server = Server("resumer", on_list_tools=tool_listing("resume"), on_call_tool=call_tool)

    async with connect(server) as client:
        result = await client.call_tool("resume", {})

    assert unstamped(result) == snapshot(CallToolResult(content=[TextContent(text="done")]))
    assert request_states == [None, resume_token]


@requirement("mrtr:multi-round:complete")
async def test_server_reprompts_across_two_productive_rounds_then_completes(
    connect: Connect, unstamped: Unstamp
) -> None:
    """A server re-prompting with input_required across two productive rounds completes normally.

    Round 1's answer rides forward inside request_state (the spec's stateless-server pattern). Each
    retry carrying only the latest round's responses is SDK-defined (spec silent on accumulate-vs-replace).
    """
    request_states: list[str | None] = []

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name == "enroll"
        request_states.append(params.request_state)
        if params.input_responses is None:
            return InputRequiredResult(input_requests={"first": _form_request("first question")}, request_state="s1")
        if "first" in params.input_responses:
            assert params.request_state == "s1"
            first = params.input_responses["first"]
            assert isinstance(first, ElicitResult)
            assert first.content is not None
            return InputRequiredResult(
                input_requests={"second": _form_request("second question")},
                request_state=f"s2:{first.content['name']}",
            )
        assert set(params.input_responses) == {"second"}
        assert params.request_state is not None and params.request_state.startswith("s2:")
        first_answer = params.request_state.removeprefix("s2:")
        second = params.input_responses["second"]
        assert isinstance(second, ElicitResult)
        assert second.content is not None
        return CallToolResult(content=[TextContent(text=f"{first_answer}+{second.content['name']}")])

    server = Server("reprompter", on_list_tools=tool_listing("enroll"), on_call_tool=call_tool)

    answers = {"first question": "one", "second question": "two"}
    prompts: list[str] = []

    async def answer_by_prompt(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        prompts.append(params.message)
        return ElicitResult(action="accept", content={"name": answers[params.message]})

    async with connect(server, elicitation_callback=answer_by_prompt) as client:
        result = await client.call_tool("enroll", {})

    assert unstamped(result) == snapshot(CallToolResult(content=[TextContent(text="one+two")]))
    assert prompts == ["first question", "second question"]
    assert request_states == [None, "s1", "s2:one"]


@requirement("mrtr:rounds-cap")
async def test_auto_loop_raises_rounds_exceeded_when_the_server_never_completes() -> None:
    """Exceeding input_required_max_rounds raises InputRequiredRoundsExceededError with the cap.

    SDK-defined behaviour (the spec places no bound). Direct in-memory Client because the connect
    factories do not forward input_required_max_rounds; the driver is transport-independent.
    """
    seen_responses: list[set[str] | None] = []

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> InputRequiredResult:
        assert params.name == "never-done"
        seen_responses.append(None if params.input_responses is None else set(params.input_responses))
        return InputRequiredResult(input_requests={"q": _form_request("again")})

    server = Server("bottomless", on_call_tool=call_tool)

    prompts: list[str] = []

    async def answer_again(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        prompts.append(params.message)
        return ElicitResult(action="accept", content={"name": "x"})

    async with Client(
        server, mode=LATEST_MODERN_VERSION, elicitation_callback=answer_again, input_required_max_rounds=2
    ) as client:
        # Raised inside the block: Client.__aexit__ would wrap the error in an ExceptionGroup.
        with pytest.raises(InputRequiredRoundsExceededError) as exc_info:
            await client.call_tool("never-done", {})

    assert exc_info.value.max_rounds == 2
    assert str(exc_info.value) == snapshot(
        "Server returned InputRequiredResult for more than 2 rounds; raise input_required_max_rounds "
        "on the Client, or use client.session.<method>(..., allow_input_required=True) to drive the loop manually."
    )
    # The initial call plus two retries reach the handler; the tripping round's requests are never dispatched.
    assert seen_responses == [None, {"q"}, {"q"}]
    assert prompts == ["again", "again"]


@requirement("protocol:result-type:input-required-not-masked")
async def test_unopted_session_call_with_an_input_required_result_raises_instead_of_returning_it() -> None:
    """A session tools/call without allow_input_required raises instead of returning the interim.

    The interim never surfaces as an empty-content success; the error shape is SDK-defined.
    """
    calls: list[str] = []

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> InputRequiredResult:
        assert params.name == "ask"
        calls.append(params.name)
        return InputRequiredResult(input_requests={"q": _form_request("Need a name")}, request_state="s")

    server = Server("interim-only", on_call_tool=call_tool)

    async with Client(server, mode=LATEST_MODERN_VERSION) as client:
        # Raised inside the block: Client.__aexit__ would wrap the error in an ExceptionGroup.
        with pytest.raises(RuntimeError) as exc_info:
            await client.session.call_tool("ask", {})

    assert str(exc_info.value) == snapshot(
        "Server returned InputRequiredResult; pass allow_input_required=True to receive it "
        "and retry call_tool(..., input_responses=..., request_state=result.request_state)."
    )
    # The handler ran exactly once: no hidden retry preceded the raise.
    assert calls == ["ask"]


@requirement("mrtr:input-required-result:at-least-one-of")
async def test_input_required_result_with_neither_field_cannot_reach_the_client(connect: Connect) -> None:
    """An InputRequiredResult with neither inputRequests nor requestState cannot reach the client.

    The model validator enforces the at-least-one-of MUST; both 2026 dispatchers map the handler's
    ValidationError to the same SDK-defined invalid-params error, so one snapshot serves both cells.
    """

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> InputRequiredResult:
        assert params.name == "bare"
        # Statically legal (both fields default None); raises pydantic's ValidationError here.
        return InputRequiredResult()

    server = Server("malformed-interim", on_call_tool=call_tool)

    async with connect(server) as client:
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("bare", {})

    assert exc_info.value.error == snapshot(
        ErrorData(code=INVALID_PARAMS, message="Invalid request parameters", data="")
    )


@requirement("mrtr:input-responses:key-correspondence")
async def test_multi_request_input_responses_are_keyed_by_the_input_request_keys(
    connect: Connect, unstamped: Unstamp
) -> None:
    """inputResponses on the retry are keyed by the inputRequests keys, each value that key's typed result.

    ElicitResult and ListRootsResult prove the map contract; sampling fidelity belongs to the sampling entries.
    """

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name == "profile"
        if params.input_responses is None:
            # Constructing ListRootsRequest raises no deprecation warning; only push-API calls do.
            return InputRequiredResult(
                input_requests={"github_login": _form_request("Need a name"), "workspace_roots": ListRootsRequest()}
            )
        assert set(params.input_responses) == {"github_login", "workspace_roots"}
        login = params.input_responses["github_login"]
        roots = params.input_responses["workspace_roots"]
        assert isinstance(login, ElicitResult)
        assert isinstance(roots, ListRootsResult)
        assert login.content is not None
        return CallToolResult(content=[TextContent(text=f"{login.content['name']}@{roots.roots[0].uri}")])

    server = Server("profiled", on_list_tools=tool_listing("profile"), on_call_tool=call_tool)

    async def answer_login(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        return ElicitResult(action="accept", content={"name": "octocat"})

    async def answer_roots(context: ClientRequestContext) -> ListRootsResult:
        return ListRootsResult(roots=[Root(uri=FileUrl("file:///workspace"))])

    async with connect(server, elicitation_callback=answer_login, list_roots_callback=answer_roots) as client:
        result = await client.call_tool("profile", {})

    assert unstamped(result) == snapshot(CallToolResult(content=[TextContent(text="octocat@file:///workspace")]))


@requirement("mrtr:input-responses:missing-reprompted")
async def test_retry_missing_a_requested_key_is_reprompted_not_errored(connect: Connect, unstamped: Unstamp) -> None:
    """A retry omitting a requested inputResponses key is re-prompted, not errored (spec SHOULD).

    The re-prompt decision belongs to the test's handler; the SDK obligation pinned is that the partial
    map reaches the handler unmodified. Manual loop: the auto driver answers every requested key.
    """
    seen: list[set[str] | None] = []

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name == "enroll"
        seen.append(None if params.input_responses is None else set(params.input_responses))
        if params.input_responses is None:
            return InputRequiredResult(
                input_requests={"first": _form_request("first question"), "second": _form_request("second question")},
                request_state="r1",
            )
        if "second" not in params.input_responses:
            first = params.input_responses["first"]
            assert isinstance(first, ElicitResult)
            assert first.content is not None
            # Re-prompt for the missing key, threading round 1's answer through the state.
            return InputRequiredResult(
                input_requests={"second": _form_request("second question")},
                request_state=f"r2:{first.content['name']}",
            )
        assert params.request_state is not None and params.request_state.startswith("r2:")
        second = params.input_responses["second"]
        assert isinstance(second, ElicitResult)
        assert second.content is not None
        return CallToolResult(
            content=[TextContent(text=f"{params.request_state.removeprefix('r2:')}+{second.content['name']}")]
        )

    server = Server("reprompting", on_list_tools=tool_listing("enroll"), on_call_tool=call_tool)

    async with connect(server) as client:
        round1 = await client.session.call_tool("enroll", {}, allow_input_required=True)
        assert isinstance(round1, InputRequiredResult)
        assert round1.input_requests is not None
        assert set(round1.input_requests) == {"first", "second"}
        round2 = await client.session.call_tool(
            "enroll",
            {},
            input_responses={"first": ElicitResult(action="accept", content={"name": "one"})},
            request_state=round1.request_state,
            allow_input_required=True,
        )
        assert isinstance(round2, InputRequiredResult)
        assert round2.input_requests is not None
        assert set(round2.input_requests) == {"second"}
        result = await client.session.call_tool(
            "enroll",
            {},
            input_responses={"second": ElicitResult(action="accept", content={"name": "two"})},
            request_state=round2.request_state,
            allow_input_required=True,
        )

    assert unstamped(result) == snapshot(CallToolResult(content=[TextContent(text="one+two")]))
    # The partial map reached the handler as sent, not filtered or rejected.
    assert seen == [None, {"first"}, {"second"}]


@requirement("mrtr:input-responses:unknown-ignored")
async def test_retry_with_an_unrequested_extra_key_is_tolerated_and_the_call_completes(
    connect: Connect, unstamped: Unstamp
) -> None:
    """A retry carrying an unrequested inputResponses key completes normally (spec SHOULD: ignore).

    The ignoring happens in the test's handler; the SDK half pinned is that the stray entry is
    delivered unfiltered. Manual loop: the auto driver only answers the server's own keys.
    """
    seen: list[set[str] | None] = []

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name == "greet"
        seen.append(None if params.input_responses is None else set(params.input_responses))
        if params.input_responses is None:
            return InputRequiredResult(input_requests={"name": _form_request("Need a name")}, request_state="s1")
        # Completes from the requested key alone; the stray entry is deliberately never read.
        answer = params.input_responses["name"]
        assert isinstance(answer, ElicitResult)
        assert answer.content is not None
        return CallToolResult(content=[TextContent(text=f"hello {answer.content['name']}")])

    server = Server("tolerant", on_list_tools=tool_listing("greet"), on_call_tool=call_tool)

    async with connect(server) as client:
        round1 = await client.session.call_tool("greet", {}, allow_input_required=True)
        assert isinstance(round1, InputRequiredResult)
        result = await client.session.call_tool(
            "greet",
            {},
            # Structurally valid value: only the key is unknown, keeping this disjoint from invalid-rejected below.
            input_responses={
                "name": ElicitResult(action="accept", content={"name": "ada"}),
                "stray": ElicitResult(action="accept", content={"name": "noise"}),
            },
            request_state=round1.request_state,
            allow_input_required=True,
        )

    assert unstamped(result) == snapshot(CallToolResult(content=[TextContent(text="hello ada")]))
    assert seen == [None, {"name", "stray"}]


@requirement("mrtr:push-api:loud-fail-2026")
async def test_push_elicit_on_2026_raises_typed_local_error_and_call_still_completes(
    connect: Connect, unstamped: Unstamp
) -> None:
    """A push API call on a 2026 connection raises a typed local error and the call still completes.

    Spec-mandated outcome, era-routed enforcement: every modern dispatch path installs a
    channel-less context by construction, so the gate is "no back-channel", never a send-time
    era check. One push API stands for all four: they share ServerSession.send_request's
    channel selection.
    """
    caught: list[NoBackChannelError] = []

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "ask"
        try:
            await ctx.session.elicit_form("Need a name", _NAME_SCHEMA)
        except NoBackChannelError as exc:
            caught.append(exc)
        return CallToolResult(content=[TextContent(text="fallback")])

    server = Server("push", on_list_tools=tool_listing("ask"), on_call_tool=call_tool)

    # Declares the elicitation capability, isolating the failure to the missing back-channel; never delivered.
    async def never_deliverable(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        raise NotImplementedError

    async with connect(server, elicitation_callback=never_deliverable) as client:
        result = await client.call_tool("ask", {})

    # The failed push did not poison the request: the call completes with the handler's fallback.
    assert unstamped(result) == snapshot(CallToolResult(content=[TextContent(text="fallback")]))
    assert len(caught) == 1
    assert caught[0].method == "elicitation/create"
    assert caught[0].error == snapshot(
        ErrorData(
            code=INVALID_REQUEST,
            message=(
                "Cannot send 'elicitation/create': this transport context has no back-channel "
                "for server-initiated requests."
            ),
        )
    )


@requirement("mrtr:push-api:loud-fail-2026")
async def test_request_scoped_push_elicit_on_in_memory_2026_loud_fails_locally_and_the_call_still_completes() -> None:
    """A request-scoped push elicit on in-memory 2026 loud-fails locally and the call still completes.

    The related id routes the send onto the per-request dispatch channel -- the one leg whose
    channel is otherwise live in-memory -- so this pin proves local provenance: the typed
    NoBackChannelError (never a peer answer) and a callback that never fires. A delivered frame
    would raise NotImplementedError in the callback, surface as a non-NoBackChannelError error,
    escape the narrowed except, and fail the test loudly.
    """
    caught: list[NoBackChannelError] = []

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "ask"
        assert ctx.request_id is not None
        try:
            # The related id routes the send onto the per-request dispatch channel.
            await ctx.session.elicit_form("Need a name", _NAME_SCHEMA, related_request_id=ctx.request_id)
        except NoBackChannelError as exc:
            # Narrow on purpose: a peer-answered MCPError would propagate and fail the test.
            caught.append(exc)
        return CallToolResult(content=[TextContent(text="fallback")])

    server = Server("scoped-push", on_list_tools=tool_listing("ask"), on_call_tool=call_tool)

    # Registering the callback declares the elicitation capability; it must never fire.
    async def never_deliverable(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        raise NotImplementedError

    async with Client(server, mode=LATEST_MODERN_VERSION, elicitation_callback=never_deliverable) as client:
        result = await client.call_tool("ask", {})

    # The failed push did not poison the request: the call completes with the handler's fallback.
    assert strip_stamp(result) == snapshot(CallToolResult(content=[TextContent(text="fallback")]))
    assert len(caught) == 1
    assert caught[0].method == "elicitation/create"
    assert caught[0].error == snapshot(
        ErrorData(
            code=INVALID_REQUEST,
            message=(
                "Cannot send 'elicitation/create': this transport context has no back-channel "
                "for server-initiated requests."
            ),
        )
    )


@requirement("sampling:mrtr:capability:not-declared")
async def test_sampling_request_embedded_for_a_non_sampling_client_is_sent_and_refused_client_side(
    connect: Connect,
) -> None:
    """PINS A KNOWN GAP: an embedded sampling request an undeclared client cannot support is sent anyway.

    The low-level Server's hand-built input_required path has no embed gate (the MCPServer resolver
    path does), so the violation surfaces as the client driver's refusal aborting the call. When the
    low-level gate lands: re-pin to the gated outcome and delete the Divergence.
    """
    calls: list[str] = []

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> InputRequiredResult:
        assert params.name == "gated"
        calls.append(params.name)
        # Precondition: this connection's envelope declared no sampling capability.
        assert not ctx.session.check_client_capability(ClientCapabilities(sampling=SamplingCapability()))
        return InputRequiredResult(
            input_requests={
                "ask-model": CreateMessageRequest(
                    params=CreateMessageRequestParams(
                        messages=[SamplingMessage(role="user", content=TextContent(text="hi"))], max_tokens=8
                    )
                )
            }
        )

    server = Server("ungated-sampling", on_call_tool=call_tool)

    async with connect(server) as client:
        # Raised inside the block: Client.__aexit__ would wrap the error in an ExceptionGroup.
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("gated", {})

    # The refusal comes from the client driver's default sampling callback -- proof the embed was transmitted.
    assert exc_info.value.error == snapshot(ErrorData(code=INVALID_REQUEST, message="Sampling not supported"))
    # The handler ran exactly once: the driver aborts on the refusal, no retry.
    assert calls == ["gated"]


@requirement("roots:mrtr:capability:not-declared")
async def test_roots_request_embedded_for_a_rootless_client_is_sent_and_refused_client_side(
    connect: Connect,
) -> None:
    """PINS A KNOWN GAP: an embedded roots request a rootless client cannot support is sent anyway.

    The low-level Server's hand-built input_required path has no embed gate (the MCPServer resolver
    path does), so the violation surfaces as the client driver's refusal aborting the call. When the
    low-level gate lands: re-pin to the gated outcome and delete the Divergence.
    """
    calls: list[str] = []

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> InputRequiredResult:
        assert params.name == "gated"
        calls.append(params.name)
        # Precondition: this connection's envelope declared no roots capability.
        assert not ctx.session.check_client_capability(ClientCapabilities(roots=RootsCapability()))
        return InputRequiredResult(input_requests={"workspace-roots": ListRootsRequest()})

    server = Server("ungated-roots", on_call_tool=call_tool)

    async with connect(server) as client:
        # Raised inside the block: Client.__aexit__ would wrap the error in an ExceptionGroup.
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("gated", {})

    # The refusal comes from the client driver's default roots callback -- proof the embed was transmitted.
    assert exc_info.value.error == snapshot(ErrorData(code=INVALID_REQUEST, message="List roots not supported"))
    # The handler ran exactly once: the driver aborts on the refusal, no retry.
    assert calls == ["gated"]


@requirement("mrtr:request-state:omitted-when-absent")
async def test_a_retry_carries_no_request_state_when_the_interim_result_had_none(
    connect: Connect, unstamped: Unstamp
) -> None:
    """When the interim input_required result carried no requestState, the retry carries none either.

    Spec MUST NOT: the client never invents a state, so the retried handler sees the field absent
    while the collected inputResponses still arrive.
    """
    request_states: list[str | None] = []

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name == "ask"
        request_states.append(params.request_state)
        if params.input_responses is None:
            return InputRequiredResult(input_requests={"q": _form_request("Need a name")})
        answer = params.input_responses["q"]
        assert isinstance(answer, ElicitResult)
        assert answer.content is not None
        return CallToolResult(content=[TextContent(text=f"ok {answer.content['name']}")])

    server = Server("stateless-asker", on_list_tools=tool_listing("ask"), on_call_tool=call_tool)

    async def answer(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        return ElicitResult(action="accept", content={"name": "ada"})

    async with connect(server, elicitation_callback=answer) as client:
        result = await client.call_tool("ask", {})

    assert unstamped(result) == snapshot(CallToolResult(content=[TextContent(text="ok ada")]))
    assert request_states == [None, None]


@requirement("mrtr:request-state:scoped-to-originating-request")
async def test_parallel_mrtr_calls_keep_request_state_and_responses_isolated() -> None:
    """Parallel MRTR calls keep requestState and inputResponses scoped to their originating request.

    A symmetric rendezvous in the elicitation callback forces both loops mid-flight before either
    retry leaves (spec MUST NOT). Handler capture suffices: every tools/call the client sends is
    delivered to the handler, so the captured rounds are 1:1 with the sent frames.
    """
    rounds: list[tuple[str, str | None, set[str] | None]] = []

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name in ("alpha", "beta")
        name = params.name
        rounds.append(
            (name, params.request_state, None if params.input_responses is None else set(params.input_responses))
        )
        if params.input_responses is None:
            return InputRequiredResult(
                input_requests={f"q-{name}": _form_request(f"for {name}")},
                request_state=f"state-{name}",
            )
        return CallToolResult(content=[TextContent(text=name)])

    server = Server("parallel", on_list_tools=tool_listing("alpha", "beta"), on_call_tool=call_tool)

    round1_seen = {"alpha": anyio.Event(), "beta": anyio.Event()}

    async def answer(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        name = params.message.removeprefix("for ")
        assert name in round1_seen
        # Set own round-1 event before waiting on the other's: deadlock-free, both loops provably mid-flight.
        round1_seen[name].set()
        other = "beta" if name == "alpha" else "alpha"
        with anyio.fail_after(5):
            await round1_seen[other].wait()
        return ElicitResult(action="accept", content={"name": name})

    results: dict[str, CallToolResult] = {}

    with anyio.fail_after(5):
        async with (
            Client(server, mode=LATEST_MODERN_VERSION, elicitation_callback=answer) as client,
            # Last item so it exits first: both calls complete while the client is still open.
            anyio.create_task_group() as task_group,
        ):

            async def call(name: str) -> None:
                results[name] = strip_stamp(await client.call_tool(name, {}))

            task_group.start_soon(call, "alpha")
            task_group.start_soon(call, "beta")

    # The rendezvous guarantees both initial rounds land before either retry; order within a phase is free.
    assert sorted(rounds[:2]) == [("alpha", None, None), ("beta", None, None)]
    # Each retry carries exactly its own call's state and response key -- nothing crossed over.
    assert sorted(rounds[2:]) == [("alpha", "state-alpha", {"q-alpha"}), ("beta", "state-beta", {"q-beta"})]
    assert results == {
        "alpha": CallToolResult(content=[TextContent(text="alpha")]),
        "beta": CallToolResult(content=[TextContent(text="beta")]),
    }


@requirement("protocol:directionality:no-client-responses")
async def test_2026_trace_is_client_requests_and_server_responses_only() -> None:
    """A completed 2026 exchange's trace is client-sent requests and server-sent responses only.

    At 2025-11-25 this same elicitation was a server-initiated request answered by a client response
    -- the maximal legitimate occasion for the forbidden frames (spec MUST NOT, both halves) -- yet
    the trace contains neither. Recorded at the streamable HTTP seam, the only 2026 JSON-RPC framing.
    """

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name == "ask"
        if params.input_responses is None:
            return InputRequiredResult(input_requests={"q": _form_request("Need a name")}, request_state="s1")
        assert set(params.input_responses) == {"q"}
        return CallToolResult(content=[TextContent(text="done")])

    server = Server("one-round", on_list_tools=tool_listing("ask"), on_call_tool=call_tool)

    async def answer(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        return ElicitResult(action="accept", content={"name": "Berlin"})

    with anyio.fail_after(5):
        async with (
            mounted_app(server) as (http, _),
            Client(
                recording := RecordingTransport(streamable_http_client(f"{BASE_URL}/mcp", http_client=http)),
                mode=LATEST_MODERN_VERSION,
                elicitation_callback=answer,
            ) as client,
        ):
            result = await client.call_tool("ask", {})

    assert strip_stamp(result) == snapshot(CallToolResult(content=[TextContent(text="done")]))
    # The client half of the clause: every client-to-server frame is a request.
    assert {type(frame.message) for frame in recording.sent} == {JSONRPCRequest}
    # The server half: no server-to-client frame is a request (a transport exception in the log would also fail).
    received = [frame.message if isinstance(frame, SessionMessage) else frame for frame in recording.received]
    assert {type(message) for message in received} <= {JSONRPCResponse, JSONRPCNotification}
    # Positive control: the elicitation travelled inside an input_required *response*, so the trace is not vacuous.
    results = [message.result for message in received if isinstance(message, JSONRPCResponse)]
    assert [body.get("resultType") for body in results].count("input_required") == 1


# --- unrecognized resultType: a server extension puts an arbitrary tag on the wire ---


@requirement("protocol:result-type:unrecognized-invalid")
async def test_an_unrecognized_result_type_value_is_surfaced_unchanged_instead_of_treated_as_invalid(
    connect: Connect, unstamped: Unstamp
) -> None:
    """PINS A KNOWN GAP: an unrecognized resultType round-trips instead of being treated as invalid (spec MUST).

    The leniency is narrow: the unknown tag survives only because the body also parses as a
    complete core result. When the client starts rejecting unrecognized resultType values:
    re-pin to the typed rejection and delete the Divergence.
    """

    class BogusIssuer(Extension):
        identifier = "com.example/bogus"

        async def intercept_tool_call(
            self, params: types.CallToolRequestParams, ctx: ServerRequestContext[Any, Any], call_next: CallNext
        ) -> HandlerResult:
            assert params.name == "probe"
            # "bogus" is in no core or extension vocabulary -- exactly the value the MUST addresses.
            return {"resultType": "bogus", "content": [{"type": "text", "text": "still here"}]}

    server = MCPServer("bogus-issuer", extensions=[BogusIssuer()])

    @server.tool()
    def probe() -> CallToolResult:
        """Probe the unrecognized-tag path."""
        raise NotImplementedError  # the server extension answers before the tool runs

    async with connect(server) as client:
        result = await client.call_tool("probe", {})

    # The divergent observable: the unrecognized discriminator survives unchanged, never a rejection.
    assert result.result_type == "bogus"
    assert unstamped(result) == snapshot(CallToolResult(content=[TextContent(text="still here")], result_type="bogus"))
