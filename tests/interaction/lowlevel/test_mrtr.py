"""The 2026-07-28 multi-round-trip request (MRTR) core pattern over tools/call.

A tool that needs more input answers with an ``input_required`` result; the client driver fulfils
the embedded requests through its registered callbacks and retries the original call carrying the
collected ``inputResponses`` and the echoed opaque ``requestState``. The fixture-driven tests pin
the driver's user-facing contract on both 2026 matrix cells; the wire-level tests record JSON-RPC
frames at the client transport seam over the modern streamable HTTP entry -- the only transport
serving 2026 JSON-RPC frames -- because retry ids and serialized key presence are protocol facts
invisible to API callers (the in-memory 2026 path has no JSON-RPC framing at all). One test
speaks the raw 2026 dialect against the mounted modern entry, the only seam where malformed
params can originate. The directionality-edge tests pin the 2026 boundary itself: the retired
push APIs fail loudly (except the in-memory request-scoped leg, a pinned divergence), embedded
input requests cross un-gated to the refusing client driver, and a completed exchange's trace
carries client requests and server responses only.
"""

from typing import Any

import anyio
import mcp_types as types
import pytest
from inline_snapshot import snapshot
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION_META_KEY,
    CallToolResult,
    ClientCapabilities,
    CreateMessageRequest,
    CreateMessageRequestParams,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    ErrorData,
    InputRequiredResult,
    JSONRPCError,
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
from mcp.server import Server, ServerRequestContext
from mcp.shared.exceptions import NoBackChannelError
from mcp.shared.message import SessionMessage
from tests.interaction._connect import BASE_URL, Connect, base_headers, mounted_app
from tests.interaction._helpers import RecordingTransport
from tests.interaction._requirements import requirement

pytestmark = pytest.mark.anyio

# Deliberately not parseable as JSON or base64: a client that inspected or normalized
# request_state instead of echoing it byte-exact would fail the equality assertions below.
OPAQUE_STATE = 'state!{"not-json'

_NAME_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
}


def _form_request(message: str) -> ElicitRequest:
    """A form-mode elicitation request embeddable in an InputRequiredResult's input_requests."""
    return ElicitRequest(params=ElicitRequestFormParams(message=message, requested_schema=_NAME_SCHEMA))


