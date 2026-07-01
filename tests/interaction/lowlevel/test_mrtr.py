"""The 2026-07-28 multi-round-trip request (MRTR) pattern over tools/call.

Fixture-driven tests pin the client driver's contract on both 2026 matrix cells; wire-level tests
record JSON-RPC frames over the modern HTTP entry, the only transport with 2026 framing; raw-dialect
and scripted-peer tests cover params and result bodies the typed API cannot produce.
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
    Implementation,
    InitializeResult,
    InputRequiredResult,
    JSONRPCError,
    JSONRPCNotification,
    JSONRPCRequest,
    JSONRPCResponse,
    ListRootsRequest,
    ListRootsResult,
    Root,
    RootsCapability,
    SamplingCapability,
    SamplingMessage,
    ServerCapabilities,
    TextContent,
)
from mcp_types.version import LATEST_MODERN_VERSION
from pydantic import FileUrl

from mcp import InputRequiredRoundsExceededError, MCPError
from mcp.client import ClientRequestContext, ClientSession
from mcp.client.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server import MCPServer, Server, ServerRequestContext
from mcp.server.context import CallNext, HandlerResult
from mcp.server.extension import Extension
from mcp.shared.exceptions import NoBackChannelError
from mcp.shared.memory import MessageStream, create_client_server_memory_streams
from mcp.shared.message import SessionMessage
from tests.interaction._connect import BASE_URL, Connect, base_headers, mounted_app
from tests.interaction._helpers import RecordingTransport
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


def _login_server(request_states: list[str | None]) -> Server:
    """Two-round login server shared by the roundtrip pair; appends each round's request_state."""

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        # Live: the client's output-schema cache refresh calls tools/list after the tools/call result.
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
    """An input_required tools/call is auto-fulfilled by the client driver and retried to completion.

    The byte-exact requestState echo (spec MUST) is the only observable proxy for the MUST NOT
    inspect/parse/modify rule.
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
    assert request_states == [None, OPAQUE_STATE]


@requirement("mrtr:request-state-only:retry")
async def test_state_only_input_required_is_retried_with_no_responses_and_echoed_state(connect: Connect) -> None:
    """A state-only input_required result is retried with no inputResponses and the state echoed.

    No callbacks are registered: a driver that wrongly dispatched here would error the call.
    """
    resume_token = "resume-token-1"
    request_states: list[str | None] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
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
    assert request_states == [None, resume_token]


@requirement("mrtr:multi-round:complete")
async def test_server_reprompts_across_two_productive_rounds_then_completes(connect: Connect) -> None:
    """A server re-prompting with input_required across two productive rounds completes normally.

    Round 1's answer rides forward inside request_state (the spec's stateless-server pattern). Each
    retry carrying only the latest round's responses is SDK-defined (spec silent on accumulate-vs-replace).
    """
    request_states: list[str | None] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
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
async def test_multi_request_input_responses_are_keyed_by_the_input_request_keys(connect: Connect) -> None:
    """inputResponses on the retry are keyed by the inputRequests keys, each value that key's typed result.

    ElicitResult and ListRootsResult prove the map contract; sampling fidelity belongs to the sampling entries.
    """

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
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


@requirement("mrtr:input-responses:missing-reprompted")
async def test_retry_missing_a_requested_key_is_reprompted_not_errored(connect: Connect) -> None:
    """A retry omitting a requested inputResponses key is re-prompted, not errored (spec SHOULD).

    The re-prompt decision belongs to the test's handler; the SDK obligation pinned is that the partial
    map reaches the handler unmodified. Manual loop: the auto driver answers every requested key.
    """
    seen: list[set[str] | None] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="enroll", input_schema={"type": "object"})])

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

    server = Server("reprompting", on_list_tools=list_tools, on_call_tool=call_tool)

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

    assert result == snapshot(CallToolResult(content=[TextContent(text="one+two")]))
    # The partial map reached the handler as sent, not filtered or rejected.
    assert seen == [None, {"first"}, {"second"}]


@requirement("mrtr:input-responses:unknown-ignored")
async def test_retry_with_an_unrequested_extra_key_is_tolerated_and_the_call_completes(connect: Connect) -> None:
    """A retry carrying an unrequested inputResponses key completes normally (spec SHOULD: ignore).

    The ignoring happens in the test's handler; the SDK half pinned is that the stray entry is
    delivered unfiltered. Manual loop: the auto driver only answers the server's own keys.
    """
    seen: list[set[str] | None] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="greet", input_schema={"type": "object"})])

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

    server = Server("tolerant", on_list_tools=list_tools, on_call_tool=call_tool)

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

    assert result == snapshot(CallToolResult(content=[TextContent(text="hello ada")]))
    assert seen == [None, {"name", "stray"}]


@requirement("mrtr:push-api:loud-fail-2026")
async def test_push_elicit_on_2026_raises_typed_local_error_and_call_still_completes(connect: Connect) -> None:
    """A push API call on a 2026 connection raises a typed local error and the call still completes.

    Spec-mandated outcome, incidental enforcement: the gate is "no back-channel", not "wrong era".
    One push API stands for all four: they share ServerSession.send_request's channel selection.
    """
    caught: list[NoBackChannelError] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="ask", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "ask"
        try:
            await ctx.session.elicit_form("Need a name", _NAME_SCHEMA)
        except NoBackChannelError as exc:
            caught.append(exc)
        return CallToolResult(content=[TextContent(text="fallback")])

    server = Server("push", on_list_tools=list_tools, on_call_tool=call_tool)

    # Declares the elicitation capability, isolating the failure to the missing back-channel; never delivered.
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
    """PINS A KNOWN GAP: a request-scoped push elicit on in-memory 2026 transmits the forbidden frame.

    The no-back-channel gate is per-transport and the in-memory request-scoped channel still has one,
    so the failure comes back from the client's 2026 version gate instead of arising locally. When an
    era-aware send gate lands: re-pin to the local NoBackChannelError and delete the Divergence.
    """
    caught: list[MCPError] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(name="ask", input_schema={"type": "object"})])

    async def call_tool(ctx: ServerRequestContext, params: types.CallToolRequestParams) -> CallToolResult:
        assert params.name == "ask"
        assert ctx.request_id is not None
        try:
            # The related id routes the send onto the per-request dispatch channel.
            await ctx.session.elicit_form("Need a name", _NAME_SCHEMA, related_request_id=ctx.request_id)
        except MCPError as exc:
            # MCPError, not NoBackChannelError: nothing is raised locally -- the failure is the peer's answer.
            caught.append(exc)
        return CallToolResult(content=[TextContent(text="fallback")])

    server = Server("scoped-push", on_list_tools=list_tools, on_call_tool=call_tool)

    # Declares the elicitation capability; the body is itself the never-delivered assertion.
    async def never_deliverable(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        raise NotImplementedError

    async with Client(server, mode=LATEST_MODERN_VERSION, elicitation_callback=never_deliverable) as client:
        result = await client.call_tool("ask", {})

    # The connection survives the rejected frame.
    assert result == snapshot(CallToolResult(content=[TextContent(text="fallback")]))
    assert len(caught) == 1
    # Only the pre-dispatch client version gate answers data=<method>: transmission proven, callback never reached.
    assert caught[0].error == snapshot(
        ErrorData(code=METHOD_NOT_FOUND, message="Method not found", data="elicitation/create")
    )


@requirement("sampling:mrtr:capability:not-declared")
async def test_sampling_request_embedded_for_a_non_sampling_client_is_sent_and_refused_client_side(
    connect: Connect,
) -> None:
    """PINS A KNOWN GAP: an embedded sampling request an undeclared client cannot support is sent anyway.

    The SDK has no embed gate (spec MUST NOT), so the violation surfaces as the client driver's refusal
    aborting the call. When the server-side gate lands: re-pin to the gated outcome and delete the Divergence.
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

    The SDK has no embed gate (spec MUST NOT), so the violation surfaces as the client driver's refusal
    aborting the call. When the server-side gate lands: re-pin to the gated outcome and delete the Divergence.
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


# --- wire-level: the modern HTTP entry is the only 2026 framing seam ---


@requirement("mrtr:tools-call:write-once-roundtrip")
async def test_mrtr_retry_frame_carries_fresh_id_and_byte_exact_request_state() -> None:
    """The MRTR retry frame carries a fresh JSON-RPC id and the requestState key serialized byte-exact.

    Asserted at the client transport seam: the retry's id (spec MUST: the retry is an independent
    request) and the serialized key presence are invisible to API callers.
    """
    server = _login_server([])

    async def answer_login(context: ClientRequestContext, params: types.ElicitRequestParams) -> ElicitResult:
        assert isinstance(params, ElicitRequestFormParams)
        return ElicitResult(action="accept", content={"name": "octocat"})

    with anyio.fail_after(5):
        # One combined async-with, recorder bound via :=: nested async-with mis-traces exit arcs on 3.11+.
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
    # Inequality, not pinned values: the id sequence belongs to protocol:request-id:unique.
    assert first.id is not None
    assert retry.id is not None
    assert retry.id != first.id
    assert first.params is not None
    assert "requestState" not in first.params
    assert "inputResponses" not in first.params
    assert retry.params is not None
    assert retry.params["requestState"] == OPAQUE_STATE
    assert retry.params["inputResponses"]["github_login"]["action"] == "accept"
    # The interim travelled as a *result*, matched to the initial request by its id.
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

    Wire-pinned (spec MUST NOT): typed None and key-absence are indistinguishable in-memory. The
    fresh-id test above proves the same serializer emits the key when present, guarding against vacuity.
    """
    request_states: list[str | None] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
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
    # The absence is specific: no requestState key on an otherwise-loaded retry frame.
    assert "requestState" not in retry.params
    assert "inputResponses" in retry.params
    assert request_states == [None, None]


@requirement("mrtr:request-state:scoped-to-originating-request")
async def test_parallel_mrtr_calls_keep_request_state_and_responses_isolated() -> None:
    """Parallel MRTR calls keep requestState and inputResponses scoped to their originating request.

    A symmetric rendezvous in the elicitation callback forces both loops mid-flight before either
    retry leaves (spec MUST NOT). Handler capture suffices: every tools/call the client sends is
    delivered to the handler, so the captured rounds are 1:1 with the sent frames.
    """
    rounds: list[tuple[str, str | None, set[str] | None]] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
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
        rounds.append(
            (name, params.request_state, None if params.input_responses is None else set(params.input_responses))
        )
        if params.input_responses is None:
            return InputRequiredResult(
                input_requests={f"q-{name}": _form_request(f"for {name}")},
                request_state=f"state-{name}",
            )
        return CallToolResult(content=[TextContent(text=name)])

    server = Server("parallel", on_list_tools=list_tools, on_call_tool=call_tool)

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
                results[name] = await client.call_tool(name, {})

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
    the trace contains neither. The full trace is snapshotted so a frame reorder fails consciously.
    """
    elicited: list[str] = []

    async def list_tools(
        ctx: ServerRequestContext, params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
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
    # Prove the received log holds only messages before narrowing: a filtered-out transport exception would fake it.
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
    # Response ids pair the sent request ids in order; the snapshots above prove these filters drop nothing.
    requests = [message.message for message in recording.sent if isinstance(message.message, JSONRPCRequest)]
    responses = [message.message for message in received_messages if isinstance(message.message, JSONRPCResponse)]
    assert [response.id for response in responses] == [request.id for request in requests]


# --- raw 2026 dialect: malformed params can only originate from a scripted client ---


def _modern_headers(*, method: str, name: str) -> dict[str, str]:
    """Headers for a raw 2026-07-28 tools/call POST: baseline plus the modern routing/advisory headers."""
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
    """A retry whose inputResponses do not parse is rejected with invalid params before dispatch (spec SHOULD).

    Raw httpx against the mounted modern entry: the typed API rejects garbage inputResponses at
    construction, so the violation is unproducible above this seam.
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


# --- scripted server peer: byte-controlled absence of the resultType key ---


@requirement("protocol:result-type:absent-is-complete")
async def test_result_body_without_result_type_parses_as_a_complete_result() -> None:
    """A tools/call result body with no resultType key parses as the normal terminal result.

    Spec MUST: clients treat an absent resultType as "complete" (backward compatibility). The server
    is played by hand over memory streams so the key's absence is byte-controlled, not a serializer artifact.
    """

    async def scripted_server(streams: MessageStream) -> None:
        server_read, server_write = streams

        def respond(request_id: types.RequestId, result: dict[str, object]) -> SessionMessage:
            return SessionMessage(JSONRPCResponse(jsonrpc="2.0", id=request_id, result=result))

        init = await server_read.receive()
        assert isinstance(init, SessionMessage)
        assert isinstance(init.message, JSONRPCRequest)
        assert init.message.method == "initialize"
        await server_write.send(
            respond(
                init.message.id,
                InitializeResult(
                    protocol_version="2025-11-25",
                    capabilities=ServerCapabilities(),
                    server_info=Implementation(name="scripted", version="0.0.1"),
                ).model_dump(by_alias=True, mode="json", exclude_none=True),
            )
        )

        initialized = await server_read.receive()
        assert isinstance(initialized, SessionMessage)
        assert isinstance(initialized.message, JSONRPCNotification)
        assert initialized.message.method == "notifications/initialized"

        call = await server_read.receive()
        assert isinstance(call, SessionMessage)
        assert isinstance(call.message, JSONRPCRequest)
        assert call.message.method == "tools/call"
        # Deliberately no "resultType" key: the absence is the clause under test.
        await server_write.send(respond(call.message.id, {"content": [{"type": "text", "text": "plain"}]}))

        # The client's output-schema cache refresh follows the call result; stopping here hangs the test.
        refresh = await server_read.receive()
        assert isinstance(refresh, SessionMessage)
        assert isinstance(refresh.message, JSONRPCRequest)
        assert refresh.message.method == "tools/list"
        await server_write.send(
            respond(refresh.message.id, {"tools": [{"name": "x", "inputSchema": {"type": "object"}}]})
        )

    async with (
        create_client_server_memory_streams() as ((client_read, client_write), server_streams),
        anyio.create_task_group() as task_group,
        ClientSession(client_read, client_write) as session,
    ):
        task_group.start_soon(scripted_server, server_streams)
        with anyio.fail_after(5):
            await session.initialize()
            result = await session.call_tool("x", {})

        # The parse default filling "complete" IS the MUST under test.
        assert result.result_type == "complete"
        assert result == snapshot(CallToolResult(content=[TextContent(text="plain")]))


# --- unrecognized resultType: a server extension puts an arbitrary tag on the wire ---


@requirement("protocol:result-type:unrecognized-invalid")
async def test_an_unrecognized_result_type_value_is_surfaced_unchanged_instead_of_treated_as_invalid(
    connect: Connect,
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
    assert result == snapshot(CallToolResult(content=[TextContent(text="still here")], result_type="bogus"))