def _login_server(request_states: list[str | None]) -> Server:
    """The two-round write-once server the roundtrip pair shares.

    Round 1 answers with one embedded form request plus the opaque state; round 2 asserts the
    byte-exact echo and completes with the elicited name. Every round's request_state is appended
    to `request_states`.
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        # Live (not NotImplementedError): the client's output-schema cache refresh invokes
        # tools/list right after the first tools/call result.
        return types.ListToolsResult(tools=[types.Tool(name="login", input_schema={"type": "object"})])

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name == "login"
        request_states.append(params.request_state)
        if params.input_responses is None:
            assert params.request_state is None
            return InputRequiredResult(
                input_requests={"github_login": _form_request("Provide your GitHub username")},
                request_state=OPAQUE_STATE,
            )
        assert params.request_state == OPAQUE_STATE
        answer = params.input_responses["github_login"]
        assert isinstance(answer, ElicitResult)
        assert answer.action == "accept"
        assert answer.content is not None
        return CallToolResult(content=[TextContent(text=f"hello {answer.content['name']}")])

    return Server("mrtr", on_list_tools=list_tools, on_call_tool=call_tool)


@requirement("mrtr:tools-call:write-once-roundtrip")
async def test_input_required_tool_call_is_auto_fulfilled_and_retried_to_completion(connect: Connect) -> None:
    """An input_required tools/call is fulfilled by the client driver and retried to completion.

    The registered callback answers the embedded form request and the retried call completes as a
    plain CallToolResult (spec basic workflow). The byte-exact requestState echo (spec MUST) is
    pinned by equality against a deliberately non-parseable literal -- the only observable proxy
    for the MUST NOT inspect/parse/modify rule; the retry's frame-level obligations are pinned by
    the wire test below.
    """
    request_states: list[str | None] = []
    server = _login_server(request_states)

    prompts: list[str] = []

    async def answer_login(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        prompts.append(params.message)
        return ElicitResult(action="accept", content={"name": "octocat"})

    async with connect(server, elicitation_callback=answer_login) as client:
        result = await client.call_tool("login", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="hello octocat")]))
    assert prompts == ["Provide your GitHub username"]
    # Exactly the initial round and one retry, the retry echoing the module constant byte-exact.
    assert request_states == [None, OPAQUE_STATE]


@requirement("mrtr:request-state-only:retry")
async def test_state_only_input_required_is_retried_with_no_responses_and_echoed_state(connect: Connect) -> None:
    """A state-only input_required result is retried with no inputResponses and the state echoed.

    There is nothing to dispatch, so no callbacks are registered -- a driver that wrongly
    dispatched on this branch would error the call instead of completing it. The spec's "MAY
    retry the original request immediately" is permission: the SDK paces the retry with an
    internal 50 ms backoff, its own pacing choice rather than a divergence, and the test neither
    adds sleeps nor asserts elapsed time.
    """
    resume_token = "resume-token-1"
    request_states: list[str | None] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        # Live (not NotImplementedError): the client's output-schema cache refresh invokes
        # tools/list right after the first tools/call result.
        return types.ListToolsResult(tools=[types.Tool(name="resume", input_schema={"type": "object"})])

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

    server = Server("resumer", on_list_tools=list_tools, on_call_tool=call_tool)

    async with connect(server) as client:
        result = await client.call_tool("resume", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="done")]))
    # Exactly one retry, echoing the token the server minted.
    assert request_states == [None, resume_token]


@requirement("mrtr:multi-round:complete")
async def test_server_reprompts_across_two_productive_rounds_then_completes(connect: Connect) -> None:
    """A server may answer the same call with input_required on successive attempts (spec MAY);
    after two productive rounds the retried call completes normally.

    Round 1's answer is threaded through ``request_state`` -- the spec's own stateless-server
    pattern -- so the terminal snapshot proves both rounds' data reached the server. Echoing the
    *latest* round's state on each retry is spec-mandated (the retry echoes the exact value of the
    result being retried); round 3 carrying only round 3's answers is SDK-defined -- the driver
    rebuilds responses per round, and the spec is silent on accumulate-vs-replace.
    """
    request_states: list[str | None] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        # Live (not NotImplementedError): the client's output-schema cache refresh invokes
        # tools/list right after the first tools/call result.
        return types.ListToolsResult(tools=[types.Tool(name="enroll", input_schema={"type": "object"})])

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
            # The stateless-server pattern: round 1's answer rides forward inside the new state.
            return InputRequiredResult(
                input_requests={"second": _form_request("second question")},
                request_state=f"s2:{first.content['name']}",
            )
        # Only the current round's answers ride the retry (SDK-defined; see docstring).
        assert set(params.input_responses) == {"second"}
        assert params.request_state is not None and params.request_state.startswith("s2:")
        first_answer = params.request_state.removeprefix("s2:")
        second = params.input_responses["second"]
        assert isinstance(second, ElicitResult)
        assert second.content is not None
        return CallToolResult(content=[TextContent(text=f"{first_answer}+{second.content['name']}")])

    server = Server("reprompter", on_list_tools=list_tools, on_call_tool=call_tool)

    answers = {"first question": "one", "second question": "two"}
    prompts: list[str] = []

    async def answer_by_prompt(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        prompts.append(params.message)
        return ElicitResult(action="accept", content={"name": answers[params.message]})

    async with connect(server, elicitation_callback=answer_by_prompt) as client:
        result = await client.call_tool("enroll", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="one+two")]))
    assert prompts == ["first question", "second question"]
    # Three rounds, each retry echoing the latest round's state (spec) -- round 1's answer
    # visible inside round 2's threaded state.
    assert request_states == [None, "s1", "s2:one"]


@requirement("mrtr:rounds-cap")
async def test_auto_loop_raises_rounds_exceeded_when_the_server_never_completes() -> None:
    """The driver's retry loop is bounded: a server that keeps answering input_required past the
    configured ``input_required_max_rounds`` raises ``InputRequiredRoundsExceededError`` carrying
    the configured cap. SDK-defined contract (the spec places no bound; servers MUST NOT assume
    clients retry at all).

    Constructed directly on the in-memory 2026 cell rather than via the connect fixture because
    the factories do not forward ``input_required_max_rounds``; the driver is a
    transport-independent pure function, so the knob's effect is fully observable here. Every
    round carries ``input_requests``, so the state-only backoff branch never runs.
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
        # Inside the connect block: unwinding through Client.__aexit__ would wrap the error in
        # ExceptionGroups (task-group teardown), and pytest.raises would miss the bare type.
        with pytest.raises(InputRequiredRoundsExceededError) as exc_info:
            await client.call_tool("never-done", {})

    # The configured cap comes back on the error; the message is the SDK's own guidance text.
    assert exc_info.value.max_rounds == 2
    assert str(exc_info.value) == snapshot(
        "Server returned InputRequiredResult for more than 2 rounds; raise input_required_max_rounds "
        "on the Client, or use client.session.<method>(..., allow_input_required=True) to drive the loop manually."
    )
    # SDK-defined loop accounting: the initial call plus two retries reach the handler (round 3's
    # input_required trips the cap), and the tripping round's requests are never dispatched.
    assert seen_responses == [None, {"q"}, {"q"}]
    assert prompts == ["again", "again"]


@requirement("mrtr:input-required-result:at-least-one-of")
async def test_input_required_result_with_neither_field_cannot_reach_the_client(connect: Connect) -> None:
    """A handler-built InputRequiredResult with neither inputRequests nor requestState cannot
    cross to the client: construction fails (the spec's at-least-one-of MUST, enforced by the
    model validator) and the call surfaces a JSON-RPC error, never a malformed interim result.

    The error shape is SDK-defined -- both 2026 dispatchers map the handler's ValidationError to
    the same invalid-params ErrorData, so one snapshot serves both cells; the spec mandates no
    code for a server-side construction bug (its 'appropriate error code' SHOULD addresses
    client-sent malformed data).
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
async def test_multi_request_input_responses_are_keyed_by_the_input_request_keys(connect: Connect) -> None:
    """inputResponses on the retry are keyed by the inputRequests keys, each value the client's
    typed result for that key's request (spec: keys correspond; values are per-request results).

    Two of the three response types (ElicitResult, ListRootsResult) prove the map contract;
    sampling-value fidelity belongs to the sampling MRTR entries. Both payloads travel back
    through the protocol into one terminal result.
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        # Live (not NotImplementedError): the client's output-schema cache refresh invokes
        # tools/list right after the first tools/call result.
        return types.ListToolsResult(tools=[types.Tool(name="profile", input_schema={"type": "object"})])

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
        # Per-key type routing: each key's value is the result type its request asked for.
        assert isinstance(login, ElicitResult)
        assert isinstance(roots, ListRootsResult)
        assert login.content is not None
        return CallToolResult(content=[TextContent(text=f"{login.content['name']}@{roots.roots[0].uri}")])

    server = Server("profiled", on_list_tools=list_tools, on_call_tool=call_tool)

    async def answer_login(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        return ElicitResult(action="accept", content={"name": "octocat"})

    async def answer_roots(context: ClientRequestContext) -> ListRootsResult:
        return ListRootsResult(roots=[Root(uri=FileUrl("file:///workspace"))])

    async with connect(server, elicitation_callback=answer_login, list_roots_callback=answer_roots) as client:
        result = await client.call_tool("profile", {})

    assert result == snapshot(CallToolResult(content=[TextContent(text="octocat@file:///workspace")]))


@requirement("mrtr:push-api:loud-fail-2026")
async def test_push_elicit_on_2026_raises_typed_local_error_and_call_still_completes(connect: Connect) -> None:
    """A handler calling the retired push API on a 2026 connection gets a typed, catchable local
    error before anything reaches the client, and the originating call still completes normally.

    The outcome is spec-mandated (the previous server-initiated request pattern is no longer
    supported) but the enforcement at this pin is incidental -- the gate is "this transport context
    has no back-channel", not "wrong era"; the request-scoped half of that gap is pinned by the
    divergence test below. One push API stands for all four: elicit_form / elicit_url /
    create_message / list_roots share the single channel-selection point in
    ServerSession.send_request, and the deprecated siblings would add warning scaffolding only to
    re-prove the same gate.
    """
    caught: list[NoBackChannelError] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        # Live (not NotImplementedError): the client's output-schema cache refresh invokes
        # tools/list right after the first tools/call result.
        return types.ListToolsResult(tools=[types.Tool(name="ask", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "ask"
        try:
            await ctx.session.elicit_form("Need a name", _NAME_SCHEMA)
        except NoBackChannelError as exc:
            caught.append(exc)
        return CallToolResult(content=[TextContent(text="fallback")])

    server = Server("push", on_list_tools=list_tools, on_call_tool=call_tool)

    # Registered so the client declares the elicitation capability in the per-request envelope,
    # isolating the failure to the missing back-channel rather than to capability gating; the
    # body is itself the never-delivered assertion.
    async def never_deliverable(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        raise NotImplementedError

    async with connect(server, elicitation_callback=never_deliverable) as client:
        result = await client.call_tool("ask", {})

    # The failed push did not poison the request: the call completes with the handler's fallback.
    assert result == snapshot(CallToolResult(content=[TextContent(text="fallback")]))
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
async def test_request_scoped_push_elicit_on_in_memory_2026_transmits_the_forbidden_frame() -> None:
    """PINS A KNOWN GAP: the 2026 prohibition on server-initiated requests is enforced
    per-transport by the missing back-channel, and the in-memory pair's request-scoped channel
    still has one -- a push elicit carrying related_request_id transmits the forbidden
    elicitation/create, and the failure comes back from the client's 2026 version gate instead of
    arising locally. See the requirement's divergence; when an era-aware send gate lands, re-pin
    this to the local NoBackChannelError the test above observes and delete the divergence.

    Direct in-memory client, no fixture: the behaviour is transport-split -- over the modern HTTP
    entry this same leg loud-fails locally -- so one fixture body cannot pin both cells.
    """
    caught: list[MCPError] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        # Live (not NotImplementedError): the client's output-schema cache refresh invokes
        # tools/list right after the first tools/call result.
        return types.ListToolsResult(tools=[types.Tool(name="ask", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "ask"
        assert ctx.request_id is not None
        try:
            # The related id routes the send onto the per-request dispatch channel.
            await ctx.session.elicit_form("Need a name", _NAME_SCHEMA, related_request_id=ctx.request_id)
        except MCPError as exc:
            # MCPError, not NoBackChannelError: nothing is raised locally on this path -- the
            # failure is the peer's typed answer. Post-fix, the local NoBackChannelError (an
            # MCPError subclass) lands here too and fails on the snapshot, a clean re-pin signal.
            caught.append(exc)
        return CallToolResult(content=[TextContent(text="fallback")])

    server = Server("scoped-push", on_list_tools=list_tools, on_call_tool=call_tool)

    # Registered so the client declares the elicitation capability (mirroring the test above);
    # the body is itself the never-delivered assertion.
    async def never_deliverable(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        raise NotImplementedError

    async with Client(server, mode=LATEST_MODERN_VERSION, elicitation_callback=never_deliverable) as client:
        result = await client.call_tool("ask", {})

    # The connection survives the rejected frame.
    assert result == snapshot(CallToolResult(content=[TextContent(text="fallback")]))
    assert len(caught) == 1
    # The transmission proof, byte-exact: only the client version gate's KeyError branch
    # (SERVER_REQUESTS has zero 2026-07-28 entries) answers with data=<method> -- it runs strictly
    # before callback dispatch, so this snapshot also proves the callback layer was never reached
    # (a delivered-then-failing callback surfaces a different error shape).
    assert caught[0].error == snapshot(
        ErrorData(code=METHOD_NOT_FOUND, message="Method not found", data="elicitation/create")
    )


@requirement("sampling:mrtr:capability:not-declared")
async def test_sampling_request_embedded_for_a_non_sampling_client_is_sent_and_refused_client_side(
    connect: Connect,
) -> None:
    """PINS A KNOWN GAP: the spec forbids embedding an inputRequests entry the client's declared
    capabilities do not support, but the SDK has no embed gate -- the sampling/createMessage is
    transmitted as-is and the violation surfaces as the client driver's refusal aborting the call.
    See the requirement's divergence; when the server-side gate lands (expected: the originating
    request fails with -32021 MissingRequiredClientCapability or the embed is rejected at
    construction), re-pin.
    """
    calls: list[str] = []

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> InputRequiredResult:
        assert params.name == "gated"
        calls.append(params.name)
        # The precondition, through the same public surface a conformant gate would use: this
        # connection's envelope declared no sampling capability.
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

    # Default client, no callbacks: precisely the client that declared no capabilities.
    async with connect(server) as client:
        # Inside the connect block: unwinding through Client.__aexit__ would wrap the error in
        # ExceptionGroups (task-group teardown), and pytest.raises would miss the bare type.
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("gated", {})

    # The SDK-authored refusal originates in the client driver's default sampling callback --
    # possible only because the server transmitted the embed a conformant server MUST NOT send.
    assert exc_info.value.error == snapshot(ErrorData(code=INVALID_REQUEST, message="Sampling not supported"))
    # The handler ran exactly once: the driver aborts on the refusal, no retry.
    assert calls == ["gated"]


@requirement("roots:mrtr:capability:not-declared")
async def test_roots_request_embedded_for_a_rootless_client_is_sent_and_refused_client_side(
    connect: Connect,
) -> None:
    """PINS A KNOWN GAP: the spec forbids embedding an inputRequests entry the client's declared
    capabilities do not support, but the SDK has no embed gate -- the roots/list is transmitted
    as-is and the violation surfaces as the client driver's refusal aborting the call. See the
    requirement's divergence; when the server-side gate lands (expected: the originating request
    fails with -32021 MissingRequiredClientCapability or the embed is rejected at construction),
    re-pin.
    """
    calls: list[str] = []

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> InputRequiredResult:
        assert params.name == "gated"
        calls.append(params.name)
        # The precondition, through the same public surface a conformant gate would use: this
        # connection's envelope declared no roots capability.
        assert not ctx.session.check_client_capability(ClientCapabilities(roots=RootsCapability()))
        return InputRequiredResult(input_requests={"workspace-roots": ListRootsRequest()})

    server = Server("ungated-roots", on_call_tool=call_tool)

    # Default client, no callbacks: precisely the client that declared no capabilities.
    async with connect(server) as client:
        # Inside the connect block: unwinding through Client.__aexit__ would wrap the error in
        # ExceptionGroups (task-group teardown), and pytest.raises would miss the bare type.
        with pytest.raises(MCPError) as exc_info:
            await client.call_tool("gated", {})

    # The SDK-authored refusal originates in the client driver's default roots callback --
    # possible only because the server transmitted the embed a conformant server MUST NOT send.
    assert exc_info.value.error == snapshot(ErrorData(code=INVALID_REQUEST, message="List roots not supported"))
    # The handler ran exactly once: the driver aborts on the refusal, no retry.
    assert calls == ["gated"]


# --- wire-level: the modern HTTP entry is the only 2026 framing seam ---


@requirement("mrtr:tools-call:write-once-roundtrip")
async def test_mrtr_retry_frame_carries_fresh_id_and_byte_exact_request_state() -> None:
    """The MRTR retry frame carries a fresh JSON-RPC id and the requestState key serialized byte-exact.

    Asserted at the client transport seam because the retry's id (spec MUST: initial request and
    retry are independent requests) and the serialized requestState key are invisible to API
    callers; the modern HTTP entry is the only transport serving 2026 JSON-RPC frames at this pin
    (the in-memory 2026 path has no framing). The recorded round-1 response also exhibits one
    compliant input_required interim -- enforcement of the at-least-one-of MUST is owned by its
    own entry -- and this test is the emission complement of the key-omission test below.
    """
    server = _login_server([])

    async def answer_login(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        return ElicitResult(action="accept", content={"name": "octocat"})

    with anyio.fail_after(5):
        # One combined async-with, the recorder bound via := -- a separately nested `async with`
        # line mis-traces its exit arcs under branch coverage on 3.11+.
        async with (
            mounted_app(server) as (http, _),
            Client(
                recording := RecordingTransport(streamable_http_client(f"{BASE_URL}/mcp", http_client=http)),
                mode=LATEST_MODERN_VERSION,
                elicitation_callback=answer_login,
            ) as client,
        ):
            await client.call_tool("login", {})

    # Filtered to tools/call: the client's schema-cache refresh also puts a tools/list on the wire.
    calls = [
        message.message
        for message in recording.sent
        if isinstance(message.message, JSONRPCRequest) and message.message.method == "tools/call"
    ]
    assert len(calls) == 2
    first, retry = calls
    # Fresh id on the retry, asserted as inequality: the id *sequence* belongs to
    # protocol:request-id:unique, and pinned values would couple to the refresh-frame count.
    assert first.id is not None
    assert retry.id is not None
    assert retry.id != first.id
    assert first.params is not None
    assert "requestState" not in first.params
    assert "inputResponses" not in first.params
    assert retry.params is not None
    assert retry.params["requestState"] == OPAQUE_STATE
    assert retry.params["inputResponses"]["github_login"]["action"] == "accept"
    # The interim travelled as a *result*, matched to the initial request by its id (the received
    # log also carries the retry's response and the tools/list response).
    interim = next(
        message.message
        for message in recording.received
        if isinstance(message, SessionMessage)
        and isinstance(message.message, JSONRPCResponse)
        and message.message.id == first.id
    )
    assert interim.result["resultType"] == "input_required"
    assert "requestState" in interim.result


@requirement("mrtr:request-state:omitted-when-absent")
async def test_retry_omits_the_request_state_key_when_the_server_sent_none() -> None:
    """When the server's input_required carried no requestState, the retry omits the key entirely.

    The spec MUST NOT include one in the retry is wire-pinned: typed request_state None and
    key-absence are indistinguishable in-memory, so only the serialized retry frame can prove the
    omission. The fresh-id test above proves the same serializer emits the key when the server
    sent one, guarding this absence assertion against vacuity.
    """
    request_states: list[str | None] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        # Live (not NotImplementedError): the client's output-schema cache refresh invokes
        # tools/list right after the first tools/call result.
        return types.ListToolsResult(tools=[types.Tool(name="ask", input_schema={"type": "object"})])

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name == "ask"
        request_states.append(params.request_state)
        if params.input_responses is None:
            return InputRequiredResult(input_requests={"q": _form_request("Need a name")})
        assert params.request_state is None
        return CallToolResult(content=[TextContent(text="ok")])

    server = Server("stateless-asker", on_list_tools=list_tools, on_call_tool=call_tool)

    async def answer(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        return ElicitResult(action="accept", content={"name": "ada"})

    with anyio.fail_after(5):
        async with (
            mounted_app(server) as (http, _),
            Client(
                recording := RecordingTransport(streamable_http_client(f"{BASE_URL}/mcp", http_client=http)),
                mode=LATEST_MODERN_VERSION,
                elicitation_callback=answer,
            ) as client,
        ):
            await client.call_tool("ask", {})

    calls = [
        message.message
        for message in recording.sent
        if isinstance(message.message, JSONRPCRequest) and message.message.method == "tools/call"
    ]
    assert len(calls) == 2
    retry = calls[1]
    assert retry.params is not None
    # The MUST NOT itself: no requestState key on the serialized retry...
    assert "requestState" not in retry.params
    # ...on a frame that is otherwise loaded -- the absence is specific, not a bare frame.
    assert "inputResponses" in retry.params
    # Handler-side corroboration of what the frame shows.
    assert request_states == [None, None]


@requirement("mrtr:request-state:scoped-to-originating-request")
async def test_parallel_mrtr_calls_keep_request_state_and_responses_isolated() -> None:
    """Parallel MRTR calls keep requestState and inputResponses scoped to their originating request.

    A symmetric rendezvous in the elicitation callback (each call sets its own round-1 event, then
    waits on the other's) forces both loops to be simultaneously mid-flight -- interim results
    received, neither retry sent -- before either retry leaves, so the spec scenario ("any other
    request that the client may be sending in parallel") provably occurs; the exhaustive scan over
    every recorded tools/call frame is the MUST NOT's proof that neither call's fields leak into
    the other's.
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        # Live (not NotImplementedError): the client's output-schema cache refresh invokes
        # tools/list right after the first tools/call result.
        return types.ListToolsResult(
            tools=[
                types.Tool(name="alpha", input_schema={"type": "object"}),
                types.Tool(name="beta", input_schema={"type": "object"}),
            ]
        )

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name in ("alpha", "beta")
        name = params.name
        if params.input_responses is None:
            return InputRequiredResult(
                input_requests={f"q-{name}": _form_request(f"for {name}")},
                request_state=f"state-{name}",
            )
        # Each retry carries its own call's state -- the handler-side half of the isolation claim.
        assert params.request_state == f"state-{name}"
        return CallToolResult(content=[TextContent(text=name)])

    server = Server("parallel", on_list_tools=list_tools, on_call_tool=call_tool)

    round1_seen = {"alpha": anyio.Event(), "beta": anyio.Event()}

    async def answer(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        name = params.message.removeprefix("for ")
        assert name in round1_seen
        # Symmetric rendezvous: set own round-1 event before waiting on the other's -- deadlock-free
        # by set-before-wait, and both loops are provably mid-flight before either retry leaves.
        round1_seen[name].set()
        other = "beta" if name == "alpha" else "alpha"
        with anyio.fail_after(5):
            await round1_seen[other].wait()
        return ElicitResult(action="accept", content={"name": name})

    results: dict[str, CallToolResult] = {}

    with anyio.fail_after(5):
        async with (
            mounted_app(server) as (http, _),
            Client(
                recording := RecordingTransport(streamable_http_client(f"{BASE_URL}/mcp", http_client=http)),
                mode=LATEST_MODERN_VERSION,
                elicitation_callback=answer,
            ) as client,
            # Last item so it exits first: both calls complete while the client is still open.
            anyio.create_task_group() as task_group,
        ):

            async def call(name: str) -> None:
                results[name] = await client.call_tool(name, {})

            task_group.start_soon(call, "alpha")
            task_group.start_soon(call, "beta")

    frames = [
        message.message
        for message in recording.sent
        if isinstance(message.message, JSONRPCRequest) and message.message.method == "tools/call"
    ]
    by_name: dict[str, list[dict[str, Any]]] = {"alpha": [], "beta": []}
    for frame in frames:
        assert frame.params is not None
        by_name[frame.params["name"]].append(frame.params)
    for name, sent_params in by_name.items():
        assert len(sent_params) == 2
        initial, retry = sent_params
        assert "requestState" not in initial
        assert "inputResponses" not in initial
        assert retry["requestState"] == f"state-{name}"
        assert set(retry["inputResponses"]) == {f"q-{name}"}
    # The exhaustive negative (spec MUST NOT): no recorded tools/call frame anywhere carries the
    # other call's state or responses.
    for params in (frame.params for frame in frames):
        assert params is not None
        other = "beta" if params["name"] == "alpha" else "alpha"
        assert params.get("requestState") in (None, f"state-{params['name']}")
        assert f"q-{other}" not in params.get("inputResponses", {})
    assert results == {
        "alpha": CallToolResult(content=[TextContent(text="alpha")]),
        "beta": CallToolResult(content=[TextContent(text="beta")]),
    }


@requirement("protocol:directionality:no-client-responses")
async def test_2026_trace_is_client_requests_and_server_responses_only() -> None:
    """A completed 2026 exchange's wire trace is client-sent requests and server-sent responses
    only -- zero server-initiated requests, zero client-sent responses (spec MUST NOT, both halves).

    The scenario is the maximal legitimate occasion for the forbidden frames: at 2025-11-25 this
    same elicitation was a server-initiated request answered by a client JSON-RPC response; here it
    rides the MRTR loop to completion and the trace still contains neither. The full trace shape is
    snapshotted (the trailing tools/list is the client's implicit output-schema refresh) so any
    future frame reorder fails consciously rather than silently narrowing the claim.
    """
    elicited: list[str] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        # Live (not NotImplementedError): the client's output-schema cache refresh invokes
        # tools/list right after the first tools/call result.
        return types.ListToolsResult(tools=[types.Tool(name="ask", input_schema={"type": "object"})])

    async def call_tool(
        ctx: ServerRequestContext, params: types.CallToolRequestParams
    ) -> CallToolResult | InputRequiredResult:
        assert params.name == "ask"
        if params.input_responses is None:
            return InputRequiredResult(input_requests={"q": _form_request("Need a name")}, request_state="s1")
        answer = params.input_responses["q"]
        assert isinstance(answer, ElicitResult)
        assert answer.content is not None
        return CallToolResult(content=[TextContent(text=f"done:{answer.content['name']}:{params.request_state}")])

    server = Server("one-round", on_list_tools=list_tools, on_call_tool=call_tool)

    async def answer(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        elicited.append(params.message)
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

    # Non-vacuity: the elicitation genuinely happened and the round trip completed through it.
    assert result == snapshot(CallToolResult(content=[TextContent(text="done:Berlin:s1")]))
    assert elicited == ["Need a name"]
    # Load-bearing, not decoration: a transport exception silently filtered out below would fake
    # the pass, so prove the received log holds messages only before narrowing to them.
    received_messages = [message for message in recording.received if isinstance(message, SessionMessage)]
    assert received_messages == recording.received
    # The client half of the clause: every client-to-server frame is a request.
    assert [
        (type(message.message).__name__, getattr(message.message, "method", None)) for message in recording.sent
    ] == snapshot(
        [("JSONRPCRequest", "tools/call"), ("JSONRPCRequest", "tools/call"), ("JSONRPCRequest", "tools/list")]
    )
    # The server half of the same sentence: every server-to-client frame is a response.
    assert [type(message.message).__name__ for message in received_messages] == snapshot(
        ["JSONRPCResponse", "JSONRPCResponse", "JSONRPCResponse"]
    )
    # Every server frame ANSWERS a client request: response ids pair the sent request ids in
    # order. The shape snapshots above prove these two isinstance filters drop nothing.
    requests = [message.message for message in recording.sent if isinstance(message.message, JSONRPCRequest)]
    responses = [message.message for message in received_messages if isinstance(message.message, JSONRPCResponse)]
    assert [response.id for response in responses] == [request.id for request in requests]


# --- raw 2026 dialect: malformed params can only originate from a scripted client ---


def _modern_headers(*, method: str, name: str) -> dict[str, str]:
    """Headers for a raw 2026-07-28 tools/call POST: the Accept/Content-Type baseline plus the
    routing and advisory headers a modern client always sends (the test_hosting_http_modern.py
    dialect, minus the optional-name branch this file's one caller never takes)."""
    return base_headers() | {"mcp-protocol-version": LATEST_MODERN_VERSION, "mcp-method": method, "mcp-name": name}


def _meta_envelope() -> dict[str, object]:
    """The three-key per-request ``_meta`` envelope a 2026-07-28 client stamps on every request."""
    return {
        PROTOCOL_VERSION_META_KEY: LATEST_MODERN_VERSION,
        CLIENT_INFO_META_KEY: {"name": "raw", "version": "0.0.0"},
        CLIENT_CAPABILITIES_META_KEY: {},
    }


@requirement("mrtr:input-responses:invalid-rejected")
async def test_retry_with_malformed_input_responses_is_rejected_with_invalid_params() -> None:
    """A retry whose inputResponses do not parse as a valid InputResponses object is rejected
    with invalid params before the handler runs (spec SHOULD: validate; the structural arm only --
    no requestedSchema re-validation happens on this path, and the spec asks for none).

    Raw httpx against the mounted modern entry because the violation is unproducible above this
    seam: the typed API rejects garbage inputResponses at construction, and the memory-streams
    scripted-peer pattern cannot serve 2026 requests (the stream loop's init gate rejects
    envelope-bearing requests). The cold retry is licensed by the spec's own framing -- the
    initial request and the retry are completely independent.
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        raise NotImplementedError

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        # Params validation precedes dispatch, so the malformed retry must never reach this body.
        raise NotImplementedError

    server = Server("never-dispatches", on_list_tools=list_tools, on_call_tool=call_tool)

    with anyio.fail_after(5):
        async with mounted_app(server) as (http, _):
            response = await http.post(
                f"{BASE_URL}/mcp",
                headers=_modern_headers(method="tools/call", name="never-runs"),
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {
                        "name": "never-runs",
                        "inputResponses": {"k": {"not": "a result"}},
                        "_meta": _meta_envelope(),
                    },
                },
            )

    error = JSONRPCError.model_validate(response.json())
    assert error.error == snapshot(ErrorData(code=INVALID_PARAMS, message="Invalid request parameters", data=""))
